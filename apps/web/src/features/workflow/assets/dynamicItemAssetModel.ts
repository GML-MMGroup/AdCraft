import type { AssetLibraryRefreshEventDetail } from "../../../api/workflowNormalizers";
import type { CanvasRuntimeCandidatePayload, CanvasRuntimeEvent } from "../../../workflow/canvasRuntime";
import { localRevisionEntityId, localRevisionSemanticType } from "../../../workflow/localRevision";
import type { DynamicMediaItem, UploadedAsset } from "../../../types";

export function dynamicItemActionAsset(item: DynamicMediaItem, asset?: UploadedAsset): UploadedAsset {
  const base = asset ?? item.outputAssets[0];
  const semanticType = item.semanticType ?? base?.semantic_type ?? "unknown";
  return {
    ...(base ?? {}),
    asset_id: base?.asset_id ?? item.itemId,
    asset_type: base?.asset_type ?? (item.itemType === "storyboard_video" ? "video" : "image"),
    asset_role: base?.asset_role ?? "reference",
    filename: base?.filename ?? item.displayName,
    mime_type: base?.mime_type ?? "application/octet-stream",
    local_path: base?.local_path ?? "",
    entity_id: item.itemId,
    semantic_type: semanticType,
  };
}

export function patchAssetLibraryState(asset: UploadedAsset | null | undefined, candidate: CanvasRuntimeCandidatePayload): UploadedAsset | null | undefined {
  if (!asset) return asset;
  const matchesTarget =
    (candidate.targetAssetId && asset.asset_id === candidate.targetAssetId) ||
    (candidate.libraryAssetId && (asset.asset_id === candidate.libraryAssetId || asset.library_asset_id === candidate.libraryAssetId || asset.library_asset_ids?.includes(candidate.libraryAssetId))) ||
    (candidate.entityId && candidate.semanticType && localRevisionEntityId(asset) === candidate.entityId && localRevisionSemanticType(asset) === candidate.semanticType);
  if (!matchesTarget) return asset;
  const libraryAssetIds = candidate.libraryAssetId ? Array.from(new Set([...(asset.library_asset_ids ?? []), candidate.libraryAssetId])) : asset.library_asset_ids;
  return {
    ...asset,
    ...(candidate.libraryState ? { library_state: candidate.libraryState } : {}),
    ...(candidate.libraryEntityId ? { library_entity_id: candidate.libraryEntityId } : {}),
    ...(candidate.libraryAssetId ? { library_asset_id: candidate.libraryAssetId, library_asset_ids: libraryAssetIds } : {}),
    ...(candidate.libraryError ? { library_error: candidate.libraryError } : {}),
    ...(candidate.sourceType ? { source_type: candidate.sourceType } : {}),
  };
}

export function assetLibraryRefreshDetailFromEvent(workflowId: string, event: CanvasRuntimeEvent): AssetLibraryRefreshEventDetail {
  const payload = event.payload ?? {};
  const libraryAssetId = stringFromUnknown(payload.library_asset_id) || stringFromUnknown(payload.asset_id);
  return {
    event_type: event.event_type,
    workflow_id: workflowId,
    node_id: event.node_id ?? null,
    library_entity_id: stringFromUnknown(payload.library_entity_id) || stringFromUnknown(payload.entity_id) || null,
    library_asset_id: libraryAssetId || null,
    library_asset_ids: libraryAssetId ? [libraryAssetId] : undefined,
    library_state: stringFromUnknown(payload.library_state) || libraryStateFromAssetLibraryEvent(event.event_type),
    library_error: stringFromUnknown(payload.library_error) || stringFromUnknown(payload.library_ingest_error) || stringFromUnknown(payload.error) || null,
    source_type: stringFromUnknown(payload.source_type) || null,
    semantic_type: stringFromUnknown(payload.semantic_type) || undefined,
  };
}

export function assetLibraryRefreshDetailFromItemRegenerate(
  workflowId: string,
  nodeId: string,
  item: DynamicMediaItem,
  result: Record<string, unknown>,
): AssetLibraryRefreshEventDetail {
  const workingVersion = recordFromUnknown(result.current_working_version);
  const workingAssets = Array.isArray(workingVersion?.assets) ? workingVersion.assets.filter((asset): asset is UploadedAsset => Boolean(asset && typeof asset === "object")) : [];
  const asset = workingAssets[0] ?? item.currentWorkingVersion?.assets?.[0] ?? item.outputAssets[0] ?? null;
  const libraryAssetId = stringFromUnknown(result.library_asset_id) || stringFromUnknown(asset?.library_asset_id);
  return {
    event_type: "node_item_regenerated",
    workflow_id: workflowId,
    node_id: nodeId,
    asset_id: stringFromUnknown(asset?.asset_id) || undefined,
    library_entity_id: stringFromUnknown(result.library_entity_id) || stringFromUnknown(asset?.library_entity_id) || item.libraryEntityId || null,
    library_asset_id: libraryAssetId || null,
    library_asset_ids: libraryAssetId ? [libraryAssetId] : undefined,
    library_state: stringFromUnknown(result.library_state) || stringFromUnknown(asset?.library_state) || item.libraryState || null,
    library_error: stringFromUnknown(result.library_error) || stringFromUnknown(asset?.library_error) || item.libraryError || null,
    source_type: stringFromUnknown(result.source_type) || stringFromUnknown(asset?.source_type) || item.sourceType || "workflow_generation",
    semantic_type: stringFromUnknown(result.semantic_type) || item.semanticType || asset?.semantic_type || undefined,
  };
}

function libraryStateFromAssetLibraryEvent(eventType: string) {
  if (eventType === "asset_library_entity_created") return "created";
  if (eventType === "asset_library_entity_linked" || eventType === "asset_library_asset_linked") return "linked";
  if (eventType === "asset_library_ingest_failed") return "failed";
  return null;
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
