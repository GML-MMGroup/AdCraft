import type {
  V2SlotAttachment,
  V2SlotOperationTarget,
  V2SlotVersionState,
} from "./v2SlotOperationTypes.ts";

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readMediaType(value: unknown): V2SlotAttachment["mediaType"] {
  const mediaType = readString(value);
  return mediaType === "image" || mediaType === "video" || mediaType === "audio" || mediaType === "text"
    ? mediaType
    : "unknown";
}

function readAttachmentSource(value: unknown): V2SlotAttachment["source"] {
  const source = readString(value);
  return source === "asset_library" || source === "workflow_asset" || source === "locator"
    ? source
    : "upload";
}

export function buildV2SlotTarget(input: {
  workflowId: string;
  nodeId: string;
  itemId: string;
  slotId: string;
  assetId?: string | null;
  versionId?: string | null;
}): V2SlotOperationTarget {
  return {
    workflowId: input.workflowId,
    nodeId: input.nodeId,
    itemId: input.itemId,
    slotId: input.slotId,
    assetId: input.assetId ?? null,
    versionId: input.versionId ?? null,
  };
}

export function formatV2AssetLocator(assetId: string, versionId: string): string {
  return `asset:${assetId}@${versionId}`;
}

export function normalizeV2SlotVersionState(value: unknown): V2SlotVersionState {
  const record = readRecord(value);
  const historyRaw = Array.isArray(record.history_versions) ? record.history_versions : [];
  const historyVersionIds = historyRaw
    .map((entry) => readString(readRecord(entry).version_id))
    .filter((entry): entry is string => Boolean(entry));
  const selectedVersionId = readString(record.selected_version_id);
  const workingVersionId = readString(record.working_version_id);
  const quality = readString(record.quality_status);

  return {
    selectedVersionId,
    selectedAssetId: readString(record.selected_asset_id),
    workingVersionId,
    workingAssetId: readString(record.working_asset_id),
    historyVersionIds,
    hasWorkingVersion: Boolean(workingVersionId),
    needsUseCurrentVersion: Boolean(workingVersionId && workingVersionId !== selectedVersionId),
    qualityStatus: quality === "passed" || quality === "warning" || quality === "failed" || quality === "unavailable" ? quality : "unchecked",
  };
}

export function normalizeV2SlotAttachments(values: unknown[]): V2SlotAttachment[] {
  return values.map((value) => {
    const record = readRecord(value);
    return {
      relationId: readString(record.relation_id) ?? readString(record.relationId),
      sourceAssetId: readString(record.source_asset_id) ?? readString(record.sourceAssetId) ?? readString(record.asset_id) ?? readString(record.assetId) ?? "",
      sourceVersionId: readString(record.source_version_id) ?? readString(record.sourceVersionId) ?? readString(record.version_id) ?? readString(record.versionId),
      displayName: readString(record.display_name) ?? readString(record.displayName) ?? readString(record.filename) ?? "Reference",
      mediaType: readMediaType(record.media_type ?? record.mediaType),
      previewUrl: readString(record.public_url) ?? readString(record.preview_url) ?? readString(record.previewUrl) ?? readString(record.url),
      semanticType: readString(record.semantic_type) ?? readString(record.semanticType) ?? "reference",
      source: readAttachmentSource(record.source),
    };
  }).filter((attachment) => attachment.sourceAssetId);
}
