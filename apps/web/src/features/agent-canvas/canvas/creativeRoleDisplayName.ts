import type { UiMessageKey } from "../../../i18n/uiMessages.ts";
import type { CanvasNodeV2 } from "../../../types-v2.ts";

const roleLabels: Record<CanvasNodeV2["creative_role"], UiMessageKey> = {
  creative_brief: "Creative Brief",
  world_setting: "World Setting",
  script: "Script",
  product: "Product",
  prop: "Prop",
  character: "Character",
  scene: "Scene",
  storyboard_sequence: "Storyboard Sequence",
  storyboard_video: "Storyboard Video",
  bgm: "BGM",
  general_text: "General Text",
  general_image: "General Image",
  general_video: "General Video",
  general_audio: "General Audio",
  editing: "Editing",
};

export function creativeRoleDisplayName(role: CanvasNodeV2["creative_role"]): UiMessageKey {
  return roleLabels[role];
}
