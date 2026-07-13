import { effectiveSlotPrompt, type WorkflowSlotV2 } from "../../../../types-v2.ts";

export type SlotPromptEditorState = {
  prompt: string;
  negativePrompt: string;
  basePrompt: string;
  baseNegativePrompt: string;
  dirty: boolean;
};

export function createSlotPromptEditorState(slot: Pick<WorkflowSlotV2, "slot_prompt" | "system_suggested_prompt" | "user_prompt" | "negative_prompt">): SlotPromptEditorState {
  const prompt = effectiveSlotPrompt(slot);
  const negativePrompt = slot.negative_prompt ?? "";
  return { prompt, negativePrompt, basePrompt: prompt, baseNegativePrompt: negativePrompt, dirty: false };
}

export function rebaseSlotPromptEditorState(current: SlotPromptEditorState, server: SlotPromptEditorState): SlotPromptEditorState {
  if (current.dirty) return current;
  return current.prompt === server.prompt && current.negativePrompt === server.negativePrompt ? current : server;
}
