import assert from "node:assert/strict";
import test from "node:test";

import { normalizeWorkflowSlotV2 } from "../src/api/v2Normalizers.ts";
import { effectiveSlotPrompt } from "../src/types-v2.ts";
import { workflowV2ToWorkflowGraph } from "../src/workflow-v2/pageAdapter.ts";
import { deriveV2SlotRebaseSnapshot } from "../src/features/workflow/v2/slots/v2SlotRebaseSnapshot.ts";
import {
  createInitialSlotMicroEditState,
  addSlotDraftReference,
  completeSlotDraftSubmission,
  markSlotDraftClean,
  openSlotMicroEdit,
  rebaseSlotMicroEditDraft,
  rebaseSlotMicroEditState,
  setSlotDraftSubmitting,
  slotDraftHasPromptChanges,
  updateSlotMicroEditNegativePrompt,
  updateSlotMicroEditPrompt,
} from "../src/features/workflow/v2/slots/useSlotMicroEdit.ts";
import { buildDirtyV2SlotPromptPatch, collectDirtyV2SlotDraftFlushes } from "../src/features/workflow/v2/slots/slotPromptFlush.ts";
import { createSlotPromptEditorState, rebaseSlotPromptEditorState, runSlotPromptEditorGeneration } from "../src/features/workflow/v2/slots/slotPromptEditorState.ts";

function slot(overrides = {}) {
  return {
    slot_id: "slot-1",
    node_id: "node-1",
    item_id: "item-1",
    slot_type: "product_main_image",
    media_type: "image",
    required: true,
    status: "ready",
    slot_prompt: "compatibility prompt",
    negative_prompt: "old negative",
    explicit_reference_ids: ["persisted-reference"],
    ...overrides,
  };
}

test("normalizes layered slot prompts without collapsing their whitespace", () => {
  const normalized = normalizeWorkflowSlotV2({
    ...slot(),
    system_suggested_prompt: "  system suggestion  ",
    user_prompt: "  user instruction  ",
  });

  assert.equal(normalized.system_suggested_prompt, "  system suggestion  ");
  assert.equal(normalized.user_prompt, "  user instruction  ");
  assert.equal(effectiveSlotPrompt(normalized), "  user instruction  ");
  assert.equal(effectiveSlotPrompt(slot({ user_prompt: "   ", system_suggested_prompt: "  system  " })), "  system  ");
  assert.equal(effectiveSlotPrompt(slot({ user_prompt: "", system_suggested_prompt: "\n\t", slot_prompt: "  compatibility  " })), "  compatibility  ");
  assert.equal(effectiveSlotPrompt(slot({ user_prompt: " ", system_suggested_prompt: " ", slot_prompt: " " })), "");
});

test("rebase leaves unopened slots draft-free", () => {
  const state = createInitialSlotMicroEditState();
  assert.equal(rebaseSlotMicroEditDraft(state, slot()), state);
  assert.equal(rebaseSlotMicroEditState(state, [slot()]), state);
});

test("rebase replaces a clean draft with refreshed effective prompt and persisted references", () => {
  const initial = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  const refreshed = slot({
    system_suggested_prompt: "new system prompt",
    user_prompt: "",
    negative_prompt: "new negative",
    explicit_reference_ids: ["ref-a", "ref-b"],
  });

  const next = rebaseSlotMicroEditDraft(initial, refreshed);
  const draft = next.draftsBySlotId[refreshed.slot_id];
  assert.equal(draft.prompt, "new system prompt");
  assert.equal(draft.negative_prompt, "new negative");
  assert.deepEqual(draft.reference_asset_ids, ["ref-a", "ref-b"]);
  assert.deepEqual(draft.attachments.map((attachment) => attachment.source_asset_id), ["ref-a", "ref-b"]);
  assert.equal(draft.dirty, false);
});

test("rebase preserves a dirty draft and refreshes only its server baseline", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  const dirty = updateSlotMicroEditPrompt(opened, "slot-1", "  local draft  ");
  const draft = dirty.draftsBySlotId["slot-1"];
  const dirtyWithUpload = {
    ...dirty,
    draftsBySlotId: {
      ...dirty.draftsBySlotId,
      "slot-1": {
        ...draft,
        error: "upload pending",
        uploaded_asset_ids: ["upload-1"],
        attachments: [...draft.attachments, { id: "upload:1", source: "upload", source_asset_id: "upload-1", status: "registering" }],
      },
    },
  };
  const refreshed = slot({ user_prompt: "persisted user prompt", system_suggested_prompt: "new system prompt", negative_prompt: "server negative", explicit_reference_ids: ["ref-server"] });

  const next = rebaseSlotMicroEditDraft(dirtyWithUpload, refreshed);
  const nextDraft = next.draftsBySlotId["slot-1"];
  assert.equal(nextDraft.prompt, "  local draft  ");
  assert.equal(nextDraft.negative_prompt, "old negative");
  assert.equal(nextDraft.error, "upload pending");
  assert.deepEqual(nextDraft.uploaded_asset_ids, ["upload-1"]);
  assert.deepEqual(nextDraft.attachments.map((attachment) => attachment.id), ["reference:persisted-reference", "upload:1"]);
  assert.equal(nextDraft.serverBaseline.prompt, "persisted user prompt");
  assert.equal(nextDraft.serverBaseline.system_suggested_prompt, "new system prompt");
  assert.deepEqual(nextDraft.serverBaseline.reference_asset_ids, ["ref-server"]);
});

test("a system suggestion refresh does not replace a persisted user prompt", () => {
  const initialSlot = slot({ user_prompt: "  persisted user prompt  ", system_suggested_prompt: "old system prompt" });
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), initialSlot);
  const refreshed = slot({ user_prompt: "  persisted user prompt  ", system_suggested_prompt: "new system prompt" });

  const next = rebaseSlotMicroEditDraft(opened, refreshed);
  assert.equal(next.draftsBySlotId["slot-1"].prompt, "  persisted user prompt  ");
  assert.equal(next.draftsBySlotId["slot-1"].serverBaseline.system_suggested_prompt, "new system prompt");
});

test("rebase queues a submitting draft refresh without overwriting its visible fields", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  const submitting = setSlotDraftSubmitting(opened, "slot-1", true);
  const refreshed = rebaseSlotMicroEditDraft(submitting, slot({ system_suggested_prompt: "new system prompt" }));
  assert.equal(refreshed.draftsBySlotId["slot-1"].prompt, "compatibility prompt");
  assert.equal(refreshed.draftsBySlotId["slot-1"].pendingRebase.system_suggested_prompt, "new system prompt");
});

test("rebase removes archived drafts, closes their editor, and is idempotent", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  const removed = rebaseSlotMicroEditState(opened, [], { authoritative: true });
  assert.equal(removed.openSlotId, null);
  assert.deepEqual(removed.draftsBySlotId, {});

  const retained = rebaseSlotMicroEditState(opened, [slot()]);
  assert.equal(rebaseSlotMicroEditState(retained, [slot()]), retained);
});

test("global Run flush uses the dirty effective draft and does not replace it with a system suggestion", () => {
  const current = slot({ user_prompt: "saved user prompt", system_suggested_prompt: "new system suggestion", slot_prompt: "compatibility prompt" });
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), current);
  const dirty = updateSlotMicroEditPrompt(opened, "slot-1", "  local draft  ");
  const draft = dirty.draftsBySlotId["slot-1"];

  assert.deepEqual(buildDirtyV2SlotPromptPatch(current, draft), {
    slot_prompt: "  local draft  ",
    negative_prompt: "old negative",
  });
  assert.equal(collectDirtyV2SlotDraftFlushes([current], dirty.draftsBySlotId)[0].promptPatch.slot_prompt, "  local draft  ");
});

test("opening and reference-only edits never promote a system suggestion into a prompt PATCH", () => {
  const systemOnly = slot({ slot_prompt: undefined, system_suggested_prompt: "system-owned text", user_prompt: undefined });
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), systemOnly);
  const draft = opened.draftsBySlotId["slot-1"];
  assert.equal(draft.prompt, "system-owned text");
  assert.equal(draft.promptDirty, false);
  assert.equal(slotDraftHasPromptChanges(draft), false);
  assert.equal(buildDirtyV2SlotPromptPatch(systemOnly, draft), null);

  const referenceOnly = addSlotDraftReference(opened, "slot-1", { source: "reference_asset", asset_id: "reference-2" });
  const flush = collectDirtyV2SlotDraftFlushes([systemOnly], referenceOnly.draftsBySlotId);
  assert.equal(flush.length, 1);
  assert.equal(flush[0].promptPatch, null);
  assert.equal(flush[0].hasPendingReferences, true);
});

test("prompt ownership dirtiness follows exact baseline divergence, including empty and whitespace edits", () => {
  const systemOnly = slot({ slot_prompt: undefined, system_suggested_prompt: "system-owned text", user_prompt: undefined });
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), systemOnly);
  const edited = updateSlotMicroEditPrompt(opened, "slot-1", "  user edit  ");
  assert.equal(edited.draftsBySlotId["slot-1"].promptDirty, true);
  assert.deepEqual(buildDirtyV2SlotPromptPatch(systemOnly, edited.draftsBySlotId["slot-1"]), {
    slot_prompt: "  user edit  ",
    negative_prompt: "old negative",
  });

  const reverted = updateSlotMicroEditPrompt(edited, "slot-1", "system-owned text");
  assert.equal(reverted.draftsBySlotId["slot-1"].promptDirty, false);
  assert.equal(buildDirtyV2SlotPromptPatch(systemOnly, reverted.draftsBySlotId["slot-1"]), null);

  const whitespace = updateSlotMicroEditPrompt(opened, "slot-1", " \t ");
  assert.equal(whitespace.draftsBySlotId["slot-1"].promptDirty, true);
  assert.equal(buildDirtyV2SlotPromptPatch(systemOnly, whitespace.draftsBySlotId["slot-1"]).slot_prompt, " \t ");

  const empty = updateSlotMicroEditPrompt(opened, "slot-1", "");
  assert.equal(empty.draftsBySlotId["slot-1"].promptDirty, true);
  assert.equal(buildDirtyV2SlotPromptPatch(systemOnly, empty.draftsBySlotId["slot-1"]).slot_prompt, "");

  const negativeEdited = updateSlotMicroEditNegativePrompt(opened, "slot-1", "");
  assert.equal(negativeEdited.draftsBySlotId["slot-1"].promptDirty, true);
});

test("partial snapshots preserve drafts while declared removal and archived items clear them", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  assert.equal(rebaseSlotMicroEditState(opened, []), opened);

  const removed = rebaseSlotMicroEditState(opened, [], { authoritative: true });
  assert.equal(removed.openSlotId, null);
  assert.deepEqual(removed.draftsBySlotId, {});

  const archived = rebaseSlotMicroEditState(opened, [slot()], { archivedSlotIds: ["slot-1"] });
  assert.equal(archived.openSlotId, null);
  assert.deepEqual(archived.draftsBySlotId, {});

  const workflow = { items: [{ item_id: "item-1", lifecycle_state: "archived" }], slots: [slot()] };
  const archivedItemIds = new Set(workflow.items.filter((item) => item.lifecycle_state === "archived").map((item) => item.item_id));
  const activeSlots = workflow.slots.filter((candidate) => !archivedItemIds.has(candidate.item_id));
  const archivedByItem = workflow.slots.filter((candidate) => archivedItemIds.has(candidate.item_id)).map((candidate) => candidate.slot_id);
  const archivedItemState = rebaseSlotMicroEditState(opened, activeSlots, { authoritative: true, archivedSlotIds: archivedByItem });
  assert.equal(archivedItemState.openSlotId, null);
  assert.deepEqual(archivedItemState.draftsBySlotId, {});
});

test("submitting drafts coalesce the newest server rebase and settle with ownership precedence", () => {
  const initial = openSlotMicroEdit(createInitialSlotMicroEditState(), slot({ slot_prompt: undefined, system_suggested_prompt: "system-v1" }));
  const edited = updateSlotMicroEditPrompt(initial, "slot-1", "user-owned draft");
  const submitting = setSlotDraftSubmitting(edited, "slot-1", true);
  const refreshedOnce = rebaseSlotMicroEditDraft(submitting, slot({ slot_prompt: undefined, system_suggested_prompt: "system-v2", explicit_reference_ids: ["ref-v2"] }));
  const refreshedTwice = rebaseSlotMicroEditDraft(refreshedOnce, slot({ slot_prompt: undefined, system_suggested_prompt: "system-v3", explicit_reference_ids: ["ref-v3"] }));
  assert.equal(refreshedTwice.draftsBySlotId["slot-1"].prompt, "user-owned draft");
  assert.equal(refreshedTwice.draftsBySlotId["slot-1"].pendingRebase.system_suggested_prompt, "system-v3");

  const succeeded = completeSlotDraftSubmission(refreshedTwice, "slot-1", { promptPersisted: true, slot: slot({ slot_prompt: undefined, system_suggested_prompt: "stale-operation-system" }) });
  assert.equal(succeeded.draftsBySlotId["slot-1"].prompt, "user-owned draft");
  assert.equal(succeeded.draftsBySlotId["slot-1"].base_prompt, "user-owned draft");
  assert.equal(succeeded.draftsBySlotId["slot-1"].serverBaseline.system_suggested_prompt, "system-v3");
  assert.equal(succeeded.draftsBySlotId["slot-1"].pendingRebase, undefined);

  const failed = completeSlotDraftSubmission(refreshedTwice, "slot-1", { error: "provider failed" });
  assert.equal(failed.draftsBySlotId["slot-1"].promptDirty, true);
  assert.equal(failed.draftsBySlotId["slot-1"].error, "provider failed");
  assert.equal(failed.draftsBySlotId["slot-1"].serverBaseline.system_suggested_prompt, "system-v3");
});

test("V2SlotCard retains dirty local fields across refresh and rebases clean fields", () => {
  const systemOnly = slot({ slot_prompt: undefined, system_suggested_prompt: "system-v1" });
  const clean = createSlotPromptEditorState(systemOnly);
  const refreshedClean = rebaseSlotPromptEditorState(clean, createSlotPromptEditorState(slot({ slot_prompt: undefined, system_suggested_prompt: "system-v2" })));
  assert.equal(refreshedClean.prompt, "system-v2");

  const dirty = { ...clean, prompt: "local edit", dirty: true };
  assert.equal(rebaseSlotPromptEditorState(dirty, createSlotPromptEditorState(slot({ slot_prompt: undefined, system_suggested_prompt: "system-v2" }))), dirty);
});

test("graph conversion derives an authoritative archive-aware slot snapshot while partial arrays stay conservative", () => {
  const activeSlot = slot({ slot_id: "slot-active", item_id: "item-active" });
  const archivedSlot = slot({ slot_id: "slot-archived", item_id: "item-archived" });
  const workflow = {
    workflow_id: "workflow-1",
    workflow_schema_version: 2,
    nodes: [{ node_id: "node-1", node_type: "product-generation", title: "Product", status: "ready" }],
    items: [
      { item_id: "item-active", node_id: "node-1", item_type: "product", display_name: "Active", status: "ready", lifecycle_state: "active" },
      { item_id: "item-archived", node_id: "node-1", item_type: "product", display_name: "Archived", status: "ready", lifecycle_state: "archived" },
    ],
    slots: [activeSlot, archivedSlot],
    asset_versions: [],
    edges: [],
  };
  const graphSnapshot = deriveV2SlotRebaseSnapshot(workflowV2ToWorkflowGraph(workflow), []);
  assert.equal(graphSnapshot.authoritative, true);
  assert.deepEqual(graphSnapshot.slots.map((candidate) => candidate.slot_id), ["slot-active"]);
  assert.deepEqual(graphSnapshot.archivedSlotIds, ["slot-archived"]);

  const opened = openSlotMicroEdit(openSlotMicroEdit(createInitialSlotMicroEditState(), activeSlot), archivedSlot);
  const rebased = rebaseSlotMicroEditState({ ...opened, openSlotId: "slot-archived" }, graphSnapshot.slots, graphSnapshot);
  assert.equal(rebased.openSlotId, null);
  assert.ok(rebased.draftsBySlotId["slot-active"]);
  assert.equal(rebased.draftsBySlotId["slot-archived"], undefined);

  const linkedRefresh = deriveV2SlotRebaseSnapshot(workflowV2ToWorkflowGraph({
    ...workflow,
    slots: [slot({ slot_id: "slot-active", item_id: "item-active", slot_prompt: undefined, system_suggested_prompt: "linked system refresh" }), archivedSlot],
  }), []);
  const refreshedActive = rebaseSlotMicroEditState(rebased, linkedRefresh.slots, linkedRefresh);
  assert.equal(refreshedActive.draftsBySlotId["slot-active"].prompt, "linked system refresh");

  const partial = deriveV2SlotRebaseSnapshot(null, [activeSlot]);
  assert.equal(partial.authoritative, false);
  assert.equal(rebaseSlotMicroEditState(opened, partial.slots, partial), opened);
});

test("completion uses the returned server prompt and explicit negative clears remain in PATCH bodies", () => {
  const systemOnly = slot({ slot_prompt: undefined, system_suggested_prompt: "system fallback", user_prompt: undefined, negative_prompt: "old negative" });
  const edited = updateSlotMicroEditNegativePrompt(updateSlotMicroEditPrompt(openSlotMicroEdit(createInitialSlotMicroEditState(), systemOnly), "slot-1", ""), "slot-1", "");
  const clearedNegativePatch = buildDirtyV2SlotPromptPatch(systemOnly, edited.draftsBySlotId["slot-1"]);
  assert.deepEqual(clearedNegativePatch, { slot_prompt: "", negative_prompt: "" });

  const succeeded = completeSlotDraftSubmission(edited, "slot-1", {
    promptPersisted: true,
    slot: slot({ slot_prompt: undefined, system_suggested_prompt: "system fallback", user_prompt: "", negative_prompt: "" }),
  });
  const clean = succeeded.draftsBySlotId["slot-1"];
  assert.equal(clean.prompt, "system fallback");
  assert.equal(clean.base_prompt, "system fallback");
  assert.equal(clean.negative_prompt, "");
  assert.equal(clean.dirty, false);

  const noAuthoritativeResponse = completeSlotDraftSubmission(edited, "slot-1", { promptPersisted: true });
  assert.equal(noAuthoritativeResponse.draftsBySlotId["slot-1"].dirty, true);
});

test("failed submission rebases draft baselines to the latest pending server truth", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot({ slot_prompt: undefined, system_suggested_prompt: "system-v1", negative_prompt: "neg-v1", explicit_reference_ids: ["ref-v1"] }));
  const dirty = updateSlotMicroEditNegativePrompt(updateSlotMicroEditPrompt(opened, "slot-1", "system-v3"), "slot-1", "neg-v3");
  const submitting = setSlotDraftSubmitting(dirty, "slot-1", true);
  const refreshedOnce = rebaseSlotMicroEditDraft(submitting, slot({ slot_prompt: undefined, system_suggested_prompt: "system-v2", negative_prompt: "neg-v2", explicit_reference_ids: ["ref-v2"] }));
  const refreshedTwice = rebaseSlotMicroEditDraft(refreshedOnce, slot({ slot_prompt: undefined, system_suggested_prompt: "system-v3", negative_prompt: "neg-v3", explicit_reference_ids: ["ref-v3"] }));

  const failed = completeSlotDraftSubmission(refreshedTwice, "slot-1", { error: "save failed" });
  const draft = failed.draftsBySlotId["slot-1"];
  assert.equal(draft.prompt, "system-v3");
  assert.equal(draft.base_prompt, "system-v3");
  assert.equal(draft.base_negative_prompt, "neg-v3");
  assert.equal(draft.promptDirty, false);
  assert.equal(draft.dirty, false);
  assert.equal(draft.referenceDirty, false);
  assert.deepEqual(draft.reference_asset_ids, ["ref-v3"]);
  assert.equal(draft.error, "save failed");
});

test("SlotCard save results gate generation and never create an absent micro draft", async () => {
  const editor = { ...createSlotPromptEditorState(slot()), prompt: "local edit", dirty: true };
  let generationCount = 0;
  const failed = await runSlotPromptEditorGeneration(
    editor,
    async () => ({ ok: false }),
    async () => { generationCount += 1; },
  );
  assert.equal(failed.saved, false);
  assert.equal(failed.state, editor);
  assert.equal(generationCount, 0);

  const succeeded = await runSlotPromptEditorGeneration(
    editor,
    async () => ({ ok: true, slot: slot({ slot_prompt: undefined, system_suggested_prompt: "returned system", user_prompt: "", negative_prompt: "returned negative" }) }),
    async () => { generationCount += 1; },
  );
  assert.equal(succeeded.saved, true);
  assert.equal(succeeded.state.prompt, "returned system");
  assert.equal(succeeded.state.dirty, false);
  assert.equal(generationCount, 1);

  const blank = createInitialSlotMicroEditState();
  assert.equal(markSlotDraftClean(blank, "slot-1", slot()), blank);
});
