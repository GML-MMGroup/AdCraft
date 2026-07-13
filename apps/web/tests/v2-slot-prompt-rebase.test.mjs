import assert from "node:assert/strict";
import test from "node:test";

import { normalizeWorkflowSlotV2 } from "../src/api/v2Normalizers.ts";
import { effectiveSlotPrompt } from "../src/types-v2.ts";
import {
  createInitialSlotMicroEditState,
  openSlotMicroEdit,
  rebaseSlotMicroEditDraft,
  rebaseSlotMicroEditState,
  setSlotDraftSubmitting,
  updateSlotMicroEditPrompt,
} from "../src/features/workflow/v2/slots/useSlotMicroEdit.ts";
import { buildDirtyV2SlotPromptPatch, collectDirtyV2SlotDraftFlushes } from "../src/features/workflow/v2/slots/slotPromptFlush.ts";

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

test("rebase does not overwrite a submitting draft", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  const submitting = setSlotDraftSubmitting(opened, "slot-1", true);
  assert.equal(rebaseSlotMicroEditDraft(submitting, slot({ system_suggested_prompt: "new system prompt" })), submitting);
});

test("rebase removes archived drafts, closes their editor, and is idempotent", () => {
  const opened = openSlotMicroEdit(createInitialSlotMicroEditState(), slot());
  const removed = rebaseSlotMicroEditState(opened, []);
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
