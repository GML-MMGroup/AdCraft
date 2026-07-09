import type {
  V2AddSlotReferenceRequest,
  V2ReferenceAttachRequest,
  V2RegisterLibraryReferenceRequest,
  V2RegisterReferenceAssetRequest,
  V2SlotCandidateRegenerateRequest,
  WorkflowSlotV2,
} from "../types-v2.ts";
import type { SlotMicroEditDraft } from "../features/workflow/v2/slots/useSlotMicroEdit.ts";

export function createV2SlotActionModel(workflowId: string, itemId: string, slotId: string, versionId?: string) {
  return {
    updateItemPrompt: { workflowId, itemId },
    updateSlotPrompt: { workflowId, slotId },
    regenerateSlot: { workflowId, slotId },
    selectVersion: versionId ? { workflowId, slotId, versionId } : null,
  };
}

export function buildSlotCandidateRegenerateRequest(
  draft: Pick<SlotMicroEditDraft, "prompt" | "negative_prompt" | "reference_asset_ids" | "uploaded_asset_ids" | "library_entity_ids">,
  slot: WorkflowSlotV2,
  sourceAction: V2SlotCandidateRegenerateRequest["source_action"] = "slot_micro_prompt_send",
): V2SlotCandidateRegenerateRequest {
  return {
    slot_prompt: stripInlineBase64(draft.prompt || slot.slot_prompt || ""),
    negative_prompt: stripInlineBase64(draft.negative_prompt ?? slot.negative_prompt ?? ""),
    reference_asset_ids: uniqueStrings([...(draft.reference_asset_ids ?? []), ...(draft.uploaded_asset_ids ?? [])]),
    library_entity_ids: uniqueStrings(draft.library_entity_ids ?? []),
    source_action: sourceAction,
  };
}

export function buildSlotReferenceAttachRequest(slotId: string, sourceAssetId: string, semanticType?: string | null): V2ReferenceAttachRequest {
  return {
    target_type: "slot",
    target_id: requiredString(slotId, "slot_id"),
    source_asset_id: canonicalSourceAssetId(sourceAssetId),
    reference_kind: "explicit",
    ...(semanticType ? { metadata: { semantic_type: semanticType } } : {}),
  };
}

export function buildSlotLibraryReferenceRegistration(
  slotId: string,
  libraryEntityId: string,
  libraryAssetId?: string | null,
  semanticType?: string | null,
): V2RegisterLibraryReferenceRequest {
  return {
    library_entity_id: requiredString(libraryEntityId, "library_entity_id"),
    library_asset_id: libraryAssetId?.trim() || null,
    target: { target_type: "slot", slot_id: requiredString(slotId, "slot_id") },
    ...(semanticType ? { semantic_type: semanticType } : {}),
    use_as_prompt: true,
  };
}

export function buildSlotReferenceAssetRegistration(
  slotId: string,
  source: V2RegisterReferenceAssetRequest["source"],
  semanticType?: string | null,
): V2RegisterReferenceAssetRequest {
  const canonicalSource = canonicalRegisterReferenceSource(source, semanticType);
  return {
    source: canonicalSource,
    target: { target_type: "slot", slot_id: requiredString(slotId, "slot_id") },
    ...(semanticType ? { semantic_type: semanticType } : {}),
    use_as_prompt: true,
  };
}

export function slotReferenceUploadFormData(files: File[], role: string, displayName?: string) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files[]", file));
  formData.append("reference_role", role);
  if (displayName?.trim()) formData.append("display_name", displayName.trim());
  return formData;
}

export function buildV2RegisterReferenceRequest(
  asset: { asset_id: string; version_id?: string | null },
  slotId: string,
  referenceRole: string,
): V2RegisterReferenceAssetRequest {
  return {
    source: {
      kind: "existing_v2_asset_version",
      asset_id: requiredString(asset.asset_id, "asset_id"),
      version_id: asset.version_id ?? undefined,
    },
    target: {
      target_type: "slot",
      slot_id: requiredString(slotId, "slot_id"),
    },
    reference_role: referenceRole,
    use_as_prompt: true,
  };
}

export function buildAddSlotReferenceRequest(
  asset: { asset_id: string; version_id: string },
  referenceRole: string,
): V2AddSlotReferenceRequest {
  return {
    asset_id: requiredString(asset.asset_id, "asset_id"),
    version_id: requiredString(asset.version_id, "version_id"),
    reference_role: referenceRole,
  };
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter((value) => typeof value === "string" && Boolean(value.trim())).map((value) => value.trim())));
}

function stripInlineBase64(value: string) {
  return value.replace(/data:(?:image|video|audio)\/[a-z0-9.+-]+;base64,[^\s"')]+/gi, "[inline media omitted]");
}

function canonicalRegisterReferenceSource(
  source: V2RegisterReferenceAssetRequest["source"],
  semanticType?: string | null,
): V2RegisterReferenceAssetRequest["source"] {
  if (source.kind) return source;
  const assetId = source.asset_id ?? source.source_asset_id ?? source.upload_asset_id;
  if (assetId) {
    return {
      kind: "existing_v2_asset_version",
      asset_id: assetId,
      version_id: source.version_id ?? undefined,
      display_name: source.display_name ?? undefined,
      media_type: source.media_type ?? undefined,
      semantic_type: semanticType ?? source.semantic_type ?? undefined,
    };
  }
  return {
    kind: "data_assets_file",
    file_path: source.local_path ?? source.public_url ?? undefined,
    media_type: source.media_type ?? undefined,
    semantic_type: semanticType ?? source.semantic_type ?? undefined,
    display_name: source.display_name ?? undefined,
  };
}

function requiredString(value: string, fieldName: string) {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`${fieldName} is required`);
  return trimmed;
}

function canonicalSourceAssetId(value: string) {
  const assetId = requiredString(value, "source_asset_id");
  if (/^data:(?:image|video|audio)\//i.test(assetId)) throw new Error("source_asset_id must be a V2 canonical asset id, not inline media");
  if (/^https?:\/\//i.test(assetId) || assetId.startsWith("/")) throw new Error("source_asset_id must be a V2 canonical asset id, not a URL");
  if (/^(lib|library)[_-]/i.test(assetId)) throw new Error("source_asset_id must be a V2 canonical asset id, not an Asset Library id");
  return assetId;
}
