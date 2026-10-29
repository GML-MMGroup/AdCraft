import type { AgentCanvasWorkflowV2, CanvasBindingRestoreRequestV2, CanvasBindingV2, CanvasLayoutPositionV2 } from "../../../types-v2.ts";

export type CanvasHistoryEntry =
  | { kind: "create"; node_id: string }
  | { kind: "delete"; node_ids: string[]; bindings: CanvasBindingV2[] }
  | { kind: "move"; before: CanvasLayoutPositionV2[]; after: CanvasLayoutPositionV2[] }
  | { kind: "connect" | "disconnect"; binding: CanvasBindingV2 };

export type CanvasHistoryDirection = "undo" | "redo";
export type CanvasHistoryState = {
  workflowId: string | null;
  undo: CanvasHistoryEntry[];
  redo: CanvasHistoryEntry[];
};
export type CanvasHistoryAction =
  | { type: "record"; entry: CanvasHistoryEntry }
  | { type: CanvasHistoryDirection }
  | { type: "drop"; direction: CanvasHistoryDirection }
  | { type: "reset"; workflowId: string | null };

export function createCanvasHistory(workflowId: string | null): CanvasHistoryState {
  return { workflowId, undo: [], redo: [] };
}

export function canvasHistoryReducer(state: CanvasHistoryState, action: CanvasHistoryAction): CanvasHistoryState {
  if (action.type === "reset") return createCanvasHistory(action.workflowId);
  if (action.type === "record") return { ...state, undo: [...state.undo, action.entry].slice(-50), redo: [] };
  const direction = action.type === "drop" ? action.direction : action.type;
  const entry = state[direction].at(-1);
  if (!entry) return state;
  if (action.type === "drop") return { ...state, [direction]: state[direction].slice(0, -1) };
  const opposite = direction === "undo" ? "redo" : "undo";
  return {
    ...state,
    [direction]: state[direction].slice(0, -1),
    [opposite]: [...state[opposite], entry].slice(-50),
  };
}

export function bindingRestoreRequest(binding: CanvasBindingV2): CanvasBindingRestoreRequestV2 | null {
  const { binding_id, target_node_id, input_role, enabled, order, label, metadata, source } = binding;
  if (source.kind === "image_asset" && source.source_asset_version_id === null) return null;
  return {
    binding_id, target_node_id, input_role, enabled, order, label, metadata,
    source: source.kind === "node_output" ? source : {
      ...source, source_asset_version_id: source.source_asset_version_id!,
    },
  };
}

export function bindingEndpointsLive(binding: CanvasBindingV2, workflow: AgentCanvasWorkflowV2): boolean {
  const source = binding.source;
  return workflow.nodes.some((node) => node.node_id === binding.target_node_id)
    && (source.kind === "node_output"
      ? workflow.nodes.some((node) => node.node_id === source.source_node_id)
      : workflow.assets.some((asset) => asset.asset_id === source.source_asset_id));
}

export function isCanvasHistoryEntryValid(
  entry: CanvasHistoryEntry,
  direction: CanvasHistoryDirection,
  workflow: AgentCanvasWorkflowV2,
  completed: ReadonlySet<string> = new Set(),
): boolean {
  const nodeLive = (id: string) => workflow.nodes.some((node) => node.node_id === id);
  const bindingLive = (id: string) => workflow.bindings.some((binding) => binding.binding_id === id);
  switch (entry.kind) {
    case "create": return nodeLive(entry.node_id) === (direction === "undo");
    case "delete": {
      if (!entry.node_ids.every((id) => nodeLive(id) === (completed.has(`node:${id}`) ? direction === "undo" : direction === "redo"))) return false;
      // Node restore may skip bindings with missing endpoints; node presence is
      // the validity condition for that gesture. An edge-only multi-selection
      // follows the same checks as a standalone disconnect.
      return entry.node_ids.length > 0 || entry.bindings.every((binding) => {
        const restoring = direction === "undo";
        if (completed.has(`binding:${binding.binding_id}`)) return bindingLive(binding.binding_id) === restoring;
        return restoring ? !bindingLive(binding.binding_id) && bindingEndpointsLive(binding, workflow) : bindingLive(binding.binding_id);
      });
    }
    case "move": return (direction === "undo" ? entry.after : entry.before).every((position) => {
      const current = workflow.nodes.find((node) => node.node_id === position.node_id);
      return current?.position.x === position.x && current.position.y === position.y;
    });
    case "connect":
    case "disconnect": {
      const remove = (entry.kind === "connect") === (direction === "undo");
      return remove ? bindingLive(entry.binding.binding_id)
        : !bindingLive(entry.binding.binding_id) && bindingEndpointsLive(entry.binding, workflow);
    }
  }
}
