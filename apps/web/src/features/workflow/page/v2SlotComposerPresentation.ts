import type { WorkflowSlotV2 } from "../../../types-v2.ts";

type V2SlotComposerPresentation = {
  editable: boolean;
  heading: string;
  placeholder: string;
  closeLabel: string;
  acceptedFileTypes: string | undefined;
  assetPickerEnabled: boolean;
  assetMentionsEnabled: boolean;
};

export function v2SlotComposerPresentation(
  slot: Pick<WorkflowSlotV2, "slot_type" | "media_type">,
): V2SlotComposerPresentation {
  if (slot.slot_type === "bgm_audio" && slot.media_type === "audio") {
    return {
      editable: true,
      heading: "BGM soundtrack",
      placeholder: "Describe the instrumental soundtrack, mood, pace, and energy...",
      closeLabel: "Close BGM prompt",
      acceptedFileTypes: "audio/*",
      assetPickerEnabled: false,
      assetMentionsEnabled: false,
    };
  }

  return {
    editable: slot.media_type === "image" || slot.media_type === "video",
    heading: slot.slot_type.replace(/_/g, " "),
    placeholder: "Ask the agent team...",
    closeLabel: "Close image prompt",
    acceptedFileTypes: undefined,
    assetPickerEnabled: true,
    assetMentionsEnabled: true,
  };
}
