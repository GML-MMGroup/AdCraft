import type { CanvasEdge, CanvasNode } from "../types.ts";
import type { WorkflowEdge, WorkflowSavePayload } from "../../../types.ts";
import type { WorkflowRuntimeV2, WorkflowV2 } from "../../../types-v2.ts";

export function normalizeFlowEdges(edges: CanvasEdge[], nodes: CanvasNode[] = []): CanvasEdge[] {
  const nodeIds = new Set(nodes.map((node) => node.id));
  return edges
    .filter((edge) => !nodeIds.size || (nodeIds.has(edge.source) && nodeIds.has(edge.target)))
    .map(normalizeCanvasEdge);
}

export function normalizeCanvasEdge(edge: CanvasEdge): CanvasEdge {
  return {
    ...edge,
    id: edge.id || `${edge.source}-${edge.sourceHandle ?? "source"}-${edge.target}-${edge.targetHandle ?? "target"}`,
    sourceHandle: edge.sourceHandle ?? undefined,
    targetHandle: edge.targetHandle ?? undefined,
    data: {
      ...(edge.data ?? {}),
      label: edge.data?.label ?? (typeof edge.label === "string" ? edge.label : undefined),
      required: edge.data?.required ?? true,
    },
  };
}

export function toWorkflowSaveEdges(edges: CanvasEdge[], workflowId: string): WorkflowSavePayload["edges"] {
  return normalizeFlowEdges(edges).map((edge, index) => ({
    id: edge.id || `${edge.source}-${edge.target}-${index}`,
    workflow_id: workflowId,
    source_node_id: edge.source,
    target_node_id: edge.target,
    source_handle: edge.sourceHandle ?? null,
    target_handle: edge.targetHandle ?? null,
    label: edge.data?.label ?? (typeof edge.label === "string" ? edge.label : undefined),
    mapping: edge.data?.mapping,
    required: edge.data?.required ?? true,
  }));
}

export function mergeBackendEdgesForSave(flowEdges: CanvasEdge[], backendEdges: WorkflowEdge[], flowNodes: CanvasNode[]): CanvasEdge[] {
  const merged = [...normalizeFlowEdges(flowEdges, flowNodes)];
  const seen = new Set(merged.map((edge) => `${edge.source}->${edge.target}:${edge.sourceHandle ?? ""}:${edge.targetHandle ?? ""}`));
  for (const edge of backendEdges) {
    const source = edge.source_node_id ?? edge.source;
    const target = edge.target_node_id ?? edge.target;
    if (!source || !target) continue;
    const next = normalizeCanvasEdge({
      id: edge.id || `${source}-${target}`,
      source,
      target,
      sourceHandle: edge.source_handle ?? undefined,
      targetHandle: edge.target_handle ?? undefined,
      data: { label: edge.label, mapping: edge.mapping, required: edge.required ?? true },
    });
    const key = `${next.source}->${next.target}:${next.sourceHandle ?? ""}:${next.targetHandle ?? ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(next);
    }
  }
  return merged;
}

export function toEdgeMutationPayload(edge: Partial<CanvasEdge> | CanvasEdge): Partial<WorkflowEdge> {
  return {
    id: edge.id,
    source_node_id: edge.source,
    target_node_id: edge.target,
    source: edge.source,
    target: edge.target,
    source_handle: edge.sourceHandle ?? null,
    target_handle: edge.targetHandle ?? null,
    label: typeof edge.label === "string" ? edge.label : edge.data?.label,
    mapping: edge.data?.mapping,
    required: edge.data?.required ?? true,
  };
}

export function activeV2DisplayEdgeIds(workflow: Pick<WorkflowV2, "edges" | "slots"> | null | undefined, runtime: WorkflowRuntimeV2 | null | undefined) {
  if (!workflow || !runtime) return [];
  const activeSlotIds = new Set([...(runtime.running_slot_ids ?? []), ...(runtime.waiting_slot_ids ?? [])]);
  const activeNodeIds = new Set([...(runtime.running_node_ids ?? []), ...(runtime.waiting_node_ids ?? [])]);
  for (const slot of workflow.slots ?? []) {
    if (activeSlotIds.has(slot.slot_id)) activeNodeIds.add(slot.node_id);
  }
  return (workflow.edges ?? [])
    .filter((edge) => edge.edge_kind === "display_flow")
    .filter((edge) => activeNodeIds.has(edge.source))
    .map((edge) => edge.id || `${edge.source}-${edge.target}`);
}
