import type { CanvasPosition, WorkflowGraph, WorkflowNode } from "../../../types.ts";
import type { CanvasNode, WorkflowNodeData } from "../types.ts";

export type WorkflowDocumentCommand =
  | {
      type: "patch-nodes";
      nodeIds: readonly string[] | ReadonlySet<string>;
      patch: Partial<WorkflowNode>;
      canvasDataPatch?: (node: CanvasNode) => Partial<WorkflowNodeData>;
    }
  | {
      type: "move-node";
      nodeId: string;
      position: CanvasPosition;
    }
  | {
      type: "set-node-positions";
      positions: ReadonlyMap<string, CanvasPosition>;
    }
  | {
      type: "transform-nodes";
      transformWorkflowNode: (
        node: WorkflowNode,
        nodes: WorkflowNode[],
      ) => WorkflowNode;
      transformCanvasNode: (
        node: CanvasNode,
        nodes: CanvasNode[],
      ) => CanvasNode;
    };

export type WorkflowDocumentCommandTargets = {
  setWorkflow: (update: (current: WorkflowGraph | null) => WorkflowGraph | null) => void;
  setCanvasNodes: (update: (current: WorkflowNode[]) => WorkflowNode[]) => void;
  setFlowNodes: (update: (current: CanvasNode[]) => CanvasNode[]) => void;
};

export function dispatchWorkflowDocumentCommand(
  targets: WorkflowDocumentCommandTargets,
  command: WorkflowDocumentCommand,
) {
  targets.setWorkflow((current) => (
    current ? applyWorkflowDocumentCommand(current, command) : current
  ));
  targets.setCanvasNodes((current) => applyWorkflowNodeListCommand(current, command));
  targets.setFlowNodes((current) => applyCanvasNodeListCommand(current, command));
}

export function applyWorkflowDocumentCommand(
  workflow: WorkflowGraph,
  command: WorkflowDocumentCommand,
): WorkflowGraph {
  const nodes = applyWorkflowNodeListCommand(workflow.nodes, command);
  return nodes === workflow.nodes ? workflow : { ...workflow, nodes };
}

export function applyWorkflowNodeListCommand(
  nodes: WorkflowNode[],
  command: WorkflowDocumentCommand,
): WorkflowNode[] {
  if (command.type === "transform-nodes") {
    return mapChanged(nodes, (node) => command.transformWorkflowNode(node, nodes));
  }
  if (command.type === "move-node") {
    return mapChanged(nodes, (node) => {
      if (node.id !== command.nodeId || samePosition(node.position, command.position)) {
        return node;
      }
      return { ...node, position: command.position };
    });
  }
  if (command.type === "set-node-positions") {
    return mapChanged(nodes, (node) => {
      const position = command.positions.get(node.id);
      if (!position || samePosition(node.position, position)) return node;
      return { ...node, position };
    });
  }

  const nodeIds = command.nodeIds instanceof Set
    ? command.nodeIds
    : new Set(command.nodeIds);
  return mapChanged(nodes, (node) => (
    nodeIds.has(node.id) ? patchWorkflowNode(node, command.patch) : node
  ));
}

export function applyCanvasNodeListCommand(
  nodes: CanvasNode[],
  command: WorkflowDocumentCommand,
): CanvasNode[] {
  if (command.type === "transform-nodes") {
    return mapChanged(nodes, (node) => command.transformCanvasNode(node, nodes));
  }
  if (command.type === "move-node") {
    return mapChanged(nodes, (node) => {
      if (node.id !== command.nodeId || samePosition(node.position, command.position)) {
        return node;
      }
      return { ...node, position: command.position };
    });
  }
  if (command.type === "set-node-positions") {
    return mapChanged(nodes, (node) => {
      const position = command.positions.get(node.id);
      if (!position || samePosition(node.position, position)) return node;
      return { ...node, position };
    });
  }

  const nodeIds = command.nodeIds instanceof Set
    ? command.nodeIds
    : new Set(command.nodeIds);
  return mapChanged(nodes, (node) => {
    if (!nodeIds.has(node.id)) return node;
    const nextData: WorkflowNodeData = {
      ...node.data,
      ...(command.patch.status !== undefined ? { status: command.patch.status } : {}),
      ...(command.patch.version !== undefined ? { version: command.patch.version } : {}),
      ...(command.patch.locked !== undefined ? { locked: command.patch.locked } : {}),
      ...(command.patch.stale !== undefined ? { stale: command.patch.stale } : {}),
      ...(command.patch.stale_reason !== undefined
        ? { staleReason: command.patch.stale_reason }
        : {}),
      ...(command.canvasDataPatch?.(node) ?? {}),
    };
    const position = command.patch.position ?? node.position;
    if (samePosition(node.position, position) && shallowEqual(node.data, nextData)) {
      return node;
    }
    return {
      ...node,
      position,
      data: nextData,
    };
  });
}

function patchWorkflowNode(
  node: WorkflowNode,
  patch: Partial<WorkflowNode>,
): WorkflowNode {
  for (const [key, value] of Object.entries(patch)) {
    if (key === "position") {
      if (!samePosition(node.position, value as CanvasPosition | undefined)) {
        return { ...node, ...patch };
      }
      continue;
    }
    if (!Object.is(node[key as keyof WorkflowNode], value)) {
      return { ...node, ...patch };
    }
  }
  return node;
}

function mapChanged<T>(items: T[], mapItem: (item: T) => T): T[] {
  let changed = false;
  const next = items.map((item) => {
    const mapped = mapItem(item);
    if (mapped !== item) changed = true;
    return mapped;
  });
  return changed ? next : items;
}

function samePosition(
  left: CanvasPosition | undefined,
  right: CanvasPosition | undefined,
) {
  return left?.x === right?.x && left?.y === right?.y;
}

function shallowEqual(
  left: Record<string, unknown>,
  right: Record<string, unknown>,
) {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key) => Object.is(left[key], right[key]));
}
