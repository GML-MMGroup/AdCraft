import type { NodeRunResult, WorkflowEdge, WorkflowGraph } from "../../../types.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import { normalizeFlowEdges } from "../canvas/flowEdges.ts";

export type WorkflowNodeMapOptions = {
  projectId?: string | null;
  workflowId?: string | null;
};

export function mapWorkflowNodes(workflow: WorkflowGraph, _nodeRuns: NodeRunResult[] = [], options: WorkflowNodeMapOptions = {}): CanvasNode[] {
  return (workflow.nodes ?? []).map((node) => ({
    id: node.id,
    type: "workflowNode",
    position: node.position ?? { x: 0, y: 0 },
    data: {
      title: node.title,
      description: node.description ?? "",
      status: node.status ?? "idle",
      nodeId: node.id,
      nodeType: node.node_type ?? node.type ?? node.id,
      kind: node.node_type ?? node.type ?? node.id,
      family: "Utility",
      category: node.category ?? "utility",
      contentPreview: node.prompt ?? "",
      output: node.output,
      outputCount: node.output_assets?.length ?? 0,
      previewAssets: node.output_assets ?? [],
      inputPorts: [],
      outputPorts: [],
      projectId: options.projectId,
      workflowId: options.workflowId ?? workflow.workflow_id,
    },
  }));
}

export function mapWorkflowEdges(edges: WorkflowEdge[], flowNodes: CanvasNode[]): CanvasEdge[] {
  const nodeIds = new Set(flowNodes.map((node) => node.id));
  return normalizeFlowEdges(
    edges.flatMap((edge) => {
      const source = edge.source_node_id ?? edge.source;
      const target = edge.target_node_id ?? edge.target;
      if (!source || !target || (nodeIds.size && (!nodeIds.has(source) || !nodeIds.has(target)))) return [];
      return [{
        id: edge.id || `${source}-${target}`,
        source,
        target,
        sourceHandle: edge.source_handle ?? undefined,
        targetHandle: edge.target_handle ?? undefined,
        data: { label: edge.label, mapping: edge.mapping, required: edge.required ?? true },
      }];
    }),
    flowNodes,
  );
}
