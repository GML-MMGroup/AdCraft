import { describe, expect, it } from "vitest";

import {
  buildTimelineSegments,
  bgmPlayedRatioForTimeline,
  clampPixelsPerSecond,
  clampTrimRange,
  editedClipDuration,
  fitPixelsPerSecond,
  mapTimelineTimeToSource,
  pixelsToTime,
  timeToPixels,
} from "./editingTimelineMath.ts";

describe("editing timeline math", () => {
  it("clamps trim handles without crossing the minimum duration", () => {
    expect(clampTrimRange({ sourceDuration: 10, start: 9.8, end: 4, edge: "start" }))
      .toEqual({ start: 3.5, end: 4 });
  });

  it("maps the sequence playhead into the trimmed source", () => {
    const segments = buildTimelineSegments([
      { referenceId: "a", sourceDuration: 8, trimStart: 2, trimEnd: 6 },
      { referenceId: "b", sourceDuration: 5, trimStart: 1, trimEnd: 4 },
    ]);

    expect(mapTimelineTimeToSource(segments, 5)).toMatchObject({
      referenceId: "b",
      sourceSeconds: 2,
    });
  });

  it("uses fit-all as the minimum zoom", () => {
    expect(fitPixelsPerSecond(900, 30)).toBe(30);
    expect(clampPixelsPerSecond(10, { viewportWidth: 900, duration: 30, max: 180 })).toBe(30);
  });

  it("calculates edited duration from explicit trim fields", () => {
    expect(editedClipDuration(8, 2, 6)).toBe(4);
    expect(editedClipDuration(8, 2, null)).toBe(6);
  });

  it("preserves source clips shorter than the minimum edited duration", () => {
    expect(editedClipDuration(0.25, 0, null)).toBe(0.25);

    const [segment] = buildTimelineSegments([
      { referenceId: "short", sourceDuration: 0.25, trimStart: 0, trimEnd: null },
    ]);
    expect(segment).toMatchObject({
      timelineEnd: 0.25,
      sourceStart: 0,
      sourceEnd: 0.25,
    });
    expect(segment.sourceEnd).toBeLessThanOrEqual(0.25);
  });

  it("bounds invalid and out-of-range trim inputs to the source", () => {
    const [invalid] = buildTimelineSegments([
      { referenceId: "invalid", sourceDuration: 10, trimStart: Number.NaN, trimEnd: Number.POSITIVE_INFINITY },
    ]);
    expect(invalid).toMatchObject({ sourceStart: 0, sourceEnd: 10, timelineEnd: 10 });

    const [outOfRange] = buildTimelineSegments([
      { referenceId: "out-of-range", sourceDuration: 10, trimStart: 20, trimEnd: 30 },
    ]);
    expect(outOfRange.sourceStart).toBe(9.5);
    expect(outOfRange.sourceEnd).toBe(10);
    expect(outOfRange.sourceEnd).toBeLessThanOrEqual(10);
  });

  it("maps pixels and seconds using the same scale", () => {
    expect(timeToPixels(2.5, 40)).toBe(100);
    expect(pixelsToTime(100, 40)).toBe(2.5);
    expect(pixelsToTime(100, 0)).toBe(0);
  });

  it("aligns BGM waveform progress with the shared timeline playhead", () => {
    expect(bgmPlayedRatioForTimeline({
      playheadSeconds: 4,
      timelineDuration: 10,
      sourceDuration: 20,
      trimStart: 2,
      trimEnd: 12,
    })).toBeCloseTo(0.6);
  });

  it("treats segment ends as half-open except at the timeline terminus", () => {
    const segments = buildTimelineSegments([
      { referenceId: "a", sourceDuration: 2, trimStart: 0, trimEnd: 1 },
      { referenceId: "b", sourceDuration: 2, trimStart: 0.5, trimEnd: 1.5 },
    ]);

    expect(mapTimelineTimeToSource(segments, 1)?.referenceId).toBe("b");
    expect(mapTimelineTimeToSource(segments, 2)?.referenceId).toBe("b");
    expect(mapTimelineTimeToSource(segments, 2.0001)).toBeNull();
  });
});
