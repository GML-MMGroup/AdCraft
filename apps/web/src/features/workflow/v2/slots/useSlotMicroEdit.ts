import { useCallback, useState } from "react";
import { effectiveSlotPrompt, type WorkflowSlotV2 } from "../../../../types-v2.ts";

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
  promptDirty: boolean;
  referenceDirty: boolean;
  base_prompt: string;
  base_negative_prompt: string;
  isSubmitting: boolean;
  error?: string;
  serverBaseline?: SlotMicroEditServerBaseline;
  pendingRebase?: SlotMicroEditServerBaseline;
}

export interface SlotMicroEditServerBaseline {
  prompt: string;
  slot_prompt?: string;
  system_suggested_prompt?: string;
  user_prompt?: string;
  negative_prompt: string;
  reference_asset_ids: string[];
  attachments: SlotMicroEditAttachment[];
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

/** Reconciles one existing draft with a fresh server slot without creating drafts. */
export function rebaseSlotMicroEditDraft(state: SlotMicroEditState, slot: WorkflowSlotV2): SlotMicroEditState {
  const draft = state.draftsBySlotId[slot.slot_id];
  if (!draft) return state;

  const serverBaseline = serverBaselineFromSlot(slot);
  if (draft.isSubmitting) {
    const nextDraft = sameServerBaseline(draft.pendingRebase, serverBaseline) ? draft : { ...draft, pendingRebase: serverBaseline };
    return sameDraft(draft, nextDraft) ? state : updateDraft(state, slot.slot_id, nextDraft);
  }
  const nextDraft = draft.promptDirty
    ? { ...draft, serverBaseline }
    : {
      ...draft,
      prompt: serverBaseline.prompt,
      negative_prompt: serverBaseline.negative_prompt,
      base_prompt: serverBaseline.prompt,
      base_negative_prompt: serverBaseline.negative_prompt,
      promptDirty: false,
      reference_asset_ids: draft.referenceDirty ? draft.reference_asset_ids : serverBaseline.reference_asset_ids,
      attachments: draft.referenceDirty ? draft.attachments : serverBaseline.attachments,
      dirty: draft.referenceDirty,
      serverBaseline,
    };
  if (sameDraft(draft, nextDraft)) return state;
  return {
    ...state,
    draftsBySlotId: { ...state.draftsBySlotId, [slot.slot_id]: nextDraft },
  };
}

/** Reconciles existing drafts with a fresh slot collection and removes archived slots. */
export function rebaseSlotMicroEditState(
  state: SlotMicroEditState,
  slots: WorkflowSlotV2[],
  options: { authoritative?: boolean; archivedSlotIds?: string[]; removedSlotIds?: string[] } = {},
): SlotMicroEditState {
  const slotsById = new Map(slots.map((slot) => [slot.slot_id, slot]));
  const removedSlotIds = new Set([...(options.archivedSlotIds ?? []), ...(options.removedSlotIds ?? [])]);
  let nextState = state;

  for (const slotId of Object.keys(state.draftsBySlotId)) {
    const slot = slotsById.get(slotId);
    if (slot && !removedSlotIds.has(slotId)) {
      nextState = rebaseSlotMicroEditDraft(nextState, slot);
      continue;
    }
    if (!removedSlotIds.has(slotId) && !options.authoritative) continue;
    const { [slotId]: _removed, ...remainingDrafts } = nextState.draftsBySlotId;
    nextState = {
      ...nextState,
      openSlotId: nextState.openSlotId === slotId ? null : nextState.openSlotId,
      draftsBySlotId: remainingDrafts,
    };
  }

  if (nextState.openSlotId && (removedSlotIds.has(nextState.openSlotId) || (options.authoritative && !slotsById.has(nextState.openSlotId)))) {
    return { ...nextState, openSlotId: null };
  }
  return nextState;
}

export function updateSlotMicroEditPrompt(state: SlotMicroEditState, slotId: string, prompt: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  const promptDirty = prompt !== draft.base_prompt;
  return {
    ...state,
    draftsBySlotId: {
      ...state.draftsBySlotId,
      [slotId]: { ...draft, prompt, promptDirty, dirty: promptDirty || draft.referenceDirty, error: undefined },
    },
  };
}

export function updateSlotMicroEditNegativePrompt(state: SlotMicroEditState, slotId: string, negativePrompt: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  const promptDirty = draft.prompt !== draft.base_prompt || negativePrompt !== draft.base_negative_prompt;
  return {
    ...state,
    draftsBySlotId: {
      ...state.draftsBySlotId,
      [slotId]: { ...draft, negative_prompt: negativePrompt, promptDirty, dirty: promptDirty || draft.referenceDirty, error: undefined },
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
    referenceDirty: true,
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
      referenceDirty: true,
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
      referenceDirty: true,
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
    referenceDirty: true,
    dirty: true,
    error: undefined,
  }));
}

export function setSlotDraftSubmitting(state: SlotMicroEditState, slotId: string, isSubmitting: boolean, error?: string): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  if (!isSubmitting && (draft.pendingRebase || error)) return completeSlotDraftSubmission(state, slotId, { error });
  return updateDraft(state, slotId, { ...draft, isSubmitting, error });
}

export function completeSlotDraftSubmission(
  state: SlotMicroEditState,
  slotId: string,
  options: { slot?: WorkflowSlotV2; promptPersisted?: boolean; error?: string } = {},
): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  const incoming = draft.pendingRebase ?? (options.slot ? serverBaselineFromSlot(options.slot) : draft.serverBaseline);
  if (!incoming) return updateDraft(state, slotId, { ...draft, isSubmitting: false, error: options.error });
  const promptPersisted = Boolean(options.promptPersisted);
  const serverBaseline = promptPersisted
    ? { ...incoming, prompt: draft.prompt, user_prompt: draft.prompt, negative_prompt: draft.negative_prompt ?? "" }
    : incoming;
  const keepPrompt = Boolean(options.error) || draft.promptDirty;
  const prompt = keepPrompt ? draft.prompt : serverBaseline.prompt;
  const negative_prompt = keepPrompt ? draft.negative_prompt : serverBaseline.negative_prompt;
  const base_prompt = promptPersisted ? draft.prompt : keepPrompt ? draft.base_prompt : serverBaseline.prompt;
  const base_negative_prompt = promptPersisted ? (draft.negative_prompt ?? "") : keepPrompt ? draft.base_negative_prompt : serverBaseline.negative_prompt;
  const nextDraft: SlotMicroEditDraft = {
    ...draft,
    prompt,
    negative_prompt,
    base_prompt,
    base_negative_prompt,
    promptDirty: options.error ? draft.promptDirty : promptPersisted ? false : prompt !== base_prompt || (negative_prompt ?? "") !== base_negative_prompt,
    referenceDirty: options.error ? draft.referenceDirty : false,
    dirty: options.error ? draft.dirty : false,
    isSubmitting: false,
    error: options.error,
    serverBaseline,
    pendingRebase: undefined,
  };
  nextDraft.dirty = nextDraft.promptDirty || nextDraft.referenceDirty;
  return sameDraft(draft, nextDraft) ? state : updateDraft(state, slotId, nextDraft);
}

export function markSlotDraftClean(state: SlotMicroEditState, slotId: string, slot?: WorkflowSlotV2, promptPersisted = true): SlotMicroEditState {
  return completeSlotDraftSubmission(state, slotId, { slot, promptPersisted });
}

export function slotDraftHasPromptChanges(draft: Pick<SlotMicroEditDraft, "promptDirty">) {
  return draft.promptDirty;
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
  const markClean = useCallback((slotId: string, slot?: WorkflowSlotV2, promptPersisted = true) => setState((current) => markSlotDraftClean(current, slotId, slot, promptPersisted)), []);
  const rebaseSlots = useCallback((slots: WorkflowSlotV2[], options?: { authoritative?: boolean; archivedSlotIds?: string[]; removedSlotIds?: string[] }) => setState((current) => rebaseSlotMicroEditState(current, slots, options)), []);
  return { state, setState, openSlot, closeSlot, updatePrompt, updateNegativePrompt, addReference, removeReference, addAttachment, updateAttachment, setSubmitting, markClean, rebaseSlots };
}

function draftFromSlot(slot: WorkflowSlotV2): SlotMicroEditDraft {
  const serverBaseline = serverBaselineFromSlot(slot);
  return {
    prompt: serverBaseline.prompt,
    negative_prompt: serverBaseline.negative_prompt,
    reference_asset_ids: serverBaseline.reference_asset_ids,
    uploaded_asset_ids: [],
    library_entity_ids: [],
    attachments: serverBaseline.attachments,
    dirty: false,
    promptDirty: false,
    referenceDirty: false,
    base_prompt: serverBaseline.prompt,
    base_negative_prompt: serverBaseline.negative_prompt,
    isSubmitting: false,
    serverBaseline,
  };
}

function serverBaselineFromSlot(slot: WorkflowSlotV2): SlotMicroEditServerBaseline {
  const reference_asset_ids = [...(slot.explicit_reference_ids ?? [])];
  return {
    prompt: effectiveSlotPrompt(slot),
    slot_prompt: slot.slot_prompt,
    system_suggested_prompt: slot.system_suggested_prompt,
    user_prompt: slot.user_prompt,
    negative_prompt: slot.negative_prompt ?? "",
    reference_asset_ids,
    attachments: reference_asset_ids.map((assetId) => ({
      id: `reference:${assetId}`,
      source: "reference_asset",
      source_asset_id: assetId,
      status: "attached",
    })),
  };
}

function sameDraft(left: SlotMicroEditDraft, right: SlotMicroEditDraft) {
  return left === right || (
    left.prompt === right.prompt &&
    left.negative_prompt === right.negative_prompt &&
    left.base_prompt === right.base_prompt &&
    left.base_negative_prompt === right.base_negative_prompt &&
    left.dirty === right.dirty &&
    left.promptDirty === right.promptDirty &&
    left.referenceDirty === right.referenceDirty &&
    left.isSubmitting === right.isSubmitting &&
    left.error === right.error &&
    sameStrings(left.reference_asset_ids, right.reference_asset_ids) &&
    sameStrings(left.uploaded_asset_ids, right.uploaded_asset_ids) &&
    sameStrings(left.library_entity_ids, right.library_entity_ids) &&
    sameAttachments(left.attachments, right.attachments) &&
    sameServerBaseline(left.serverBaseline, right.serverBaseline) &&
    sameServerBaseline(left.pendingRebase, right.pendingRebase)
  );
}

function sameServerBaseline(left: SlotMicroEditServerBaseline | undefined, right: SlotMicroEditServerBaseline | undefined) {
  return left === right || Boolean(left && right &&
    left.prompt === right.prompt &&
    left.slot_prompt === right.slot_prompt &&
    left.system_suggested_prompt === right.system_suggested_prompt &&
    left.user_prompt === right.user_prompt &&
    left.negative_prompt === right.negative_prompt &&
    sameStrings(left.reference_asset_ids, right.reference_asset_ids) &&
    sameAttachments(left.attachments, right.attachments));
}

function sameStrings(left: string[], right: string[]) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function sameAttachments(left: SlotMicroEditAttachment[], right: SlotMicroEditAttachment[]) {
  return left.length === right.length && left.every((attachment, index) => {
    const other = right[index];
    return attachment.id === other.id && attachment.source === other.source && attachment.preview_url === other.preview_url &&
      attachment.source_asset_id === other.source_asset_id && attachment.relation_id === other.relation_id &&
      attachment.library_entity_id === other.library_entity_id && attachment.library_asset_id === other.library_asset_id &&
      attachment.filename === other.filename && attachment.semantic_type === other.semantic_type && attachment.status === other.status && attachment.error === other.error;
  });
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
    promptDirty: false,
    referenceDirty: false,
    base_prompt: "",
    base_negative_prompt: "",
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
