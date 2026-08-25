import type { EditingVideoEntryV2 } from "../../../types-v2.ts";
import { buildTimelineSegments, type TimelineSegment } from "./editingTimelineMath.ts";
import type { EditingBoundInput } from "./editingModel.ts";

type EditingVideoInput = EditingBoundInput<EditingVideoEntryV2>;

export interface PlayableEditingSequence {
  videos: EditingVideoInput[];
  inactiveVideos: EditingVideoInput[];
  segments: TimelineSegment[];
  duration: number;
}

export function isBackendReadyEditingVideo(input: EditingVideoInput): boolean {
  return input.entry.enabled
    && input.asset?.status === "ready"
    && (input.node === null || input.node.status === "ready");
}

export function isPlayableEditingVideo(input: EditingVideoInput): boolean {
  return isBackendReadyEditingVideo(input) && Boolean(input.asset?.media_url);
}

export function buildPlayableEditingSequence(
  inputs: readonly EditingVideoInput[],
): PlayableEditingSequence {
  const videos = inputs.filter(isPlayableEditingVideo);
  const segments = buildTimelineSegments(videos.map((input) => ({
    referenceId: input.referenceId,
    sourceDuration: input.asset?.duration_seconds
      ?? input.entry.trim_end_seconds
      ?? input.entry.trim_start_seconds + 0.5,
    trimStart: input.entry.trim_start_seconds,
    trimEnd: input.entry.trim_end_seconds,
  })));
  return {
    videos,
    inactiveVideos: inputs.filter((input) => !isPlayableEditingVideo(input)),
    segments,
    duration: segments.at(-1)?.timelineEnd ?? 0,
  };
}
