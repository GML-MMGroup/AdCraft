import { effectiveSlotPrompt, type WorkflowSlotV2 } from "../../../../types-v2.ts";

export type SlotPromptEditorState = {
  prompt: string;
  negativePrompt: string;
  basePrompt: string;
  baseNegativePrompt: string;
  dirty: boolean;
};

export type SlotPromptSaveResult =
  | { ok: true; slot: Pick<WorkflowSlotV2, "slot_prompt" | "system_suggested_prompt" | "user_prompt" | "negative_prompt"> }
  | { ok: false };

export function createSlotPromptEditorState(slot: Pick<WorkflowSlotV2, "slot_prompt" | "system_suggested_prompt" | "user_prompt" | "negative_prompt">): SlotPromptEditorState {
  const prompt = effectiveSlotPrompt(slot);
  const negativePrompt = slot.negative_prompt ?? "";
  return { prompt, negativePrompt, basePrompt: prompt, baseNegativePrompt: negativePrompt, dirty: false };
}

export function rebaseSlotPromptEditorState(current: SlotPromptEditorState, server: SlotPromptEditorState): SlotPromptEditorState {
  if (current.dirty) return current;
  return current.prompt === server.prompt && current.negativePrompt === server.negativePrompt ? current : server;
}

export async function saveSlotPromptEditorState(
  submitted: SlotPromptEditorState,
  save: () => Promise<SlotPromptSaveResult> | SlotPromptSaveResult,
  latest: () => SlotPromptEditorState = () => submitted,
) {
  const result = await save();
  if (!result.ok) return { saved: false as const, state: latest() };
  return {
    saved: true as const,
    state: reconcileSuccessfulSlotPromptSave(submitted, latest(), createSlotPromptEditorState(result.slot)),
  };
}

export async function runSlotPromptEditorGeneration(
  current: SlotPromptEditorState,
  save: () => Promise<SlotPromptSaveResult> | SlotPromptSaveResult,
  generate: () => Promise<unknown> | unknown,
) {
  const saved = current.dirty ? await saveSlotPromptEditorState(current, save) : { saved: true as const, state: current };
  if (!saved.saved) return saved;
  await generate();
  return saved;
}

function reconcileSuccessfulSlotPromptSave(
  submitted: SlotPromptEditorState,
  latest: SlotPromptEditorState,
  server: SlotPromptEditorState,
): SlotPromptEditorState {
  const prompt = latest.prompt === submitted.prompt ? server.prompt : latest.prompt;
  const negativePrompt = latest.negativePrompt === submitted.negativePrompt ? server.negativePrompt : latest.negativePrompt;
  return {
    prompt,
    negativePrompt,
    basePrompt: server.basePrompt,
    baseNegativePrompt: server.baseNegativePrompt,
    dirty: prompt !== server.basePrompt || negativePrompt !== server.baseNegativePrompt,
  };
}
