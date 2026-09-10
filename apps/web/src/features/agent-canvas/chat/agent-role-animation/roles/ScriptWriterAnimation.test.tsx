import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import ScriptWriterAnimation, { SCRIPT_WRITER_MOTION_PROGRAM } from "./ScriptWriterAnimation.tsx";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({ useAgentRoleMotion: vi.fn() }));

function pose(frame: Keyframe) {
  const transform = String(frame.transform ?? "none");
  const xy = transform.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/);
  return {
    x: Number(xy?.[1] ?? transform.match(/translateX\((-?[\d.]+)px\)/)?.[1] ?? 0),
    y: Number(xy?.[2] ?? transform.match(/translateY\((-?[\d.]+)px\)/)?.[1] ?? 0),
    opacity: Number(frame.opacity ?? 1),
  };
}

function frameAt(track: AgentRoleMotionTrack, offset: number): Keyframe {
  return track.keyframes.filter((frame) => frame.offset === offset).at(-1)!;
}

describe("ScriptWriterAnimation", () => {
  beforeEach(() => vi.mocked(useAgentRoleMotion).mockClear());

  it("keeps the paper identity with four reusable rows in a fixed writing viewport", () => {
    const { container } = render(<ScriptWriterAnimation motionState="idle" />);
    const svg = assertRoleArtworkContract(container, "script-writer", ["base", "writing-pen"]);
    expect(svg.querySelectorAll("[data-writing-row]")).toHaveLength(4);
    expect(svg.querySelector("[data-writing-viewport]")?.getAttribute("clip-path")).toContain("url(#");
    expect(svg.querySelector('[data-part="writing-pen"]')?.getAttribute("style"))
      .toContain("transform-origin: 170px 230px");
    expect(svg.querySelectorAll("image, filter")).toHaveLength(0);
    expect(svg.querySelectorAll("[data-word]").length).toBeGreaterThan(8);
  });

  it("continues indefinitely after a finite first pass, without a visible handoff reset", () => {
    const { workingIntro: intro, working: loop } = SCRIPT_WRITER_MOTION_PROGRAM;
    expect(intro?.length).toBeGreaterThan(0);
    for (const track of intro!) {
      expect(track.options.iterations).toBe(1);
      expect(track.options.duration).toBe(3_200);
      const next = loop.find(({ part }) => part === track.part)!;
      expect(next).toBeDefined();
      expect(pose(track.keyframes.at(-1)!)).toEqual(pose(next.keyframes[0]));
    }
    for (const track of loop) {
      expect(track.options.iterations).toBe(Infinity);
      expect(pose(track.keyframes.at(-1)!)).toEqual(pose(track.keyframes[0]));
      expect(track.keyframes.map(({ offset }) => offset)).toEqual(
        track.keyframes.map(({ offset }) => offset).sort((a, b) => Number(a) - Number(b)),
      );
    }
  });

  it("reveals ink at the visible pen tip, including phrase pauses, in both phases", () => {
    for (const tracks of [SCRIPT_WRITER_MOTION_PROGRAM.workingIntro!, SCRIPT_WRITER_MOTION_PROGRAM.working]) {
      const pen = tracks.find(({ part }) => part === "writing-pen")!;
      expect(pen.keyframes.every((frame) => pose(frame).opacity === 1)).toBe(true);
      const reveals = tracks.filter(({ part }) => part.startsWith("writing-row-"));
      let writtenSegments = 0;
      for (const reveal of reveals) {
        for (let i = 1; i < reveal.keyframes.length; i++) {
          const from = reveal.keyframes[i - 1], to = reveal.keyframes[i];
          if (pose(to).x <= pose(from).x || to.offset === from.offset) continue;
          for (const frame of [from, to]) {
            expect(pose(frameAt(pen, Number(frame.offset))).x).toBeCloseTo(pose(frame).x, 5);
          }
          writtenSegments++;
        }
      }
      expect(writtenSegments).toBeGreaterThanOrEqual(9);
      expect(pen.keyframes.some((frame) => String(frame.transform).includes("rotate(-6deg)"))).toBe(true);
      for (const track of tracks) for (const frame of track.keyframes) {
        expect(Object.keys(frame).every((key) => ["offset", "easing", "transform", "opacity"].includes(key))).toBe(true);
      }
    }
  });

  it("only recycles complete rows outside the visible writing area", () => {
    const rows = SCRIPT_WRITER_MOTION_PROGRAM.working.filter(({ part }) => part.startsWith("row-position-"));
    expect(rows).toHaveLength(4);
    let recycled = 0;
    for (const track of rows) for (let i = 1; i < track.keyframes.length; i++) {
      const from = track.keyframes[i - 1], to = track.keyframes[i];
      if (pose(to).y <= pose(from).y) continue;
      expect(from.offset).toBe(to.offset);
      expect(pose(from).y).toBe(190);
      expect(pose(to).y).toBe(350);
      recycled++;
    }
    expect(recycled).toBe(4);
  });

  it("eases the lifted return arc rather than travelling at a constant sampling speed", () => {
    const pen = SCRIPT_WRITER_MOTION_PROGRAM.workingIntro!.find(({ part }) => part === "writing-pen")!;
    const firstArcSample = pen.keyframes.find((frame) => Number(frame.offset) * 3200 > 880.1)!;
    expect(Number(firstArcSample.offset) * 3200).toBeGreaterThan(880 + 180 / 8);
    expect(pose(firstArcSample).x).toBeGreaterThan(100);
  });

  it("keeps unwritten row starts completely hidden instead of leaking rounded-cap dots", () => {
    for (const slot of [2, 3, 4]) {
      const reveal = SCRIPT_WRITER_MOTION_PROGRAM.workingIntro!
        .find(({ part }) => part === `writing-row-${slot}`)!;
      expect(reveal.keyframes[0].opacity).toBe(0);
      const firstVisible = reveal.keyframes.findIndex((frame) => Number(frame.opacity) > 0);
      if (firstVisible >= 0) {
        const previous = reveal.keyframes[firstVisible - 1];
        expect(previous.opacity).toBe(0);
        expect(previous.offset).toBe(reveal.keyframes[firstVisible].offset);
      }
    }
  });

  it("connects both phases to the shared lifecycle", () => {
    const { container } = render(<ScriptWriterAnimation motionState="working" />);
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: container.querySelector("svg") }), "working", SCRIPT_WRITER_MOTION_PROGRAM,
    );
    expect(SCRIPT_WRITER_MOTION_PROGRAM.waiting).toEqual([]);
  });
});
