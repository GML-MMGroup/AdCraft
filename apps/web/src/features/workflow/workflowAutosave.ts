import type { Viewport } from "@xyflow/react";
import { loadCanvasSnapshot, saveCanvasSnapshot } from "../../projects/newProject.ts";
import { dedupeAssets } from "../../workflow/assets.ts";
import { editablePromptForNode } from "../../workflow/runtimeResults.ts";
import type { CanvasPosition, UploadedAsset, WorkflowNode, WorkflowVariable } from "../../types.ts";
import { normalizeFlowEdges } from "./canvas/flowEdges.ts";
import type { CanvasEdge, CanvasNode } from "./types.ts";

const SNAPSHOT_PREVIEW_ASSET_LIMIT = 6;
const SNAPSHOT_INPUT_ASSET_LIMIT = 12;

export type WorkflowAutosaveSnapshot = {
  workflowId: string;
  nodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  edges: CanvasEdge[];
  variables?: WorkflowVariable[];
  viewport?: Viewport;
  savedAt: string;
};

export type WorkflowSnapshotPayloadInput = {
  workflowId: string;
  nodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  edges: CanvasEdge[];
  variables: WorkflowVariable[];
  viewport?: Viewport;
  normalizeEdges?: (edges: CanvasEdge[], nodes: CanvasNode[]) => CanvasEdge[];
};

export type WorkflowPositionSnapshotInput = {
  workflowId: string;
  nodes: Array<Partial<WorkflowNode> & { id: string; position?: CanvasPosition }>;
  flowNodes: Array<Partial<CanvasNode> & { id: string; position?: CanvasPosition }>;
  edges: CanvasEdge[];
  variables: WorkflowVariable[];
  viewport?: Viewport;
  existingSnapshot?: WorkflowAutosaveSnapshot | null;
  savedAt?: string;
  normalizeEdges?: (edges: CanvasEdge[], nodes: CanvasNode[]) => CanvasEdge[];
};

export function createWorkflowSnapshotPayload({
  workflowId,
  nodes,
  flowNodes,
  edges,
  variables,
  viewport,
  normalizeEdges = normalizeFlowEdges,
}: WorkflowSnapshotPayloadInput): WorkflowAutosaveSnapshot {
  const flowNodeById = new Map(flowNodes.map((node) => [node.id, node]));
  const lightNodes = nodes.map((node) => stripNodeForSnapshot(node, flowNodeById.get(node.id)));
  const lightFlowNodes = flowNodes.map(stripFlowNodeForSnapshot);
  return {
    workflowId,
    nodes: lightNodes,
    flowNodes: lightFlowNodes,
    edges: normalizeEdges(edges, lightFlowNodes),
    variables,
    viewport,
    savedAt: new Date().toISOString(),
  };
}

export function createWorkflowPositionSnapshotPayload({
  workflowId,
  nodes,
  flowNodes,
  edges,
  variables,
  viewport,
  existingSnapshot,
  savedAt = new Date().toISOString(),
  normalizeEdges = normalizeFlowEdges,
}: WorkflowPositionSnapshotInput): WorkflowAutosaveSnapshot {
  const base = existingSnapshot?.workflowId === workflowId && existingSnapshot.nodes.length
    ? existingSnapshot
    : createMinimalPositionSnapshot({
        workflowId,
        nodes,
        flowNodes,
        edges,
        variables,
        viewport,
        savedAt,
        normalizeEdges,
      });
  const nodePositionById = positionByNodeId(nodes);
  const flowPositionById = positionByNodeId(flowNodes);
  const baseNodeIds = new Set(base.nodes.map((node) => node.id));
  const baseFlowNodeIds = new Set(base.flowNodes.map((node) => node.id));
  const nextNodes = [
    ...base.nodes.map((node) => applyNodePosition(node, nodePositionById.get(node.id) ?? flowPositionById.get(node.id))),
    ...nodes.filter((node) => !baseNodeIds.has(node.id)).map((node) => minimalWorkflowNodeForPosition(workflowId, node, flowPositionById.get(node.id))),
  ];
  const nextFlowNodes = [
    ...base.flowNodes.map((node) => applyFlowNodePosition(node, flowPositionById.get(node.id) ?? nodePositionById.get(node.id))),
    ...flowNodes.filter((node) => !baseFlowNodeIds.has(node.id)).map((node) => minimalFlowNodeForPosition(node, nodePositionById.get(node.id))),
  ];

  return {
    ...base,
    workflowId,
    nodes: nextNodes,
    flowNodes: nextFlowNodes,
    edges: base.edges.length ? base.edges : normalizeEdges(edges, nextFlowNodes),
    variables: base.variables ?? variables,
    viewport,
    savedAt,
  };
}

export function stableSnapshotHash(snapshot: WorkflowAutosaveSnapshot) {
  return JSON.stringify({
    workflowId: snapshot.workflowId,
    nodes: snapshot.nodes,
    flowNodes: snapshot.flowNodes.map((node) => ({ id: node.id, position: node.position, data: node.data })),
    edges: snapshot.edges,
    variables: snapshot.variables,
    viewport: snapshot.viewport,
  });
}

export function stableSnapshotPositionHash(snapshot: WorkflowAutosaveSnapshot) {
  return JSON.stringify({
    workflowId: snapshot.workflowId,
    nodes: snapshot.nodes.map((node) => ({ id: node.id, position: node.position })),
    flowNodes: snapshot.flowNodes.map((node) => ({ id: node.id, position: node.position })),
    viewport: snapshot.viewport,
  });
}

export function scheduleWorkflowSnapshotWrite(callback: () => void, options: { timeout?: number; delayMs?: number } = {}) {
  if (typeof window.requestIdleCallback === "function") {
    const handle = window.requestIdleCallback(callback, { timeout: options.timeout ?? 900 });
    return () => window.cancelIdleCallback?.(handle);
  }
  const handle = window.setTimeout(callback, options.delayMs ?? 120);
  return () => window.clearTimeout(handle);
}

export function saveWorkflowSnapshot(storage: Storage, workflowId: string, snapshot: unknown) {
  saveCanvasSnapshot(storage, workflowId, snapshot);
}

export function loadWorkflowSnapshot(storage: Pick<Storage, "getItem" | "setItem">, workflowId: string) {
  return loadCanvasSnapshot(storage, workflowId) as WorkflowAutosaveSnapshot | undefined;
}

export function applyV2SnapshotLayoutOnly(
  freshNodes: WorkflowNode[],
  freshFlowNodes: CanvasNode[],
  snapshot: WorkflowAutosaveSnapshot,
): { nodes: WorkflowNode[]; flowNodes: CanvasNode[] } {
  const nodePositionById = new Map(snapshot.nodes.map((node) => [node.id, node.position]));
  const flowPositionById = new Map(snapshot.flowNodes.map((node) => [node.id, node.position]));

  return {
    nodes: freshNodes.map((node) => ({
      ...node,
      position: nodePositionById.get(node.id) ?? node.position,
    })),
    flowNodes: freshFlowNodes.map((node) => ({
      ...node,
      position: flowPositionById.get(node.id) ?? node.position,
      selected: false,
      dragging: false,
      data: {
        ...node.data,
        selected: false,
      },
    })),
  };
}

function createMinimalPositionSnapshot({
  workflowId,
  nodes,
  flowNodes,
  edges,
  variables,
  viewport,
  savedAt,
  normalizeEdges,
}: Omit<WorkflowPositionSnapshotInput, "existingSnapshot"> & { savedAt: string; normalizeEdges: (edges: CanvasEdge[], nodes: CanvasNode[]) => CanvasEdge[] }): WorkflowAutosaveSnapshot {
  const flowPositionById = positionByNodeId(flowNodes);
  const lightNodes = nodes.map((node) => minimalWorkflowNodeForPosition(workflowId, node, flowPositionById.get(node.id)));
  const lightFlowNodes = flowNodes.map((node) => minimalFlowNodeForPosition(node));
  return {
    workflowId,
    nodes: lightNodes,
    flowNodes: lightFlowNodes,
    edges: normalizeEdges(edges, lightFlowNodes),
    variables,
    viewport,
    savedAt,
  };
}

function applyNodePosition(node: WorkflowNode, position?: CanvasPosition): WorkflowNode {
  return position ? { ...node, position } : node;
}

function applyFlowNodePosition(node: CanvasNode, position?: CanvasPosition): CanvasNode {
  return {
    ...node,
    ...(position ? { position } : {}),
    selected: false,
    dragging: false,
    data: node.data,
  };
}

function minimalWorkflowNodeForPosition(
  workflowId: string,
  node: Partial<WorkflowNode> & { id: string; position?: CanvasPosition },
  fallbackPosition?: CanvasPosition,
): WorkflowNode {
  const nodeType = getWorkflowNodeType(node as WorkflowNode);
  return {
    id: node.id,
    workflow_id: node.workflow_id ?? workflowId,
    node_type: nodeType,
    type: node.type ?? nodeType,
    category: node.category ?? inferNodeCategory(nodeType),
    title: node.title ?? node.id,
    description: node.description,
    position: node.position ?? fallbackPosition,
    config: node.config ?? {},
    prompt: node.prompt ?? node.override_prompt ?? "",
    override_prompt: node.override_prompt ?? node.prompt ?? "",
    input_assets: [],
    output_assets: [],
    status: node.status,
    locked: Boolean(node.locked),
    stale: Boolean(node.stale),
    stale_reason: node.stale_reason ?? null,
    version: node.version,
  };
}

function minimalFlowNodeForPosition(
  node: Partial<CanvasNode> & { id: string; position?: CanvasPosition },
  fallbackPosition?: CanvasPosition,
): CanvasNode {
  return {
    ...node,
    id: node.id,
    type: node.type ?? "workflowNode",
    position: node.position ?? fallbackPosition ?? { x: 0, y: 0 },
    selected: false,
    dragging: false,
    data: (node.data ?? {}) as CanvasNode["data"],
  } as CanvasNode;
}

function positionByNodeId(nodes: Array<{ id: string; position?: CanvasPosition }>) {
  const positions = new Map<string, CanvasPosition>();
  nodes.forEach((node) => {
    if (hasCanvasPosition(node.position)) positions.set(node.id, node.position);
  });
  return positions;
}

function hasCanvasPosition(position?: CanvasPosition): position is CanvasPosition {
  return Number.isFinite(position?.x) && Number.isFinite(position?.y);
}

function stripNodeForSnapshot(node: WorkflowNode, flowNode?: CanvasNode): WorkflowNode {
  const nodeType = getWorkflowNodeType(node);
  const prompt = getNodePrompt(node) || node.prompt || node.override_prompt || "";
  return {
    id: node.id,
    workflow_id: node.workflow_id,
    node_type: nodeType,
    type: node.type ?? nodeType,
    category: node.category ?? inferNodeCategory(nodeType),
    title: node.title,
    description: node.description,
    position: flowNode?.position ?? node.position,
    config: node.config ?? {},
    prompt,
    override_prompt: node.override_prompt ?? prompt,
    input_assets: (node.input_assets ?? []).slice(0, SNAPSHOT_INPUT_ASSET_LIMIT).map(stripAssetForSnapshot),
    output_assets: dedupeAssets(node.output_assets ?? []).slice(0, SNAPSHOT_PREVIEW_ASSET_LIMIT).map(stripAssetForSnapshot),
    status: node.status,
    locked: Boolean(node.locked),
    stale: Boolean(node.stale),
    stale_reason: node.stale_reason ?? null,
    version: node.version,
  };
}

function stripFlowNodeForSnapshot(node: CanvasNode): CanvasNode {
  return {
    ...node,
    selected: false,
    dragging: false,
    data: {
      ...node.data,
      output: null,
      contentPreview: truncateSnapshotText(node.data.contentPreview),
      previewAssets: node.data.previewAssets.slice(0, SNAPSHOT_PREVIEW_ASSET_LIMIT).map(stripAssetForSnapshot),
      onOpenMedia: undefined,
    },
  };
}

export function stripAssetForSnapshot(asset: UploadedAsset): UploadedAsset {
  return {
    asset_id: asset.asset_id,
    asset_type: asset.asset_type,
    asset_role: asset.asset_role,
    filename: asset.filename,
    mime_type: asset.mime_type,
    local_path: compactSnapshotPath(asset.local_path) ?? "",
    public_url: compactSnapshotPath(asset.public_url),
    thumbnail_path: compactSnapshotPath(asset.thumbnail_path),
    thumbnail_url: compactSnapshotPath(asset.thumbnail_url),
    poster_path: compactSnapshotPath(asset.poster_path),
    poster_url: compactSnapshotPath(asset.poster_url),
    preview_path: compactSnapshotPath(asset.preview_path),
    preview_url: compactSnapshotPath(asset.preview_url),
    url: compactSnapshotPath(asset.url),
    remote_url: compactSnapshotPath(asset.remote_url),
    entity_id: asset.entity_id,
    semantic_type: asset.semantic_type,
    run_id: asset.run_id,
    version: asset.version,
    is_active: asset.is_active,
    is_archived: asset.is_archived,
  };
}

export function compactSnapshotPath(value?: string | null) {
  if (!value || /^data:/i.test(value)) return undefined;
  return value;
}

function truncateSnapshotText(value: string, limit = 240) {
  return value.length > limit ? `${value.slice(0, limit)}...` : value;
}

function getWorkflowNodeType(node: WorkflowNode) {
  return node.node_type ?? node.type ?? node.id;
}

function getNodePrompt(node: WorkflowNode) {
  return editablePromptForNode(node);
}

function inferNodeCategory(nodeType: string, fallback = "utility") {
  const kind = nodeType.toLowerCase();
  if (kind === "product-generation") return "image_generation";
  if (["character-generation", "scene-generation", "storyboard"].includes(kind)) return "image_generation";
  if (kind === "storyboard-video-generation") return "video_generation";
  if (kind === "bgm") return "audio_generation";
  if (kind === "final-composition") return "composition";
  if (kind.includes("image")) return "image_generation";
  if (kind.includes("video")) return kind.includes("final") || kind.includes("composition") ? "composition" : "video_generation";
  if (kind.includes("audio") || kind.includes("bgm") || kind.includes("voice")) return "audio_generation";
  if (kind.includes("composition") || kind.includes("export")) return "composition";
  if (["requirements", "analysis", "product", "creative", "direction", "script", "character", "scene", "storyboard", "text", "prompt", "design"].some((token) => kind.includes(token))) return "agent_text";
  if (["agent", "text"].some((token) => fallback.toLowerCase().includes(token))) return "agent_text";
  return fallback === "agent" ? "agent_text" : fallback;
}
