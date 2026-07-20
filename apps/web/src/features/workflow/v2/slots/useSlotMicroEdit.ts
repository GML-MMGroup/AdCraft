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
  submissionDepth?: number;
  promptRevision?: number;
  referenceRevision?: number;
  error?: string;
  serverBaseline?: SlotMicroEditServerBaseline;
  pendingRebase?: SlotMicroEditServerBaseline;
  submissionBaseline?: SlotMicroEditSubmissionBaseline;
}

interface SlotMicroEditSubmissionBaseline {
  prompt: string;
  promptRevision: number;
  referenceRevision: number;
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
      [slotId]: {
        ...draft,
        prompt,
        promptRevision: prompt === draft.prompt ? draft.promptRevision : revisionOf(draft.promptRevision) + 1,
        promptDirty,
        dirty: promptDirty || draft.referenceDirty,
        error: undefined,
      },
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
      [slotId]: {
        ...draft,
        negative_prompt: negativePrompt,
        promptRevision: negativePrompt === draft.negative_prompt ? draft.promptRevision : revisionOf(draft.promptRevision) + 1,
        promptDirty,
        dirty: promptDirty || draft.referenceDirty,
        error: undefined,
      },
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
    referenceRevision: revisionOf(draft.referenceRevision) + 1,
    referenceDirty: true,
    dirty: true,
    error: undefined,
  });
  return updateDraft(state, slotId, nextDraft);
}

export function addSlotDraftAttachment(
  state: SlotMicroEditState,
  slotId: string,
  attachment: SlotMicroEditAttachment,
  trackRevision = true,
): SlotMicroEditState {
  const draft = ensureDraft(state, slotId);
  return updateDraft(
    state,
    slotId,
    syncDraftReferenceArrays({
      ...draft,
      attachments: upsertAttachment(draft.attachments, normalizeAttachment(attachment)),
      referenceRevision: trackRevision ? revisionOf(draft.referenceRevision) + 1 : draft.referenceRevision,
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
  const draft = state.draftsBySlotId[slotId];
  if (!draft) return state;
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
  const nextDraft = syncDraftReferenceArrays({
    ...draft,
    reference_asset_ids: assetId ? withoutValue(draft.reference_asset_ids, assetId) : draft.reference_asset_ids,
    uploaded_asset_ids: reference.source === "uploaded_asset" ? withoutValue(draft.uploaded_asset_ids, reference.asset_id) : draft.uploaded_asset_ids,
    library_entity_ids: reference.source === "library_entity" ? withoutValue(draft.library_entity_ids, reference.entity_id) : draft.library_entity_ids,
    attachments: draft.attachments.filter((attachment) => !attachmentMatchesReference(attachment, reference)),
    error: undefined,
  });
  const changed = !sameStrings(draft.reference_asset_ids, nextDraft.reference_asset_ids) ||
    !sameStrings(draft.uploaded_asset_ids, nextDraft.uploaded_asset_ids) ||
    !sameStrings(draft.library_entity_ids, nextDraft.library_entity_ids) ||
    !sameAttachments(draft.attachments, nextDraft.attachments);
  if (!changed) return state;
  const referenceDirty = draft.serverBaseline ? draftReferencesDifferFromBaseline(nextDraft, draft.serverBaseline) : true;
  return updateDraft(state, slotId, {
    ...nextDraft,
    referenceRevision: revisionOf(draft.referenceRevision) + 1,
    referenceDirty,
    dirty: draft.promptDirty || referenceDirty,
  });
}

export function setSlotDraftSubmitting(state: SlotMicroEditState, slotId: string, isSubmitting: boolean, error?: string): SlotMicroEditState {
  if (isSubmitting) {
    const draft = ensureDraft(state, slotId);
    return updateDraft(state, slotId, {
      ...draft,
      isSubmitting: true,
      submissionDepth: submissionDepthOf(draft) + 1,
      error,
      submissionBaseline: draft.submissionBaseline ?? {
        prompt: draft.prompt,
        promptRevision: revisionOf(draft.promptRevision),
        referenceRevision: revisionOf(draft.referenceRevision),
      },
    });
  }

  const draft = state.draftsBySlotId[slotId];
  if (!draft) return state;
  const settledState = draft.pendingRebase || error
    ? completeSlotDraftSubmission(state, slotId, { error })
    : state;
  const settledDraft = settledState.draftsBySlotId[slotId];
  if (!settledDraft) return settledState;
  const submissionDepth = Math.max(0, submissionDepthOf(settledDraft) - 1);
  return updateDraft(settledState, slotId, {
    ...settledDraft,
    isSubmitting: submissionDepth > 0,
    submissionDepth,
    error: error ?? settledDraft.error,
    submissionBaseline: submissionDepth > 0 ? settledDraft.submissionBaseline : undefined,
  });
}

export function completeSlotDraftSubmission(
  state: SlotMicroEditState,
  slotId: string,
  options: { slot?: WorkflowSlotV2; promptPersisted?: boolean; referenceBaselineAuthoritative?: boolean; error?: string } = {},
): SlotMicroEditState {
  const draft = state.draftsBySlotId[slotId];
  if (!draft) return state;
  const submissionDepth = submissionDepthOf(draft);
  const isSubmitting = submissionDepth > 0;
  const submissionBaseline = draft.submissionBaseline;
  const promptChangedAfterSubmit = Boolean(submissionBaseline && revisionOf(draft.promptRevision) !== submissionBaseline.promptRevision);
  const referencesChangedAfterSubmit = Boolean(submissionBaseline && revisionOf(draft.referenceRevision) !== submissionBaseline.referenceRevision);
  const promptPersisted = Boolean(options.promptPersisted);
  const returnedBaseline = options.slot ? serverBaselineFromSlot(options.slot) : undefined;
  const incoming = options.error
    ? draft.pendingRebase ?? returnedBaseline ?? draft.serverBaseline
    : returnedBaseline
      ? mergeSuccessfulSubmissionBaseline(
        returnedBaseline,
        draft.pendingRebase,
        promptPersisted ? submissionBaseline?.prompt ?? draft.prompt : undefined,
        options.referenceBaselineAuthoritative,
      )
      : draft.pendingRebase;
  if (!incoming) {
    return updateDraft(state, slotId, {
      ...draft,
      isSubmitting,
      submissionDepth,
      error: options.error,
      submissionBaseline: isSubmitting ? submissionBaseline : undefined,
    });
  }
  const serverBaseline = incoming;
  const failed = Boolean(options.error);
  const keepPrompt = failed || promptChangedAfterSubmit || (!promptPersisted && draft.promptDirty);
  const prompt = keepPrompt ? draft.prompt : serverBaseline.prompt;
  const negative_prompt = keepPrompt ? draft.negative_prompt : serverBaseline.negative_prompt;
  const base_prompt = serverBaseline.prompt;
  const base_negative_prompt = serverBaseline.negative_prompt;
  const preserveReferences = (failed && draft.referenceDirty) || referencesChangedAfterSubmit;
  const reference_asset_ids = preserveReferences ? draft.reference_asset_ids : serverBaseline.reference_asset_ids;
  const uploaded_asset_ids = preserveReferences ? draft.uploaded_asset_ids : [];
  const library_entity_ids = preserveReferences ? draft.library_entity_ids : [];
  const attachments = preserveReferences ? draft.attachments : serverBaseline.attachments;
  const referenceDirty = preserveReferences ? draftReferencesDifferFromBaseline(draft, serverBaseline) : false;
  const promptDirty = keepPrompt
    ? prompt !== base_prompt || (negative_prompt ?? "") !== base_negative_prompt
    : false;
  const nextDraft: SlotMicroEditDraft = {
    ...draft,
    prompt,
    negative_prompt,
    reference_asset_ids,
    uploaded_asset_ids,
    library_entity_ids,
    attachments,
    base_prompt,
    base_negative_prompt,
    promptDirty,
    referenceDirty,
    dirty: promptDirty || referenceDirty,
    isSubmitting,
    submissionDepth,
    error: options.error,
    serverBaseline,
    pendingRebase: undefined,
    submissionBaseline: isSubmitting ? submissionBaseline : undefined,
  };
  nextDraft.dirty = nextDraft.promptDirty || nextDraft.referenceDirty;
  return sameDraft(draft, nextDraft) ? state : updateDraft(state, slotId, nextDraft);
}

export function markSlotDraftClean(
  state: SlotMicroEditState,
  slotId: string,
  slot?: WorkflowSlotV2,
  promptPersisted = true,
  referenceBaselineAuthoritative = false,
): SlotMicroEditState {
  if (!state.draftsBySlotId[slotId]) return state;
  return completeSlotDraftSubmission(state, slotId, { slot, promptPersisted, referenceBaselineAuthoritative });
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
  const addAttachment = useCallback((slotId: string, attachment: SlotMicroEditAttachment, trackRevision = true) => setState((current) => addSlotDraftAttachment(current, slotId, attachment, trackRevision)), []);
  const updateAttachment = useCallback((slotId: string, attachmentId: string, patch: Partial<SlotMicroEditAttachment>) => setState((current) => updateSlotDraftAttachment(current, slotId, attachmentId, patch)), []);
  const setSubmitting = useCallback((slotId: string, isSubmitting: boolean, error?: string) => setState((current) => setSlotDraftSubmitting(current, slotId, isSubmitting, error)), []);
  const markClean = useCallback((slotId: string, slot?: WorkflowSlotV2, promptPersisted = true, referenceBaselineAuthoritative = false) => setState((current) => markSlotDraftClean(current, slotId, slot, promptPersisted, referenceBaselineAuthoritative)), []);
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
    submissionDepth: 0,
    promptRevision: 0,
    referenceRevision: 0,
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

function mergeSuccessfulSubmissionBaseline(
  returned: SlotMicroEditServerBaseline,
  pending: SlotMicroEditServerBaseline | undefined,
  persistedUserPrompt: string | undefined,
  referenceBaselineAuthoritative = false,
): SlotMicroEditServerBaseline {
  if (!pending && persistedUserPrompt === undefined) return returned;
  const merged = {
    ...returned,
    user_prompt: returned.user_prompt === undefined ? persistedUserPrompt : returned.user_prompt,
    system_suggested_prompt: pending?.system_suggested_prompt ?? returned.system_suggested_prompt,
    reference_asset_ids: referenceBaselineAuthoritative ? returned.reference_asset_ids : pending?.reference_asset_ids ?? returned.reference_asset_ids,
    attachments: referenceBaselineAuthoritative ? returned.attachments : pending?.attachments ?? returned.attachments,
  };
  return { ...merged, prompt: effectiveSlotPrompt(merged) };
}

function draftReferencesDifferFromBaseline(draft: SlotMicroEditDraft, baseline: SlotMicroEditServerBaseline) {
  if (!sameStringSet(draft.reference_asset_ids, baseline.reference_asset_ids) || draft.uploaded_asset_ids.length > 0) return true;
  const baselineAssetIds = new Set(baseline.reference_asset_ids);
  const unresolvedLibraryEntity = draft.library_entity_ids.some((entityId) => !draft.attachments.some((attachment) =>
    attachment.library_entity_id === entityId && attachment.source_asset_id && baselineAssetIds.has(attachment.source_asset_id)
  ));
  if (unresolvedLibraryEntity) return true;
  return draft.attachments.some((attachment) => attachment.status === "failed" || !attachment.source_asset_id);
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
    submissionDepthOf(left) === submissionDepthOf(right) &&
    revisionOf(left.promptRevision) === revisionOf(right.promptRevision) &&
    revisionOf(left.referenceRevision) === revisionOf(right.referenceRevision) &&
    left.error === right.error &&
    sameStrings(left.reference_asset_ids, right.reference_asset_ids) &&
    sameStrings(left.uploaded_asset_ids, right.uploaded_asset_ids) &&
    sameStrings(left.library_entity_ids, right.library_entity_ids) &&
    sameAttachments(left.attachments, right.attachments) &&
    sameServerBaseline(left.serverBaseline, right.serverBaseline) &&
    sameServerBaseline(left.pendingRebase, right.pendingRebase) &&
    sameSubmissionBaseline(left.submissionBaseline, right.submissionBaseline)
  );
}

function sameSubmissionBaseline(left: SlotMicroEditSubmissionBaseline | undefined, right: SlotMicroEditSubmissionBaseline | undefined) {
  return left === right || Boolean(left && right &&
    left.prompt === right.prompt &&
    left.promptRevision === right.promptRevision &&
    left.referenceRevision === right.referenceRevision);
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

function sameStringSet(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const rightValues = new Set(right);
  return left.every((value) => rightValues.has(value));
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
    submissionDepth: 0,
    promptRevision: 0,
    referenceRevision: 0,
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

function revisionOf(value?: number) {
  return value ?? 0;
}

function submissionDepthOf(draft: Pick<SlotMicroEditDraft, "isSubmitting" | "submissionDepth">) {
  return draft.submissionDepth ?? (draft.isSubmitting ? 1 : 0);
}

function scrubInlineMedia(value: string) {
  return value.replace(/data:(?:image|video|audio)\/[a-z0-9.+-]+;base64,[^\s"')]+/gi, "[inline media omitted]");
}
