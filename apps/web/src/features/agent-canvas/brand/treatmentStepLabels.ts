import type { UiMessageKey } from "../../../i18n/uiMessages";

export const TREATMENT_STEP_LABELS: Partial<Record<string, UiMessageKey>> = {
  hook: "Hook",
  story: "Story structure",
  character: "Character direction",
  scene: "Scene direction",
  visual: "Visual direction",
  camera: "Camera direction",
  editing: "Editing",
  sound: "Sound direction",
};

export const TREATMENT_STEP_SELECTION_PROMPTS: Partial<Record<string, UiMessageKey>> = {
  hook: "Choose your opening hook",
  story: "Choose your story structure",
  character: "Choose your character direction",
  scene: "Choose your scene direction",
  visual: "Choose your visual style",
  camera: "Choose your camera direction",
  editing: "Choose your editing rhythm",
  sound: "Choose your sound design",
};
