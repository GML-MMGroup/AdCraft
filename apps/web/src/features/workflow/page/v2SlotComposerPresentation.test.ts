import { describe, expect, it } from "vitest";

import type { WorkflowSlotV2 } from "../../../types-v2.ts";
import { v2SlotComposerPresentation } from "./v2SlotComposerPresentation.ts";

const bgmSlot: Pick<WorkflowSlotV2, "slot_type" | "media_type"> = {
  slot_type: "bgm_audio",
  media_type: "audio",
};

describe("v2SlotComposerPresentation", () => {
  it("uses BGM-specific composer presentation", () => {
    expect(v2SlotComposerPresentation(bgmSlot)).toEqual({
      editable: true,
      heading: "BGM soundtrack",
      placeholder: "Describe the instrumental soundtrack, mood, pace, and energy...",
      closeLabel: "Close BGM prompt",
      acceptedFileTypes: "audio/*",
      assetPickerEnabled: false,
      assetMentionsEnabled: false,
    });
  });

  it("rejects noncanonical audio slots", () => {
    expect(v2SlotComposerPresentation({ slot_type: "voice_audio", media_type: "audio" }).editable).toBe(false);
  });

  it("preserves the existing visual slot presentation", () => {
    expect(v2SlotComposerPresentation({ slot_type: "scene_main_image", media_type: "image" })).toEqual({
      editable: true,
      heading: "scene main image",
      placeholder: "Ask the agent team...",
      closeLabel: "Close image prompt",
      acceptedFileTypes: undefined,
      assetPickerEnabled: true,
      assetMentionsEnabled: true,
    });
  });
});
