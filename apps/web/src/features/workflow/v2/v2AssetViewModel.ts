import type { AssetVersionV2, WorkflowAssetRelationV2, WorkflowV2 } from "../../../types-v2.ts";
import type { QualityReviewStatus, UploadedAsset } from "../../../types.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";

export function mergeV2ReferenceArtifacts(workflow: WorkflowV2, assets: AssetVersionV2[], relations: WorkflowAssetRelationV2[]): WorkflowV2 {
  const assetKey = (asset: AssetVersionV2) => `${asset.asset_id}:${asset.version_id}`;
  const assetMap = new Map(workflow.asset_versions.map((asset) => [assetKey(asset), asset]));
  assets.forEach((asset) => {
    if (asset.asset_id && asset.version_id) assetMap.set(assetKey(asset), asset);
  });
  const relationKey = (relation: WorkflowAssetRelationV2) =>
    relation.relation_id || `${relation.target_type ?? "slot"}:${relation.target_id ?? relation.slot_id ?? ""}:${relation.source_asset_id ?? relation.asset_id ?? ""}`;
  const relationMap = new Map((workflow.asset_relations ?? []).map((relation) => [relationKey(relation), relation]));
  relations.forEach((relation) => relationMap.set(relationKey(relation), relation));
  return {
    ...workflow,
    asset_versions: Array.from(assetMap.values()),
    asset_relations: Array.from(relationMap.values()),
  };
}

export function relationForSourceAsset(relations: WorkflowAssetRelationV2[], sourceAssetId: string, slotId: string) {
  return relations.find((relation) => {
    const relationAssetId = relation.source_asset_id ?? relation.asset_id;
    const relationTargetId = relation.target_id ?? relation.slot_id;
    return relationAssetId === sourceAssetId && relationTargetId === slotId;
  });
}

export function assetPreviewUrl(asset?: AssetVersionV2 | null) {
  if (!asset) return null;
  return versionedMediaPath(asset.public_url || asset.thumbnail_path || asset.proxy_path, asset) || null;
}

export function dedupeV2AssetVersions(assets: AssetVersionV2[]) {
  const map = new Map<string, AssetVersionV2>();
  for (const asset of assets) {
    const key = `${asset.asset_id}:${asset.version_id}`;
    if (!map.has(key)) map.set(key, asset);
  }
  return Array.from(map.values());
}

export function uploadedAssetFromV2AssetVersion(asset: AssetVersionV2): UploadedAsset {
  const assetType = asset.media_type === "text" ? "document" : asset.media_type;
  const url = asset.public_url || asset.proxy_path || asset.file_path || asset.thumbnail_path || "";
  return {
    asset_id: asset.asset_id,
    asset_type: assetType,
    media_type: asset.media_type,
    asset_role: asset.media_type === "audio" ? "audio" : "reference",
    filename: asset.semantic_type || asset.asset_id,
    mime_type: asset.mime_type || "",
    local_path: asset.file_path || "",
    url,
    public_url: asset.public_url ?? undefined,
    thumbnail_path: asset.thumbnail_path ?? undefined,
    preview_url: asset.proxy_path ?? asset.public_url ?? undefined,
    version_id: asset.version_id,
    node_run_id: asset.asset_id,
    version: asset.version_id,
    entity_id: asset.item_id ?? asset.slot_id ?? undefined,
    semantic_type: asset.semantic_type,
    library_entity_id: asset.library_entity_id ?? undefined,
    source_type: asset.source_type,
    quality_status: asset.quality_status as QualityReviewStatus | undefined,
    metadata: {
      ...(asset.metadata ?? {}),
      workflow_schema_version: 2,
      slot_id: asset.slot_id ?? null,
      item_id: asset.item_id ?? null,
      node_id: asset.node_id ?? null,
    },
  };
}

export function v2SlotUploadAttachmentId(slotId: string, file: File, index: number) {
  return `upload:${slotId}:${file.name}:${file.size}:${file.lastModified}:${index}`;
}

export function objectUrlForFile(file: File) {
  if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
    return URL.createObjectURL(file);
  }
  return null;
}

export function referenceRoleForV2SemanticType(value: string | null | undefined) {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized.includes("product")) return "product";
  if (normalized.includes("character")) return "character";
  if (normalized.includes("scene")) return "scene";
  if (normalized.includes("style")) return "style";
  if (normalized.includes("bgm") || normalized.includes("audio") || normalized.includes("music")) return "audio";
  if (normalized.includes("composition") || normalized.includes("final")) return "composition";
  if (normalized.includes("motion") || normalized.includes("video") || normalized.includes("shot")) return "motion";
  return "style";
}
