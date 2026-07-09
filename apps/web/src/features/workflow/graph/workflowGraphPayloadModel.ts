import type { AdRequest, WorkflowEdge, WorkflowGraph, WorkflowNode, WorkflowSavePayload } from "../../../types.ts";
import { dedupeAssets } from "../../../workflow/assets.ts";
import { workflowEdgeMappingOrDefault } from "../../../workflow/edgeMapping.ts";
import { editablePromptForNode } from "../../../workflow/runtimeResults.ts";
import { mapWorkflowEdges } from "../canvas/workflowCanvasModel.ts";
import { getWorkflowNodeType, inferNodeCategory } from "../canvas/workflowNodeModel.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";

export function getNodePrompt(node: WorkflowNode) {
  return editablePromptForNode(node);
}

export function sanitizeInputContextForSave(context: Record<string, unknown> | undefined) {
  if (!context) return context;
  return Object.fromEntries(
    Object.entries(context).filter(([key]) => !key.startsWith("system_") && !key.startsWith("resolved_") && key !== "missing_inputs" && key !== "stale_upstream_nodes" && key !== "locked_upstream_nodes"),
  );
}

export function toWorkflowEdges(edges: CanvasEdge[]): WorkflowEdge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    source_node_id: edge.source,
    target_node_id: edge.target,
    source_handle: edge.sourceHandle ?? null,
    target_handle: edge.targetHandle ?? null,
    label: typeof edge.label === "string" ? edge.label : edge.data?.label,
    mapping: workflowEdgeMappingOrDefault(edge),
    required: edge.data?.required ?? true,
  }));
}

function toWorkflowSaveEdges(edges: CanvasEdge[], workflowId: string): WorkflowSavePayload["edges"] {
  return edges.map((edge, index) => ({
    id: edge.id || `${edge.source}-${edge.target}-${index}`,
    workflow_id: workflowId,
    source_node_id: edge.source,
    target_node_id: edge.target,
    source_handle: edge.sourceHandle ?? null,
    target_handle: edge.targetHandle ?? null,
    label: typeof edge.label === "string" ? edge.label : edge.data?.label,
    mapping: workflowEdgeMappingOrDefault(edge),
    required: edge.data?.required ?? true,
  }));
}

function mergeBackendEdgesForSave(flowEdges: CanvasEdge[], backendEdges: WorkflowEdge[], flowNodes: CanvasNode[]) {
  const merged = [...flowEdges];
  const seen = new Set(merged.map(edgeSourceTargetKey));
  for (const backendEdge of mapWorkflowEdges(backendEdges, flowNodes)) {
    const key = edgeSourceTargetKey(backendEdge);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(backendEdge);
  }
  return merged;
}

function edgeSourceTargetKey(edge: Pick<CanvasEdge, "source" | "target">) {
  return `${edge.source}->${edge.target}`;
}

export function toWorkflowGraphPayload(
  currentWorkflow: WorkflowGraph,
  nodes: WorkflowNode[],
  flowNodes: CanvasNode[],
  flowEdges: CanvasEdge[],
  currentAdRequest: AdRequest,
): WorkflowSavePayload {
  const flowNodeById = new Map(flowNodes.map((node) => [node.id, node]));
  return {
    workflow_id: currentWorkflow.workflow_id,
    name: currentWorkflow.name ?? "Ad Workflow",
    description: currentWorkflow.description ?? "Edited workflow from canvas",
    status: currentWorkflow.status,
    metadata: {
      ...(currentWorkflow as WorkflowGraph & { metadata?: Record<string, unknown> }).metadata,
      ad_request: currentAdRequest,
    },
    ad_request: currentAdRequest,
    nodes: nodes.map((node) => {
      const nodeType = getWorkflowNodeType(node);
      const prompt = getNodePrompt(node) || node.prompt || node.override_prompt || "";
      const isRequirementsNode = nodeType === "requirements-analysis" || node.id === "requirements-analysis";
      const requirementContext = isRequirementsNode
        ? {
            ...currentAdRequest,
            ad_request: currentAdRequest,
            prompt,
          }
        : sanitizeInputContextForSave(node.input_context);

      return {
        id: node.id,
        workflow_id: currentWorkflow.workflow_id,
        node_type: nodeType,
        category: inferNodeCategory(nodeType),
        title: node.title,
        description: node.description,
        position: flowNodeById.get(node.id)?.position ?? node.position,
        config: node.config ?? {},
        prompt,
        override_prompt: node.override_prompt ?? prompt,
        input_context: sanitizeInputContextForSave(requirementContext),
        output: node.output ?? {},
        input_assets: node.input_assets ?? [],
        output_assets: dedupeAssets(node.output_assets ?? []),
        content: {
          ...(node.content ?? {}),
          ...(isRequirementsNode ? { ad_request: currentAdRequest, prompt } : {}),
        },
        metadata: {
          ...(node.metadata ?? {}),
          ...(isRequirementsNode ? { ad_request: currentAdRequest } : {}),
        },
        status: node.status,
        locked: Boolean(node.locked),
        stale: Boolean(node.stale),
        stale_reason: node.stale_reason ?? null,
      };
    }),
    edges: toWorkflowSaveEdges(
      mergeBackendEdgesForSave(flowEdges, currentWorkflow.edges ?? [], flowNodes),
      currentWorkflow.workflow_id,
    ),
  };
}

export function toNodeMutationPayload(node: WorkflowNode, flowNode?: CanvasNode): Partial<WorkflowNode> {
  const nodeType = getWorkflowNodeType(node);
  return {
    id: node.id,
    node_type: nodeType,
    type: nodeType,
    category: node.category ?? inferNodeCategory(nodeType),
    title: node.title,
    description: node.description,
    position: flowNode?.position ?? node.position,
    config: node.config ?? {},
    prompt: getNodePrompt(node) || node.prompt || node.override_prompt || "",
    override_prompt: node.override_prompt ?? getNodePrompt(node) ?? node.prompt ?? "",
    input_assets: node.input_assets,
    locked: Boolean(node.locked),
  };
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
    mapping: edge.source && edge.target ? workflowEdgeMappingOrDefault(edge as CanvasEdge) : undefined,
    required: edge.data?.required ?? true,
  };
}
