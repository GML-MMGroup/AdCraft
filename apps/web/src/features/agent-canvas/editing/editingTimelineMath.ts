import type { EditingVideoEntryV2 } from "../../../types-v2.ts";

export const MIN_EDITED_CLIP_SECONDS = 0.5;

export interface TimelineSegment {
  referenceId: string;
  timelineStart: number;
  timelineEnd: number;
  sourceStart: number;
  sourceEnd: number;
}

export interface TimelineClipInput {
  referenceId: string;
  sourceDuration: number;
  trimStart: number;
  trimEnd: number | null;
}

interface TrimRangeInput {
  sourceDuration: number;
  start: number;
  end: number;
  edge: "start" | "end";
}

interface BgmPlayedRatioInput {
  playheadSeconds: number;
  timelineDuration: number;
  sourceDuration: number;
  trimStart: number;
  trimEnd: number | null;
}

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function sourceDurationOf(value: number): number {
  return Math.max(0, finiteOr(value, 0));
}

function normalizeTrimRange(sourceDuration: number, start: number, end: number): { start: number; end: number } {
  const duration = sourceDurationOf(sourceDuration);
  const minimum = Math.min(MIN_EDITED_CLIP_SECONDS, duration);
  const boundedStart = Math.min(duration, Math.max(0, finiteOr(start, 0)));
  const boundedEnd = Math.min(duration, Math.max(0, finiteOr(end, duration)));

  if (boundedEnd - boundedStart >= minimum) {
    return { start: boundedStart, end: boundedEnd };
  }
  if (boundedStart + minimum <= duration) {
    return { start: boundedStart, end: boundedStart + minimum };
  }
  return { start: Math.max(0, boundedEnd - minimum), end: boundedEnd };
}

export function clampTrimRange(input: TrimRangeInput): { start: number; end: number } {
  const duration = sourceDurationOf(input.sourceDuration);
  const minimum = Math.min(MIN_EDITED_CLIP_SECONDS, duration);
  const fixedEdge = input.edge === "start"
    ? Math.min(duration, Math.max(0, finiteOr(input.end, duration)))
    : Math.min(duration, Math.max(0, finiteOr(input.start, 0)));
  const draggedEdge = input.edge === "start"
    ? Math.min(fixedEdge - minimum, Math.max(0, finiteOr(input.start, 0)))
    : Math.max(fixedEdge + minimum, Math.min(duration, finiteOr(input.end, duration)));

  return input.edge === "start"
    ? { start: Math.max(0, draggedEdge), end: fixedEdge }
    : { start: fixedEdge, end: Math.min(duration, draggedEdge) };
}

export function editedClipDuration(
  sourceDuration: number,
  trimStart: number | Pick<EditingVideoEntryV2, "trim_start_seconds" | "trim_end_seconds">,
  trimEnd?: number | null,
): number {
  const start = typeof trimStart === "number" ? trimStart : trimStart.trim_start_seconds;
  const end = typeof trimStart === "number" ? trimEnd ?? sourceDuration : trimStart.trim_end_seconds ?? sourceDuration;
  const range = normalizeTrimRange(sourceDuration, start, end);
  return Math.min(sourceDurationOf(sourceDuration), Math.max(MIN_EDITED_CLIP_SECONDS, range.end - range.start));
}

export function buildTimelineSegments(clips: readonly TimelineClipInput[]): TimelineSegment[] {
  let timelineStart = 0;
  return clips.map((clip) => {
    const sourceDuration = sourceDurationOf(clip.sourceDuration);
    const range = normalizeTrimRange(sourceDuration, clip.trimStart, clip.trimEnd ?? sourceDuration);
    const duration = Math.min(sourceDuration, Math.max(MIN_EDITED_CLIP_SECONDS, range.end - range.start));
    const segment = {
      referenceId: clip.referenceId,
      timelineStart,
      timelineEnd: timelineStart + duration,
      sourceStart: range.start,
      sourceEnd: range.start + duration,
    };
    timelineStart = segment.timelineEnd;
    return segment;
  });
}

export function fitPixelsPerSecond(viewportWidth: number, duration: number): number {
  const width = Math.max(0, finiteOr(viewportWidth, 0));
  const seconds = Math.max(0, finiteOr(duration, 0));
  return seconds > 0 ? width / seconds : 0;
}

export function clampPixelsPerSecond(
  pixelsPerSecond: number,
  options: { viewportWidth: number; duration: number; max: number },
): number {
  const minimum = fitPixelsPerSecond(options.viewportWidth, options.duration);
  const maximum = Math.max(minimum, finiteOr(options.max, minimum));
  return Math.min(maximum, Math.max(minimum, finiteOr(pixelsPerSecond, minimum)));
}

export function timeToPixels(seconds: number, pixelsPerSecond: number): number {
  return seconds * pixelsPerSecond;
}

export function pixelsToTime(pixels: number, pixelsPerSecond: number): number {
  return pixelsPerSecond > 0 ? pixels / pixelsPerSecond : 0;
}

export function bgmPlayedRatioForTimeline(input: BgmPlayedRatioInput): number {
  const sourceDuration = sourceDurationOf(input.sourceDuration);
  const timelineDuration = sourceDurationOf(input.timelineDuration);
  const range = normalizeTrimRange(
    sourceDuration,
    input.trimStart,
    input.trimEnd ?? sourceDuration,
  );
  const selectedDuration = Math.max(0, range.end - range.start);
  if (!sourceDuration || !selectedDuration) return 0;

  if (!timelineDuration) {
    return Math.min(1, Math.max(0, finiteOr(input.playheadSeconds, 0) / selectedDuration));
  }

  const playheadRatio = Math.min(1, Math.max(0, finiteOr(input.playheadSeconds, 0) / timelineDuration));
  const selectionStartRatio = range.start / sourceDuration;
  const selectionWidthRatio = selectedDuration / sourceDuration;
  return Math.min(1, Math.max(0, (playheadRatio - selectionStartRatio) / selectionWidthRatio));
}

export function mapTimelineTimeToSource(
  segments: readonly TimelineSegment[],
  timelineSeconds: number,
): (TimelineSegment & { sourceSeconds: number }) | null {
  const time = finiteOr(timelineSeconds, 0);
  const index = segments.findIndex((segment) => (
    time >= segment.timelineStart && time < segment.timelineEnd
  ));
  const final = segments.at(-1);
  const segment = index >= 0 ? segments[index] : time === final?.timelineEnd ? final : undefined;
  if (!segment) return null;

  return {
    ...segment,
    sourceSeconds: segment.sourceStart + Math.min(
      segment.timelineEnd - segment.timelineStart,
      Math.max(0, time - segment.timelineStart),
    ),
  };
}
