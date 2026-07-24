import { describe, expect, it } from "vitest";

import type { V2CompositionCapabilities } from "../../../types-v2.ts";
import {
  classifyFinalCompositionError,
  finalCompositionDisplayStatus,
  supportsAdvancedTimelineEditor,
} from "./v2FinalCompositionPolicy.ts";

function capabilities(
  renderMode: V2CompositionCapabilities["render_mode"],
): V2CompositionCapabilities {
  return {
    render_mode: renderMode,
    supports_timeline_controls: renderMode === "timeline_editor",
    supports_shot_reorder: renderMode === "timeline_editor",
    supports_bgm_volume_edit: renderMode === "timeline_editor",
  };
}

describe("V2 Final Composition policy", () => {
  it("opens the advanced editor only for an explicit timeline_editor capability", () => {
    expect(supportsAdvancedTimelineEditor(capabilities("simple_sequence"))).toBe(false);
    expect(supportsAdvancedTimelineEditor(capabilities("timeline_editor"))).toBe(true);
    expect(supportsAdvancedTimelineEditor({
      ...capabilities("timeline_editor"),
      supports_timeline_controls: false,
    })).toBe(false);
  });

  it.each([
    "composition_inputs_not_settled",
    "v2_composition_inputs_not_settled",
  ])("classifies %s as a non-failure waiting state", (code) => {
    expect(classifyFinalCompositionError(code)).toEqual({
      kind: "waiting",
      status: "blocked",
      message: "正在等待视频/BGM 生成完成",
    });
    expect(finalCompositionDisplayStatus("failed", code)).toBe("blocked");
  });

  it.each([
    "no_successful_video_segments",
    "v2_no_successful_video_segments",
  ])("classifies %s as skipped", (code) => {
    expect(classifyFinalCompositionError(code)).toEqual({
      kind: "skipped",
      status: "skipped",
      message: "没有可用于合成的视频片段",
    });
    expect(finalCompositionDisplayStatus("failed", code)).toBe("skipped");
  });

  it("keeps ordinary failures and lifecycle states unchanged", () => {
    expect(classifyFinalCompositionError("provider_failed")).toBeNull();
    expect(finalCompositionDisplayStatus("queued", null)).toBe("queued");
    expect(finalCompositionDisplayStatus("running", null)).toBe("running");
    expect(finalCompositionDisplayStatus("completed", null)).toBe("completed");
    expect(finalCompositionDisplayStatus("cancelled", null)).toBe("cancelled");
    expect(finalCompositionDisplayStatus("failed", "provider_failed")).toBe("failed");
  });
});
