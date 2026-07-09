import type {
  CanvasTargetReference,
  DynamicMediaItem,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowNode,
} from "../types";
import { dedupeAssets } from "./assets.ts";
import { canvasTargetReferenceFromAsset, canvasTargetReferenceFromDynamicItem } from "./canvasTargets.ts";
import { dynamicMediaItemsForNode } from "./dynamicMediaItems.ts";

export type CanvasEntityAreaKind = "character" | "scene" | "storyboard" | "storyboard_video" | "bgm";

export type CanvasEntityAreaItem = DynamicMediaItem & {
  primaryAsset?: UploadedAsset;
  supplementalAssets: UploadedAsset[];
  targetReference: CanvasTargetReference;
  assetTargetReferences: CanvasTargetReference[];
};

export type CanvasEntityArea = {
  kind: CanvasEntityAreaKind;
  title: string;
  nodeId: string;
  nodeType: string;
  statusSummary: string;
  items: CanvasEntityAreaItem[];
};

type CanvasEntityAreaOptions = {
  run?: NodeRunResult | null;
  resolvedInputs?: ResolvedNodeInputs | null;
  outputAssets?: UploadedAsset[];
};

type CanvasEntityAreaConfig = {
  kind: CanvasEntityAreaKind;
  title: string;
};

export function buildCanvasEntityArea(node: WorkflowNode, options: CanvasEntityAreaOptions = {}): CanvasEntityArea | null {
  const nodeType = workflowNodeType(node);
  const config = canvasEntityAreaConfig(nodeType);
  if (!config) return null;

  const items = dynamicMediaItemsForNode(node, options)
    .filter((item) => item.itemId && shouldShowCanvasEntityItem(item))
    .map((item) => canvasEntityAreaItem(node, item));
  if (!items.length) return null;

  return {
    kind: config.kind,
    title: config.title,
    nodeId: node.id,
    nodeType,
    statusSummary: canvasEntityAreaStatusSummary(items),
    items,
  };
}

export function isCanvasEntityAreaNode(nodeType?: string | null) {
  return Boolean(nodeType && canvasEntityAreaConfig(nodeType));
}

function canvasEntityAreaItem(node: WorkflowNode, item: DynamicMediaItem): CanvasEntityAreaItem {
  const assets = dedupeAssets(item.outputAssets);
  return {
    ...item,
    outputAssets: assets,
    primaryAsset: primaryAssetForItem(item, assets),
    supplementalAssets: supplementalAssetsForItem(item, assets),
    targetReference: canvasTargetReferenceFromDynamicItem(node, item),
    assetTargetReferences: assets.map((asset) => canvasTargetReferenceFromAsset(node, item, asset)),
  };
}

function primaryAssetForItem(item: DynamicMediaItem, assets: UploadedAsset[]) {
  if (item.itemType === "character") {
    return item.mainAsset ?? assets.find((asset) => asset.semantic_type === "character_main") ?? assets[0];
  }
  if (item.itemType === "scene") {
    return item.mainAsset ?? assets.find((asset) => asset.semantic_type === "scene_main") ?? assets[0];
  }
  if (item.itemType === "storyboard_image") {
    return assets.find((asset) => asset.semantic_type === "storyboard_image") ?? assets[0];
  }
  if (item.itemType === "storyboard_video") {
    return assets.find((asset) => asset.asset_type === "video") ?? assets[0];
  }
  if (item.itemType === "bgm") {
    return assets.find((asset) => asset.asset_type === "audio") ?? assets[0];
  }
  return assets[0];
}

function supplementalAssetsForItem(item: DynamicMediaItem, assets: UploadedAsset[]) {
  const primary = primaryAssetForItem(item, assets);
  if (item.itemType === "character") {
    const ordered = [item.faceIdAsset, item.threeViewAsset, ...assets].filter((asset): asset is UploadedAsset => Boolean(asset));
    return dedupeAssets(ordered).filter((asset) => asset.asset_id !== primary?.asset_id);
  }
  if (item.itemType === "scene") {
    const ordered = [item.multiViewAsset, ...assets].filter((asset): asset is UploadedAsset => Boolean(asset));
    return dedupeAssets(ordered).filter((asset) => asset.asset_id !== primary?.asset_id);
  }
  return assets.filter((asset) => asset.asset_id !== primary?.asset_id);
}

function shouldShowCanvasEntityItem(item: DynamicMediaItem) {
  return Boolean(item.outputAssets.length || item.prompt || item.status === "running" || item.status === "waiting" || item.status === "queued" || item.error || item.errorCode);
}

function canvasEntityAreaConfig(nodeType: string): CanvasEntityAreaConfig | null {
  const normalized = normalizeNodeType(nodeType);
  if (normalized === "character-generation") return { kind: "character", title: "角色设计区" };
  if (normalized === "scene-generation") return { kind: "scene", title: "场景设计区" };
  if (normalized === "storyboard") return { kind: "storyboard", title: "Storyboard design area" };
  if (normalized === "storyboard-video-generation") return { kind: "storyboard_video", title: "Storyboard video area" };
  if (normalized === "bgm") return { kind: "bgm", title: "Music design area" };
  return null;
}

function canvasEntityAreaStatusSummary(items: DynamicMediaItem[]) {
  const counts = new Map<string, number>();
  for (const item of items) {
    const status = normalizeStatus(item.status);
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([status, count]) => `${count} ${status}`)
    .join(" · ");
}

function normalizeStatus(value?: string | null) {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized || "unknown";
}

function normalizeNodeType(value: string) {
  return value.toLowerCase().replace(/_/g, "-");
}

function workflowNodeType(node: Pick<WorkflowNode, "id" | "node_type" | "type">) {
  return node.node_type ?? node.type ?? node.id;
}
