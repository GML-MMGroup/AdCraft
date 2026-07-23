import type { V2CompositionCapabilities } from "../../../types-v2.ts";

export type V2FinalCompositionIssue = {
  kind: "waiting" | "skipped";
  status: "blocked" | "skipped";
  message: string;
};

const INPUTS_NOT_SETTLED_CODES = new Set([
  "composition_inputs_not_settled",
  "v2_composition_inputs_not_settled",
]);

const NO_VIDEO_SEGMENT_CODES = new Set([
  "no_successful_video_segments",
  "v2_no_successful_video_segments",
]);

export function supportsAdvancedTimelineEditor(capabilities: V2CompositionCapabilities) {
  return capabilities.render_mode === "timeline_editor"
    && capabilities.supports_timeline_controls;
}

export function classifyFinalCompositionError(code: string | null | undefined): V2FinalCompositionIssue | null {
  const normalized = code?.trim().toLowerCase() ?? "";
  if (INPUTS_NOT_SETTLED_CODES.has(normalized)) {
    return {
      kind: "waiting",
      status: "blocked",
      message: "正在等待视频/BGM 生成完成",
    };
  }
  if (NO_VIDEO_SEGMENT_CODES.has(normalized)) {
    return {
      kind: "skipped",
      status: "skipped",
      message: "没有可用于合成的视频片段",
    };
  }
  return null;
}

export function finalCompositionDisplayStatus(status: string, errorCode: string | null | undefined) {
  return classifyFinalCompositionError(errorCode)?.status ?? status;
}
