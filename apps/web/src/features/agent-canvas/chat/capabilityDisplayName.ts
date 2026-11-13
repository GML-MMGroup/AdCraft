import type { AgentCapabilityIdV2 } from "../../../types-v2.ts";
import { translateUi, type UiMessageKey } from "../../../i18n/uiMessages.ts";

const ROLE_LABELS: Record<AgentCapabilityIdV2, UiMessageKey> = {
  world_setting: "World Setting Designer",
  product_design: "Product Designer",
  prop_design: "Prop Designer",
  character_design: "Character Designer",
  scene_design: "Scene Designer",
  script_authoring: "Script Writer",
  storyboard_design: "Storyboard Artist",
  video_direction: "Video Director",
  bgm_direction: "BGM Director",
  quick_media: "Quick Media",
};

/** Role labels follow the UI language, independently of the task's response language. */
export function capabilityDisplayName(id: AgentCapabilityIdV2, name: string, locale: string): string {
  if (!locale.toLowerCase().startsWith("zh") && !/\p{Script=Han}/u.test(name)) return name;
  const number = /\s+[1-9]\d*$/.exec(name)?.[0] ?? "";
  return `${translateUi(locale, ROLE_LABELS[id])}${number}`;
}
