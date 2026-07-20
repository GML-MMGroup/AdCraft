import { ApiError } from "../../../api/client";
import { assetReferenceFromLibraryEntity } from "../../../workflow/assetMentions";
import type {
  AssetLibraryEntitySummary,
  AssetLibraryEntityType,
  AssetLibraryReference,
  UploadedAsset,
  WorkflowNode,
} from "../../../types";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel";
import { activeWorkflowAssets } from "./workflowAssetPreviewModel";

export function setUniquePrimaryReference(current: string[], selectedEntities: AssetLibraryEntitySummary[], entity: AssetLibraryEntitySummary) {
  if (current.includes(entity.entity_id)) return current.filter((id) => id !== entity.entity_id);
  const sameEntityTypeReferences = selectedEntities.filter((item) => item.entity_type === entity.entity_type);
  const sameEntityTypeIds = new Set(sameEntityTypeReferences.map((item) => item.entity_id));
  return [...current.filter((id) => !sameEntityTypeIds.has(id)), entity.entity_id];
}

export function libraryEntitiesToReferences(
  entities: AssetLibraryEntitySummary[],
  patch: Partial<AssetLibraryReference> = {},
  options: { primaryReferenceIds?: Set<string> } = {},
): AssetLibraryReference[] {
  const primaryReferenceIds = options.primaryReferenceIds ?? new Set<string>();
  return entities.map((entity) =>
    assetReferenceFromLibraryEntity(entity, {
      ...patch,
      is_primary: primaryReferenceIds.has(entity.entity_id),
    }),
  );
}

export function isAssetLibrarySourcedAsset(asset: UploadedAsset) {
  const record = asset as UploadedAsset & Record<string, unknown>;
  return (
    String(record.source_type ?? "").toLowerCase() === "asset_library" ||
    typeof record.library_entity_id === "string" ||
    Array.isArray(record.library_entity_ids) ||
    derivedLibraryEntitiesForAsset(asset).length > 0
  );
}

export function derivedLibraryEntitiesForAsset(asset: UploadedAsset) {
  const record = asset as UploadedAsset & Record<string, unknown>;
  const metadata = record.metadata && typeof record.metadata === "object" ? (record.metadata as Record<string, unknown>) : {};
  return stringArrayFromUnknown(record.derived_from_library_entities ?? metadata.derived_from_library_entities);
}

export function canSaveNodeToAssetLibrary(node?: WorkflowNode | null) {
  return Boolean(node && inferAssetLibraryEntityType(node));
}

export function inferAssetLibraryEntityType(node: WorkflowNode): AssetLibraryEntityType | null {
  const nodeType = getWorkflowNodeType(node).toLowerCase();
  if (nodeType === "character-generation") return "character";
  if (nodeType === "scene-generation") return "scene";
  if (nodeType === "storyboard") return "storyboard_shot";
  if (nodeType === "storyboard-video-generation") return "video_clip";
  if (nodeType === "bgm") return "bgm";
  return null;
}

export function assetLibraryDisplayNameForNode(node: WorkflowNode, assets: UploadedAsset[]) {
  return getStringFromRecord(node.output, "display_name") || getStringFromRecord(node.output, "name") || getStringFromRecord(node.content, "display_name") || activeWorkflowAssets(assets)[0]?.filename || node.title;
}

export function splitAssetLibraryTags(value: string) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function formatAssetLibraryError(error: unknown) {
  const code = error instanceof ApiError ? apiErrorCode(error.payload) : "";
  if (code === "workflow_asset_not_found") return "Source workflow asset is no longer available.";
  if (code === "no_active_assets_for_entity") return "This entity has no active assets to save.";
  if (code === "asset_library_entity_not_found") return "Asset Library entity was not found. Refresh the list and try again.";
  if (code === "invalid_entity_type") return "This entity type is not supported by the Asset Library.";
  if (code === "invalid_semantic_type") return "This semantic type is not supported by the Asset Library.";
  if (code === "asset_file_missing") return "The asset file is missing on the backend.";
  return error instanceof Error ? error.message : "Saving to Asset Library failed.";
}

function getStringFromRecord(record: Record<string, unknown> | undefined, key: string) {
  const value = record?.[key];
  return typeof value === "string" ? value : "";
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function stringArrayFromUnknown(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    if (item && typeof item === "object") {
      const record = item as Record<string, unknown>;
      const entityId = stringFromUnknown(record.entity_id) || stringFromUnknown(record.library_entity_id);
      return entityId ? [entityId] : [];
    }
    return [];
  });
}

function apiErrorCode(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  if (typeof record.code === "string") return record.code;
  if (typeof record.error === "string") return record.error;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const detailRecord = detail as Record<string, unknown>;
    return String(detailRecord.code ?? detailRecord.error ?? detailRecord.type ?? "");
  }
  return "";
}
