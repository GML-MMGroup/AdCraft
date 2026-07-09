import type {
  AssetLibraryReference,
  DynamicMediaItem,
  RevisionCandidateState,
  UploadedAsset,
  WorkflowNode,
  WorkflowRevisionRequest,
  WorkflowRevisionState,
} from "../types";

type RevisionRequestOptions = {
  mode: string;
  instruction?: string | null;
  selected_asset_id?: string | null;
  asset_references?: AssetLibraryReference[];
};

type ItemRevisionRequestOptions = {
  instruction?: string | null;
  asset_references?: AssetLibraryReference[];
};

export const LOCAL_REVISION_PENDING_CANDIDATE_LIMIT = 5;

export function localRevisionStateKey(
  workflowId: string,
  nodeId: string,
  asset: Pick<UploadedAsset, "asset_id" | "asset_type" | "entity_id" | "semantic_type">,
) {
  return [
    workflowId,
    nodeId,
    localRevisionEntityId(asset),
    localRevisionSemanticType(asset),
  ].join("::");
}

export function localRevisionRequestForAsset(
  node: Pick<WorkflowNode, "id" | "node_type" | "type">,
  asset: UploadedAsset,
  options: RevisionRequestOptions,
): WorkflowRevisionRequest {
  const targetAssetId = options.selected_asset_id || asset.asset_id;
  const instruction = options.instruction?.trim();
  return {
    mode: options.mode,
    target_entity_id: localRevisionEntityId(asset),
    target_asset_id: targetAssetId,
    semantic_type: localRevisionSemanticType(asset),
    target_field: localRevisionTargetField(asset),
    instruction: instruction || null,
    preserve_other_outputs: true,
    asset_references: options.asset_references ?? [],
  };
}

export function localRevisionRequestForItem(
  node: Pick<WorkflowNode, "id" | "node_type" | "type">,
  item: DynamicMediaItem,
  options: ItemRevisionRequestOptions = {},
): WorkflowRevisionRequest {
  const semanticType = item.semanticType ?? semanticTypeForItemType(item.itemType);
  const targetAsset = item.outputAssets[0];
  const instruction = options.instruction?.trim() || "Regenerate this item using its current prompt.";
  const targetAssetId = targetAsset?.asset_id || item.itemId;
  const targetField = localRevisionTargetField({
    asset_type: targetAsset?.asset_type ?? assetTypeForSemanticType(semanticType),
    semantic_type: semanticType,
  });
  return {
    mode: "regenerate_entity",
    target_entity_id: item.itemId,
    target_asset_id: targetAssetId,
    semantic_type: semanticType,
    target_field: targetField,
    instruction,
    preserve_other_outputs: true,
    asset_references: options.asset_references ?? [],
    metadata: {
      item_id: item.itemId,
      item_type: item.itemType,
      item_prompt: item.prompt,
    },
  };
}

export function localRevisionEntityId(asset: Pick<UploadedAsset, "asset_id" | "entity_id">) {
  return asset.entity_id || asset.asset_id;
}

export function localRevisionSemanticType(asset: Pick<UploadedAsset, "asset_type" | "semantic_type">) {
  return asset.semantic_type || asset.asset_type;
}

export function localRevisionTargetField(asset: Pick<UploadedAsset, "asset_type" | "semantic_type">) {
  const semanticType = localRevisionSemanticType(asset);
  const canonicalFields: Record<string, string> = {
    character_main: "roleMainImageUri",
    character_face_id: "roleFaceIdImageUri",
    character_three_view: "roleThreeViewImageUri",
    character_concept: "roleConceptImageUri",
    scene_main: "sceneMainImageUri",
    scene_multi_view: "sceneMultiViewImageUri",
    storyboard_image: "storyboardImageUri",
    storyboard_video: "storyboardVideoUri",
    product_image: "productImageUri",
    bgm: "musicUri",
  };
  const canonicalField = canonicalFields[semanticType];
  if (canonicalField) return canonicalField;
  if (asset.asset_type === "video") return "videoUri";
  if (asset.asset_type === "audio") return "audioUri";
  return "imageUri";
}

function semanticTypeForItemType(itemType: DynamicMediaItem["itemType"]) {
  if (itemType === "character") return "character_main";
  if (itemType === "scene") return "scene_main";
  if (itemType === "storyboard_image") return "storyboard_image";
  if (itemType === "storyboard_video") return "storyboard_video";
  if (itemType === "bgm") return "bgm";
  if (itemType === "product_image") return "product_image";
  return "unknown";
}

function assetTypeForSemanticType(semanticType: string) {
  const normalized = semanticType.toLowerCase();
  if (normalized.includes("video")) return "video";
  if (normalized === "bgm" || normalized.includes("music") || normalized.includes("audio")) return "audio";
  return "image";
}

export function revisionGenerationStatus(revision?: WorkflowRevisionState | null) {
  if (!revision) return "";
  return normalizedRevisionStatus(readRecordValue(revision, "generation_status")) || normalizedRevisionStatus(revision.status);
}

export function revisionAcceptanceStatus(revision?: WorkflowRevisionState | null) {
  if (!revision) return "";
  return normalizedRevisionStatus(readRecordValue(revision, "acceptance_status"));
}

export function revisionVisibilityStatus(revision?: WorkflowRevisionState | null) {
  if (!revision) return "";
  return normalizedRevisionStatus(readRecordValue(revision, "visibility_status"));
}

export function isPendingVisibleRevisionCandidate(revision?: WorkflowRevisionState | null) {
  return (
    revisionGenerationStatus(revision) === "completed" &&
    revisionAcceptanceStatus(revision) === "pending" &&
    revisionVisibilityStatus(revision) === "visible"
  );
}

export function pendingVisibleRevisionCandidates(revisions: WorkflowRevisionState[] = [], limit = LOCAL_REVISION_PENDING_CANDIDATE_LIMIT) {
  return revisions
    .map((revision, index) => ({ revision, index, time: revisionSortTime(revision) }))
    .filter((entry) => isPendingVisibleRevisionCandidate(entry.revision))
    .sort((left, right) => right.time - left.time || right.index - left.index)
    .slice(0, limit)
    .map((entry) => entry.revision);
}

export function revisionCandidateAsset(revision?: WorkflowRevisionState | null): UploadedAsset | null {
  if (!revision) return null;
  if (revision.candidate_asset) return revision.candidate_asset;
  if (revision.candidate_assets?.length) return revision.candidate_assets[0];
  return revision.assets?.[0] ?? null;
}

export function revisionCandidateState(revision: WorkflowRevisionState): RevisionCandidateState {
  const asset = revisionCandidateAsset(revision);
  const record = revision as WorkflowRevisionState & Record<string, unknown>;
  const qualityIssues = arrayFromUnknown(asset?.quality_issues).length + arrayFromUnknown(record.quality_issues).length;
  const qualityWarnings = arrayFromUnknown(asset?.quality_warnings).length + arrayFromUnknown(record.quality_warnings).length;
  const libraryState = stringFromUnknown(record.library_state) || asset?.library_state || "";
  const libraryEntityId = stringFromUnknown(record.library_entity_id) || asset?.library_entity_id || null;
  const libraryAssetId = stringFromUnknown(record.library_asset_id) || asset?.library_asset_id || null;
  const libraryError = stringFromUnknown(record.library_error) || stringFromUnknown(record.library_ingest_error) || asset?.library_error || null;
  const sourceType = stringFromUnknown(record.source_type) || asset?.source_type || undefined;
  return {
    revisionId: revision.revision_id,
    generationStatus: revisionGenerationStatus(revision),
    acceptanceStatus: revisionAcceptanceStatus(revision),
    visibilityStatus: revisionVisibilityStatus(revision),
    targetEntityId: revision.target_entity_id ?? revision.revision?.target_entity_id ?? null,
    semanticType: revision.semantic_type ?? revision.revision?.semantic_type ?? null,
    asset,
    qualityStatus: stringFromUnknown(record.quality_status) || asset?.quality_status || "unchecked",
    issueCount: qualityIssues + qualityWarnings,
    reviewer: stringFromUnknown(record.reviewer) || asset?.reviewer || null,
    librarySuggested: booleanFromUnknown(record.library_suggested) || Boolean(libraryEntityId || libraryAssetId || isReadyLibraryIngestState(libraryState)),
    library_state: libraryState || undefined,
    library_entity_id: libraryEntityId,
    library_asset_id: libraryAssetId,
    library_error: libraryError,
    source_type: sourceType,
  };
}

export function revisionCandidateLibraryLabel(candidate: RevisionCandidateState) {
  const generationStatus = normalizedRevisionStatus(candidate.generationStatus);
  if (generationStatus === "waiting") return "等待中";
  if (generationStatus === "running" || generationStatus === "queued") return "生成中";
  const libraryState = normalizedRevisionStatus(candidate.library_state);
  if (libraryState === "failed") return "入库失败";
  if (isReadyLibraryIngestState(libraryState) || candidate.library_entity_id || candidate.library_asset_id) return "已入库";
  if (libraryState === "pending") return "入库中";
  if (libraryState === "skipped") return "未入库";
  return "";
}

export function revisionCandidateWorkflowUsageLabel(candidate: RevisionCandidateState) {
  const acceptanceStatus = normalizedRevisionStatus(candidate.acceptanceStatus);
  if (acceptanceStatus === "accepted") return "已用于当前工作流";
  if (["pending", "rejected", "superseded", "archived"].includes(acceptanceStatus)) return "未用于当前工作流";
  return "";
}

export function revisionCandidateTargetKey(revision: Pick<WorkflowRevisionState, "node_id" | "target_entity_id" | "semantic_type" | "revision">, fallbackNodeId = "") {
  const nodeId = revision.node_id || fallbackNodeId;
  const entityId = revision.target_entity_id ?? revision.revision?.target_entity_id ?? "";
  const semanticType = revision.semantic_type ?? revision.revision?.semantic_type ?? "";
  return [nodeId, entityId, semanticType].join("::");
}

function normalizedRevisionStatus(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim().toLowerCase() : "";
}

function readRecordValue(value: unknown, key: string) {
  return value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function booleanFromUnknown(value: unknown) {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") return ["true", "1", "yes"].includes(value.trim().toLowerCase());
  return false;
}

function isReadyLibraryIngestState(value?: string | null) {
  return ["created", "linked", "ready"].includes(normalizedRevisionStatus(value));
}

function arrayFromUnknown(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function revisionSortTime(revision: WorkflowRevisionState) {
  const value = revision.updated_at || revision.created_at;
  if (!value) return 0;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}
