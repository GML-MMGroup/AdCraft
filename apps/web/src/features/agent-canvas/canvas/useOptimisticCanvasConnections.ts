import { MarkerType, type Edge } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createOperationKey } from "../../../api/operationKey.ts";
import type { AgentCanvasWorkflowV2, CanvasBindingCreateRequestV2, CanvasBindingV2 } from "../../../types-v2.ts";
import { AGENT_CANVAS_EDGE_TYPE } from "./canvasConnectionGeometry.ts";

type PendingConnection = {
  key: string;
  request: CanvasBindingCreateRequestV2;
  edge: Edge;
  bindingId: string | null;
};
type Scope = { workflowId: string | null; active: boolean; entries: Map<string, PendingConnection> };
type Options = {
  workflow: AgentCanvasWorkflowV2 | null;
  edges: Edge[];
  createBinding: (request: CanvasBindingCreateRequestV2, options?: { isCurrent?: () => boolean }) => Promise<CanvasBindingV2 | null>;
  onError: (error: unknown) => void;
};

function identity(binding: Pick<CanvasBindingV2, "source" | "target_node_id" | "input_role">) {
  return binding.source.kind === "node_output"
    ? JSON.stringify([binding.source.source_node_id, binding.target_node_id, binding.input_role])
    : null;
}

function endpointsExist(workflow: AgentCanvasWorkflowV2 | null, entry: PendingConnection) {
  return !!workflow
    && workflow.nodes.some((node) => node.node_id === entry.edge.source)
    && workflow.nodes.some((node) => node.node_id === entry.edge.target);
}

export function useOptimisticCanvasConnections(options: Options) {
  const { workflow, edges } = options;
  const scope = useMemo<Scope>(() => ({ workflowId: workflow?.workflow_id ?? null, active: true, entries: new Map() }), [workflow?.workflow_id]);
  const current = useRef({ ...options, scope });
  current.current = { ...options, scope };
  const [snapshot, setSnapshot] = useState<{ scope: Scope; entries: PendingConnection[] }>({ scope, entries: [] });
  const publish = useCallback(() => setSnapshot({ scope, entries: [...scope.entries.values()] }), [scope]);

  useEffect(() => {
    scope.active = true;
    return () => { scope.active = false; scope.entries.clear(); };
  }, [scope]);

  const cancelForNodes = useCallback((ids: readonly string[]) => {
    const removed = new Set(ids);
    for (const [key, entry] of scope.entries) {
      if (removed.has(entry.edge.source) || removed.has(entry.edge.target)) scope.entries.delete(key);
    }
    publish();
  }, [publish, scope]);

  useEffect(() => {
    let changed = false;
    for (const [key, entry] of scope.entries) {
      if (!endpointsExist(workflow, entry) || (entry.bindingId && (
        edges.some((edge) => edge.id === entry.bindingId)
        || !workflow?.bindings.some((binding) => binding.binding_id === entry.bindingId && binding.enabled)
      ))) {
        scope.entries.delete(key);
        changed = true;
      }
    }
    if (changed) publish();
  }, [edges, workflow, snapshot, scope, publish]);

  const submit = useCallback(async (input: CanvasBindingCreateRequestV2) => {
    const key = identity(input);
    const initial = current.current;
    if (!key || input.source.kind !== "node_output" || !scope.active || initial.scope !== scope
      || scope.entries.has(key)
      || initial.workflow?.bindings.some((binding) => binding.enabled && identity(binding) === key)) return;
    const request = input;
    const entry: PendingConnection = {
      key, request, bindingId: null,
      edge: {
        id: createOperationKey("pending-connection"), source: input.source.source_node_id,
        target: input.target_node_id, sourceHandle: "output", targetHandle: "input",
        type: AGENT_CANVAS_EDGE_TYPE, selectable: false, deletable: false, focusable: false,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#686868" },
        data: { optimistic: true },
      },
    };
    if (!endpointsExist(initial.workflow, entry)) return;
    scope.entries.set(key, entry);
    publish();
    const isCurrent = () => scope.active && current.current.scope === scope
      && scope.entries.get(key) === entry && endpointsExist(current.current.workflow, entry);
    try {
      const binding = await initial.createBinding(request, { isCurrent });
      if (!isCurrent()) return;
      if (binding) {
        // Keep the preview until the canonical display list contains the response binding.
        entry.bindingId = binding.binding_id;
      } else {
        scope.entries.delete(key);
      }
      publish();
    } catch (error) {
      if (!isCurrent()) return;
      scope.entries.delete(key);
      publish();
      current.current.onError(error);
    }
  }, [publish, scope]);

  const displayEdges = useMemo(() => {
    if (snapshot.scope !== scope || !scope.active) return edges;
    const canonicalKeys = new Set(edges.flatMap((edge) => {
      const binding = edge.data?.binding as CanvasBindingV2 | undefined;
      return binding ? [identity(binding)] : [];
    }));
    const pending = snapshot.entries.filter((entry) => scope.entries.get(entry.key) === entry
      && endpointsExist(workflow, entry) && !canonicalKeys.has(entry.key)
      && !edges.some((edge) => edge.id === entry.bindingId));
    return pending.length ? [...edges, ...pending.map((entry) => entry.edge)] : edges;
  }, [edges, workflow, snapshot, scope]);

  const nextOrder = useCallback((targetId: string) => Math.max(0,
    ...(current.current.workflow?.bindings ?? [])
      .filter((binding) => binding.target_node_id === targetId).map((binding) => binding.order + 1),
    ...[...scope.entries.values()].filter((entry) => entry.request.target_node_id === targetId)
      .map((entry) => (entry.request.order ?? 0) + 1),
  ), [scope]);

  return { displayEdges, submit, cancelForNodes, nextOrder };
}
