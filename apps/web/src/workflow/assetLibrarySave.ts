import type { AssetLibraryEntityType, MediaStatus, NodeRunResult, UploadedAsset, WorkflowNode } from "../types";
import { dedupeAssets } from "./assets.ts";
import { isStoryboardVideoNode, storyboardVideoReadinessFromSources } from "./mediaSegments.ts";

const SOURCE_ENTITY_FIELDS = [
  "entity_id",
  "source_entity_id",
  "character_id",
  "scene_id",
  "shot_id",
  "roleId",
  "role_id",
  "characterId",
  "sceneId",
  "shotId",
];

export function assetLibraryOutputAssetsForNode(
  node: WorkflowNode,
  run?: Pick<NodeRunResult, "node_id" | "node_type" | "status" | "output" | "output_assets"> | null,
  mediaStatus?: MediaStatus | null,
) {
  const directAssets = dedupeAssets([
    ...assetArray(run?.output_assets),
    ...assetArray(node.output_assets),
  ]);
  if (!isStoryboardVideoNode(node)) return activeWorkflowAssets(directAssets);

  const readiness = storyboardVideoReadinessFromSources({
    mediaStatus: mediaStatus ?? null,
    nodes: [{ ...node, output_assets: dedupeAssets([...directAssets, ...(node.output_assets ?? [])]) }],
    nodeRuns: run ? [run as NodeRunResult] : [],
  });
  return activeWorkflowAssets(dedupeAssets([...readiness.assets, ...directAssets]));
}

export function assetLibrarySourceEntityIdForNode(
  node: WorkflowNode,
  assets: UploadedAsset[],
  entityType?: AssetLibraryEntityType | null,
) {
  const sources = [
    ...activeWorkflowAssets(assets),
    node.output,
    node.content,
    node.metadata,
  ];
  for (const source of sources) {
    const entityId = sourceEntityIdFromUnknown(source);
    if (entityId) return entityId;
  }
  if (canUseAssetIdAsSourceEntity(node, entityType)) {
    return activeWorkflowAssets(assets)[0]?.asset_id ?? null;
  }
  return null;
}

export function assetLibraryAssetIdsForNode(assets: UploadedAsset[], sourceEntityId: string | null) {
  const activeAssets = activeWorkflowAssets(assets);
  const assetsWithEntityIds = activeAssets.filter((asset) => sourceEntityIdFromUnknown(asset));
  const scopedAssets = sourceEntityId && assetsWithEntityIds.length
    ? activeAssets.filter((asset) => sourceEntityIdFromUnknown(asset) === sourceEntityId)
    : activeAssets;
  return uniqueStrings(scopedAssets.map((asset) => asset.asset_id).filter(Boolean));
}

function assetArray(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map(normalizeAsset).filter((asset): asset is UploadedAsset => Boolean(asset));
}

function normalizeAsset(value: unknown, index: number): UploadedAsset | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const metadata = recordValue(record.metadata) ?? {};
  const path = firstString(
    record.local_path,
    metadata.local_path,
    record.public_url,
    metadata.public_url,
    record.url,
    metadata.url,
    record.remote_url,
    metadata.remote_url,
    record.uri,
    metadata.uri,
    record.path,
    metadata.path,
  );
  const assetId = firstString(record.asset_id, record.id, record.library_asset_id) ?? path ?? `asset-${index + 1}`;
  return {
    ...record,
    asset_id: assetId,
    asset_type: normalizeAssetType(record.asset_type, path),
    asset_role: firstString(record.asset_role) ?? "reference",
    filename: firstString(record.filename, record.name) ?? filenameFromPath(path) ?? assetId,
    mime_type: firstString(record.mime_type, record.content_type) ?? "",
    local_path: firstString(record.local_path, metadata.local_path, record.path, metadata.path, record.uri, metadata.uri, path) ?? "",
    url: firstString(record.url, metadata.url, record.public_url, metadata.public_url),
    remote_url: firstString(record.remote_url, metadata.remote_url),
    public_url: firstString(record.public_url, metadata.public_url),
    entity_id: firstString(record.entity_id, record.source_entity_id, metadata.entity_id, metadata.source_entity_id),
    semantic_type: firstString(record.semantic_type, metadata.semantic_type),
    metadata: Object.keys(metadata).length ? metadata : record.metadata as UploadedAsset["metadata"],
  } as UploadedAsset;
}

function normalizeAssetType(value: unknown, path?: string): UploadedAsset["asset_type"] {
  if (value === "image" || value === "video" || value === "audio" || value === "document") return value;
  const lowerPath = (path ?? "").toLowerCase();
  if (/\.(mp4|mov|webm|mkv|avi)(\?|$)/.test(lowerPath)) return "video";
  if (/\.(mp3|wav|m4a|aac|ogg)(\?|$)/.test(lowerPath)) return "audio";
  if (/\.(md|txt|pdf|doc|docx)(\?|$)/.test(lowerPath)) return "document";
  return "image";
}

function activeWorkflowAssets(assets: UploadedAsset[]) {
  const activeAssets = assets.filter((asset) => asset.is_active === true && !asset.is_archived);
  if (activeAssets.length) return activeAssets;
  const unarchivedAssets = assets.filter((asset) => !asset.is_archived);
  return unarchivedAssets.length ? unarchivedAssets : assets;
}

function canUseAssetIdAsSourceEntity(node: WorkflowNode, entityType?: AssetLibraryEntityType | null) {
  const nodeType = (node.node_type ?? node.type ?? node.id ?? "").toLowerCase();
  return entityType === "video_clip" || entityType === "bgm" || nodeType === "storyboard-video-generation" || nodeType === "bgm";
}

function sourceEntityIdFromUnknown(value: unknown, depth = 0): string | null {
  if (!value || depth > 5) return null;
  if (Array.isArray(value)) {
    for (const item of value) {
      const entityId = sourceEntityIdFromUnknown(item, depth + 1);
      if (entityId) return entityId;
    }
    return null;
  }
  if (typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  for (const field of SOURCE_ENTITY_FIELDS) {
    const entityId = firstString(record[field]);
    if (entityId) return entityId;
  }
  const metadata = recordValue(record.metadata);
  if (metadata) {
    const metadataEntityId = sourceEntityIdFromUnknown(metadata, depth + 1);
    if (metadataEntityId) return metadataEntityId;
  }
  for (const field of ["characters", "character", "scenes", "scene", "shots", "shot", "entities", "items", "assets"]) {
    const entityId = sourceEntityIdFromUnknown(record[field], depth + 1);
    if (entityId) return entityId;
  }
  return null;
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return undefined;
}

function filenameFromPath(path?: string) {
  if (!path) return undefined;
  return path.split(/[/?#]/).filter(Boolean).at(-1);
}
