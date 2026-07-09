import type { V2SlotPromptUpdateRequest, WorkflowSlotV2 } from "../../../../types-v2.ts";
import type { SlotMicroEditDraft } from "./useSlotMicroEdit.ts";
import { slotDraftSubmitPayload } from "./useSlotMicroEdit.ts";

export type V2SlotDraftFlush = {
  slotId: string;
  slot: WorkflowSlotV2;
  draft: SlotMicroEditDraft;
  promptPatch: V2SlotPromptUpdateRequest | null;
  hasPendingReferences: boolean;
};

export function collectDirtyV2SlotDraftFlushes(
  slots: WorkflowSlotV2[],
  draftsBySlotId: Record<string, SlotMicroEditDraft | undefined>,
): V2SlotDraftFlush[] {
  const slotById = new Map(slots.map((slot) => [slot.slot_id, slot]));
  const flushes: V2SlotDraftFlush[] = [];

  for (const [slotId, draft] of Object.entries(draftsBySlotId)) {
    if (!draft?.dirty) continue;
    const slot = slotById.get(slotId);
    if (!slot) continue;
    const promptPatch = buildDirtyV2SlotPromptPatch(slot, draft);
    const hasPendingReferences = v2SlotDraftHasPendingReferences(draft);
    if (!promptPatch && !hasPendingReferences) continue;
    flushes.push({ slotId, slot, draft, promptPatch, hasPendingReferences });
  }

  return flushes;
}

export function buildDirtyV2SlotPromptPatch(slot: WorkflowSlotV2, draft: SlotMicroEditDraft): V2SlotPromptUpdateRequest | null {
  const payload = slotDraftSubmitPayload(draft);
  const nextPrompt = normalizePrompt(payload.slot_prompt);
  const nextNegativePrompt = normalizePrompt(payload.negative_prompt ?? "");
  const currentPrompt = normalizePrompt(slot.slot_prompt ?? "");
  const currentNegativePrompt = normalizePrompt(slot.negative_prompt ?? "");

  if (nextPrompt === currentPrompt && nextNegativePrompt === currentNegativePrompt) return null;
  return {
    slot_prompt: nextPrompt,
    negative_prompt: nextNegativePrompt || undefined,
  };
}

export function v2SlotDraftHasPendingReferences(draft: SlotMicroEditDraft) {
  const attachmentSourceAssetIds = new Set(draft.attachments.map((attachment) => attachment.source_asset_id ?? "").filter(Boolean));
  if (draft.uploaded_asset_ids.some((assetId) => assetId && !attachmentSourceAssetIds.has(assetId))) return true;

  return draft.attachments.some((attachment) => {
    if (attachment.status === "failed") return true;
    if (attachment.status === "attached" && attachment.relation_id) return false;
    if (attachment.source === "asset_library" && attachment.library_entity_id && !attachment.source_asset_id) return true;
    if (attachment.source_asset_id && !attachment.relation_id) return true;
    return attachment.status === "draft" || attachment.status === "registering" || attachment.status === "registered";
  });
}

function normalizePrompt(value: string) {
  return value.trim();
}
