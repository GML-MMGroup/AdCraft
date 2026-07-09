import { useCallback, useState } from "react";
import type { WorkflowSlotV2 } from "../../../../types-v2.ts";

export type SlotMicroEditAttachmentStatus = "draft" | "registering" | "registered" | "attached" | "failed";

export type SlotMicroEditAttachmentSource = "upload" | "asset_library" | "reference_asset";

export interface SlotMicroEditAttachment {
  id: string;
  source: SlotMicroEditAttachmentSource;
  preview_url?: string | null;
  source_asset_id?: string | null;
  relation_id?: string | null;
  library_entity_id?: string | null;
  library_asset_id?: string | null;
  filename?: string | null;
  semantic_type?: string | null;
  status: SlotMicroEditAttachmentStatus;
  error?: string;
}

export interface SlotMicroEditDraft {
  prompt: string;
  negative_prompt?: string;
  reference_asset_ids: string[];
  uploaded_asset_ids: string[];
  library_entity_ids: string[];
  attachments: SlotMicroEditAttachment[];
  dirty: boolean;
  isSubmitting: boolean;
  error?: string;
}

export interface SlotMicroEditState {
  openSlotId: string | null;
  draftsBySlotId: Record<string, SlotMicroEditDraft>;
}

type DraftReference =
  | { source: "reference_asset"; asset_id: string; relation_id?: string | null; preview_url?: string | null; status?: SlotMicroEditAttachmentStatus; semantic_type?: string | null }
  | { source: "uploaded_asset"; asset_id: string; relation_id?: string | null; preview_url?: string | null; status?: SlotMicroEditAttachmentStatus; semantic_type?: string | null }
  | { source: "library_entity"; entity_id: string; library_asset_id?: string | null; source_asset_id?: string | null; relation_id?: string | null; preview_url?: string | null; status?: SlotMicroEditAttachmentStatus; semantic_type?: string | null };

export function createInitialSlotMicroEditState(): SlotMicroEditState {
  return { openSlotId: null, draftsBySlotId: {} };
}

export function openSlotMicroEdit(state: SlotMicroEditState, slot: WorkflowSlotV2): SlotMicroEditState {
  return {
    ...state,
    openSlotId: slot.slot_id,
    draftsBySlotId: {
      ...state.draftsBySlotId,
      [slot.slot_id]: state.draftsBySlotId[slot.slot_id] ?? draftFromSlot(slot),
    },
  };
}

export function closeSlotMicroEdit(state: SlotMicroEditState): SlotMicroEditState {
  return { ...state, openSlotId: null };
}

export function updateSlotMicroEditPrompt(state: SlotMicroEditState, slotId: string, prompt: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return {
    ...state,
    draftsBySlotId: {
      ...state.draftsBySlotId,
      [slotId]: { ...draft, prompt, dirty: true, error: undefined },
    },
  };
}

export function updateSlotMicroEditNegativePrompt(state: SlotMicroEditState, slotId: string, negativePrompt: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return {
    ...state,
    draftsBySlotId: {
      ...state.draftsBySlotId,
      [slotId]: { ...draft, negative_prompt: negativePrompt, dirty: true, error: undefined },
    },
  };
}

export function addSlotDraftReference(state: SlotMicroEditState, slotId: string, reference: DraftReference): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  const nextDraft = syncDraftReferenceArrays({
    ...draft,
    reference_asset_ids: reference.source === "reference_asset" ? addUnique(draft.reference_asset_ids, reference.asset_id) : draft.reference_asset_ids,
    uploaded_asset_ids: reference.source === "uploaded_asset" ? addUnique(draft.uploaded_asset_ids, reference.asset_id) : draft.uploaded_asset_ids,
    library_entity_ids: reference.source === "library_entity" ? addUnique(draft.library_entity_ids, reference.entity_id) : draft.library_entity_ids,
    attachments: upsertAttachment(draft.attachments, attachmentFromDraftReference(reference)),
    dirty: true,
    error: undefined,
  });
  return updateDraft(state, slotId, nextDraft);
}

export function addSlotDraftAttachment(state: SlotMicroEditState, slotId: string, attachment: SlotMicroEditAttachment): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return updateDraft(
    state,
    slotId,
    syncDraftReferenceArrays({
      ...draft,
      attachments: upsertAttachment(draft.attachments, normalizeAttachment(attachment)),
      dirty: true,
      error: undefined,
    }),
  );
}

export function updateSlotDraftAttachment(
  state: SlotMicroEditState,
  slotId: string,
  attachmentId: string,
  patch: Partial<SlotMicroEditAttachment>,
): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return updateDraft(
    state,
    slotId,
    syncDraftReferenceArrays({
      ...draft,
      attachments: draft.attachments.map((attachment) =>
        attachment.id === attachmentId ? normalizeAttachment({ ...attachment, ...patch }) : attachment,
      ),
      dirty: true,
      error: patch.status === "failed" ? patch.error : undefined,
    }),
  );
}

export function removeSlotDraftReference(state: SlotMicroEditState, slotId: string, reference: DraftReference): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  const assetId = reference.source === "reference_asset" || reference.source === "uploaded_asset" ? reference.asset_id : "";
  return updateDraft(state, slotId, syncDraftReferenceArrays({
    ...draft,
    reference_asset_ids: assetId ? withoutValue(draft.reference_asset_ids, assetId) : draft.reference_asset_ids,
    uploaded_asset_ids: reference.source === "uploaded_asset" ? withoutValue(draft.uploaded_asset_ids, reference.asset_id) : draft.uploaded_asset_ids,
    library_entity_ids: reference.source === "library_entity" ? withoutValue(draft.library_entity_ids, reference.entity_id) : draft.library_entity_ids,
    attachments: draft.attachments.filter((attachment) => !attachmentMatchesReference(attachment, reference)),
    dirty: true,
    error: undefined,
  }));
}

export function setSlotDraftSubmitting(state: SlotMicroEditState, slotId: string, isSubmitting: boolean, error?: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return updateDraft(state, slotId, { ...draft, isSubmitting, error });
}

export function markSlotDraftClean(state: SlotMicroEditState, slotId: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return updateDraft(state, slotId, { ...draft, dirty: false, isSubmitting: false, error: undefined });
}

export function slotDraftSubmitPayload(draft: SlotMicroEditDraft) {
  return {
    slot_prompt: scrubInlineMedia(draft.prompt),
    negative_prompt: scrubInlineMedia(draft.negative_prompt ?? ""),
    reference_asset_ids: uniqueStrings([
      ...draft.reference_asset_ids,
      ...draft.uploaded_asset_ids,
      ...draft.attachments.map((attachment) => attachment.source_asset_id ?? ""),
    ]),
    library_entity_ids: [],
  };
}

export function useSlotMicroEdit(initialState: SlotMicroEditState = createInitialSlotMicroEditState()) {
  const [state, setState] = useState<SlotMicroEditState>(initialState);
  const openSlot = useCallback((slot: WorkflowSlotV2) => setState((current) => openSlotMicroEdit(current, slot)), []);
  const closeSlot = useCallback(() => setState(closeSlotMicroEdit), []);
  const updatePrompt = useCallback((slotId: string, prompt: string) => setState((current) => updateSlotMicroEditPrompt(current, slotId, prompt)), []);
  const updateNegativePrompt = useCallback((slotId: string, negativePrompt: string) => setState((current) => updateSlotMicroEditNegativePrompt(current, slotId, negativePrompt)), []);
  const addReference = useCallback((slotId: string, reference: DraftReference) => setState((current) => addSlotDraftReference(current, slotId, reference)), []);
  const removeReference = useCallback((slotId: string, reference: DraftReference) => setState((current) => removeSlotDraftReference(current, slotId, reference)), []);
  const addAttachment = useCallback((slotId: string, attachment: SlotMicroEditAttachment) => setState((current) => addSlotDraftAttachment(current, slotId, attachment)), []);
  const updateAttachment = useCallback((slotId: string, attachmentId: string, patch: Partial<SlotMicroEditAttachment>) => setState((current) => updateSlotDraftAttachment(current, slotId, attachmentId, patch)), []);
  const setSubmitting = useCallback((slotId: string, isSubmitting: boolean, error?: string) => setState((current) => setSlotDraftSubmitting(current, slotId, isSubmitting, error)), []);
  const markClean = useCallback((slotId: string) => setState((current) => markSlotDraftClean(current, slotId)), []);
  return { state, setState, openSlot, closeSlot, updatePrompt, updateNegativePrompt, addReference, removeReference, addAttachment, updateAttachment, setSubmitting, markClean };
}

function draftFromSlot(slot: WorkflowSlotV2): SlotMicroEditDraft {
  return {
    prompt: slot.slot_prompt ?? "",
    negative_prompt: slot.negative_prompt ?? "",
    reference_asset_ids: [...(slot.explicit_reference_ids ?? [])],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: (slot.explicit_reference_ids ?? []).map((assetId) => ({
      id: `reference:${assetId}`,
      source: "reference_asset",
      source_asset_id: assetId,
      status: "attached",
    })),
    dirty: false,
    isSubmitting: false,
  };
}

function ensureDraft(state: SlotMicroEditState, slotId: string): SlotMicroEditDraft {
  return state.draftsBySlotId[slotId] ?? {
    prompt: "",
    negative_prompt: "",
    reference_asset_ids: [],
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: [],
    dirty: false,
    isSubmitting: false,
  };
}

function updateDraft(state: SlotMicroEditState, slotId: string, draft: SlotMicroEditDraft): SlotMicroEditState {
  return { ...state, draftsBySlotId: { ...state.draftsBySlotId, [slotId]: draft } };
}

function addUnique(values: string[], value: string) {
  return value && !values.includes(value) ? [...values, value] : values;
}

function withoutValue(values: string[], value: string) {
  return values.filter((item) => item !== value);
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function normalizeAttachment(attachment: SlotMicroEditAttachment): SlotMicroEditAttachment {
  const sourceAssetId = cleanString(attachment.source_asset_id);
  const libraryEntityId = cleanString(attachment.library_entity_id);
  return {
    ...attachment,
    id: cleanString(attachment.id) || attachmentIdentity({ ...attachment, source_asset_id: sourceAssetId, library_entity_id: libraryEntityId }),
    preview_url: cleanString(attachment.preview_url),
    source_asset_id: sourceAssetId,
    relation_id: cleanString(attachment.relation_id),
    library_entity_id: libraryEntityId,
    library_asset_id: cleanString(attachment.library_asset_id),
    filename: cleanString(attachment.filename),
    semantic_type: cleanString(attachment.semantic_type),
    status: attachment.status,
    error: cleanString(attachment.error),
  };
}

function attachmentFromDraftReference(reference: DraftReference): SlotMicroEditAttachment {
  if (reference.source === "library_entity") {
    return normalizeAttachment({
      id: `library:${reference.entity_id}:${reference.library_asset_id ?? ""}`,
      source: "asset_library",
      library_entity_id: reference.entity_id,
      library_asset_id: reference.library_asset_id,
      source_asset_id: reference.source_asset_id,
      relation_id: reference.relation_id,
      preview_url: reference.preview_url,
      semantic_type: reference.semantic_type,
      status: reference.status ?? (reference.relation_id ? "attached" : reference.source_asset_id ? "registered" : "draft"),
    });
  }
  return normalizeAttachment({
    id: `${reference.source}:${reference.asset_id}`,
    source: reference.source === "uploaded_asset" ? "upload" : "reference_asset",
    source_asset_id: reference.asset_id,
    relation_id: reference.relation_id,
    preview_url: reference.preview_url,
    semantic_type: reference.semantic_type,
    status: reference.status ?? (reference.relation_id ? "attached" : "registered"),
  });
}

function syncDraftReferenceArrays(draft: SlotMicroEditDraft): SlotMicroEditDraft {
  const attachmentSourceAssetIds = draft.attachments.map((attachment) => attachment.source_asset_id ?? "").filter(Boolean);
  const libraryEntityIds = draft.attachments
    .filter((attachment) => attachment.source === "asset_library" && attachment.library_entity_id && attachment.status !== "failed")
    .map((attachment) => attachment.library_entity_id ?? "");
  return {
    ...draft,
    reference_asset_ids: uniqueStrings([...draft.reference_asset_ids, ...attachmentSourceAssetIds]),
    uploaded_asset_ids: uniqueStrings(draft.uploaded_asset_ids),
    library_entity_ids: uniqueStrings([...draft.library_entity_ids, ...libraryEntityIds]),
  };
}

function upsertAttachment(attachments: SlotMicroEditAttachment[], attachment: SlotMicroEditAttachment) {
  const next = attachments.filter((current) => attachmentIdentity(current) !== attachmentIdentity(attachment));
  next.push(attachment);
  return next;
}

function attachmentMatchesReference(attachment: SlotMicroEditAttachment, reference: DraftReference) {
  if (reference.source === "library_entity") return attachment.source === "asset_library" && attachment.library_entity_id === reference.entity_id;
  const assetId = reference.source === "reference_asset" || reference.source === "uploaded_asset" ? reference.asset_id : "";
  return attachment.source_asset_id === assetId || attachment.id === `${reference.source}:${assetId}`;
}

function attachmentIdentity(attachment: Pick<SlotMicroEditAttachment, "id" | "source" | "source_asset_id" | "library_entity_id" | "library_asset_id" | "preview_url">) {
  if (attachment.source_asset_id) return `asset:${attachment.source_asset_id}`;
  if (attachment.library_entity_id) return `library:${attachment.library_entity_id}:${attachment.library_asset_id ?? ""}`;
  if (attachment.preview_url) return `preview:${attachment.preview_url}`;
  return attachment.id;
}

function cleanString(value?: string | null) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function scrubInlineMedia(value: string) {
  return value.replace(/data:(?:image|video|audio)\/[a-z0-9.+-]+;base64,[^\s"')]+/gi, "[inline media omitted]");
}
