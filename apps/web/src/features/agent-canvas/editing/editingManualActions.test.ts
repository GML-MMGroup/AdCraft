import { describe, expect, it } from "vitest";
import { frameTime, snapTimelineTime, trimAtPlayhead } from "./editingManualActions.ts";

const segment = { referenceId: "clip", timelineStart: 5, timelineEnd: 15, sourceStart: 20, sourceEnd: 30 };
describe("manual timeline controls", () => {
  it("snaps to the nearest edge only inside the pixel-derived tolerance", () => {
    expect(snapTimelineTime(4.94, [0, 5, 10], .08)).toBe(5);
    expect(snapTimelineTime(4.8, [0, 5, 10], .08)).toBe(4.8);
    expect(snapTimelineTime(5.06, [5, 5.1], .08)).toBe(5.1);
  });
  it("maps the composition playhead to source trim fields without shifting the remaining frames", () => {
    expect(trimAtPlayhead(segment, 8, "start")).toEqual({ trim_start_seconds: 23, timeline_start_seconds: 8 });
    expect(trimAtPlayhead(segment, 8, "end")).toEqual({ trim_end_seconds: 23 });
  });
  it("rejects playheads outside the selection and cuts shorter than the supported minimum", () => {
    for (const playhead of [0, 5, 15, 20, NaN]) expect(trimAtPlayhead(segment, playhead, "start")).toBeNull();
    expect(trimAtPlayhead(segment, 14.8, "start")).toBeNull();
    expect(trimAtPlayhead(segment, 5.2, "end")).toBeNull();
    expect(trimAtPlayhead(undefined, 8, "end")).toBeNull();
  });
  it("shows frame-accurate positions and carries whole seconds", () => {
    expect(frameTime(0, 30)).toBe("00:00:00");
    expect(frameTime(1 / 30, 30)).toBe("00:00:01");
    expect(frameTime(59 + 29 / 30, 30)).toBe("00:59:29");
    expect(frameTime(60, 30)).toBe("01:00:00");
  });
});
