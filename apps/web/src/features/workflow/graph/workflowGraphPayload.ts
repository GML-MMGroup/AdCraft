import type { Viewport } from "@xyflow/react";
import type { AdRequest, UploadedAsset, WorkflowGraph, WorkflowNode, WorkflowSavePayload } from "../../../types.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import { normalizeFlowEdges, toWorkflowSaveEdges } from "../canvas/flowEdges.ts";

export function toWorkflowGraphPayload(currentWorkflow: WorkflowGraph, nodes: WorkflowNode[], flowNodes: CanvasNode[], flowEdges: CanvasEdge[], currentAdRequest: AdRequest): WorkflowSavePayload {
  return {
    workflow_id: currentWorkflow.workflow_id,
    name: currentWorkflow.name ?? "Ad Workflow",
    description: currentWorkflow.description ?? "Edited workflow from canvas",
    status: currentWorkflow.status,
    metadata: { ...(currentWorkflow.metadata ?? {}), ad_request: currentAdRequest },
    ad_request: currentAdRequest,
    nodes: nodes.map((node) => ({
      id: node.id,
      workflow_id: node.workflow_id ?? currentWorkflow.workflow_id,
      node_type: node.node_type ?? node.type ?? node.id,
      category: node.category,
      title: node.title,
      description: node.description,
      position: node.position,
      config: node.config,
      prompt: node.prompt,
      override_prompt: node.override_prompt,
      input_context: node.input_context,
      output: node.output,
      input_assets: node.input_assets,
      output_assets: node.output_assets,
      content: node.content,
      metadata: node.metadata,
      status: node.status,
      locked: node.locked,
      stale: node.stale,
      stale_reason: node.stale_reason,
    })),
    edges: toWorkflowSaveEdges(flowEdges, currentWorkflow.workflow_id),
  };
}

export function toNodeMutationPayload(node: WorkflowNode, flowNode?: CanvasNode): Partial<WorkflowNode> {
  return { ...node, position: flowNode?.position ?? node.position };
}

export function stripNodeForSnapshot(node: WorkflowNode, flowNode?: CanvasNode): WorkflowNode {
  return { ...node, position: flowNode?.position ?? node.position, output: {}, output_assets: stripAssetList(node.output_assets) };
}

export function stripFlowNodeForSnapshot(node: CanvasNode): CanvasNode {
  return { ...node, selected: false, dragging: false, data: { ...node.data, output: null, onOpenMedia: undefined } };
}

export function stripAssetForSnapshot(asset: UploadedAsset): UploadedAsset {
  return { ...asset, local_path: compactSnapshotPath(asset.local_path) ?? "", public_url: compactSnapshotPath(asset.public_url) };
}

export function createLightweightCanvasSnapshot(args: {
  workflowId: string;
  nodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  edges: CanvasEdge[];
  variables?: unknown[];
  viewport?: Viewport;
}) {
  const flowNodeById = new Map(args.flowNodes.map((node) => [node.id, node]));
  return {
    workflowId: args.workflowId,
    nodes: args.nodes.map((node) => stripNodeForSnapshot(node, flowNodeById.get(node.id))),
    flowNodes: args.flowNodes.map(stripFlowNodeForSnapshot),
    edges: normalizeFlowEdges(args.edges, args.flowNodes),
    variables: args.variables ?? [],
    viewport: args.viewport,
    savedAt: new Date().toISOString(),
  };
}

function stripAssetList(value?: UploadedAsset[]) {
  return Array.isArray(value) ? value.slice(0, 8).map(stripAssetForSnapshot) : [];
}

function compactSnapshotPath(value?: string | null) {
  if (!value || /^data:/i.test(value)) return undefined;
  return value;
}
