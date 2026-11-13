import type { EditingVideoEntryV2 } from "../../../types-v2.ts";
import { MIN_EDITED_CLIP_SECONDS, roundTimeline, type TimelineSegment } from "./editingTimelineMath.ts";

/** Snap only within the visual tolerance; the unsnapped value is not a candidate. */
export function snapTimelineTime(value: number, candidates: readonly number[], tolerance: number): number {
  let nearest = value;
  let distance = tolerance;
  for (const candidate of candidates) {
    const nextDistance = Math.abs(candidate - value);
    if (Number.isFinite(candidate) && nextDistance <= distance) {
      nearest = candidate;
      distance = nextDistance;
    }
  }
  return nearest;
}

export function trimAtPlayhead(segment: TimelineSegment | undefined, playhead: number, edge: "start" | "end"): Partial<EditingVideoEntryV2> | null {
  if (!segment || !Number.isFinite(playhead)) return null;
  const sourceTime = roundTimeline(segment.sourceStart + playhead - segment.timelineStart);
  if (playhead <= segment.timelineStart || playhead >= segment.timelineEnd) return null;
  if (edge === "start") {
    if (segment.sourceEnd - sourceTime < MIN_EDITED_CLIP_SECONDS) return null;
    return { trim_start_seconds: sourceTime, timeline_start_seconds: roundTimeline(playhead) };
  }
  if (sourceTime - segment.sourceStart < MIN_EDITED_CLIP_SECONDS) return null;
  return { trim_end_seconds: sourceTime };
}

export function frameTime(value: number, fps: number): string {
  const rate = Number.isFinite(fps) && fps > 0 ? fps : 30;
  const totalFrames = Math.max(0, Math.round(value * rate));
  const wholeSeconds = Math.floor(totalFrames / rate);
  const frames = Math.floor(totalFrames - wholeSeconds * rate);
  return `${String(Math.floor(wholeSeconds / 60)).padStart(2, "0")}:${String(wholeSeconds % 60).padStart(2, "0")}:${String(frames).padStart(2, "0")}`;
}
