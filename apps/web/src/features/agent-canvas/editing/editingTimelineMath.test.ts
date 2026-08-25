import { describe, expect, it } from "vitest";

import {
  buildTimelineSegments,
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

  it("maps pixels and seconds using the same scale", () => {
    expect(timeToPixels(2.5, 40)).toBe(100);
    expect(pixelsToTime(100, 40)).toBe(2.5);
    expect(pixelsToTime(100, 0)).toBe(0);
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
