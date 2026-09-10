import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import QuickMediaAnimation, {
  QUICK_MEDIA_MOTION_PROGRAM,
} from "./QuickMediaAnimation.tsx";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

const MEDIA_PARTS = ["image-node", "video-node", "audio-node"] as const;

function opacityAt(track: AgentRoleMotionTrack, progress: number): number {
  const nextIndex = track.keyframes.findIndex((frame) => (
    Number(frame.offset) >= progress
  ));
  if (nextIndex <= 0) return Number(track.keyframes[0].opacity ?? 1);
  const previous = track.keyframes[nextIndex - 1];
  const next = track.keyframes[nextIndex];
  const localProgress = (progress - Number(previous.offset))
    / (Number(next.offset) - Number(previous.offset));
  return Number(previous.opacity ?? 1)
    + (Number(next.opacity ?? 1) - Number(previous.opacity ?? 1))
      * localProgress;
}

describe("QuickMediaAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it("keeps the media diagram still and treats the lightning as one control", () => {
    const { container } = render(<QuickMediaAnimation motionState="idle" />);
    const artwork = assertRoleArtworkContract(container, "quick-media", [
      "base",
      "image-node",
      "video-node",
      "audio-node",
      "route-dashes",
      "direction-arrows",
      "lightning",
      "lightning-active",
    ]);

    expect(artwork.querySelector('[data-part="lightning-segment-entry"]')).toBeNull();
    expect(artwork.querySelector('[data-part="lightning-segment-exit"]')).toBeNull();
    expect(artwork.querySelectorAll('[data-lightning-body="true"]')).toHaveLength(1);
    expect(artwork.querySelectorAll('[data-lightning-highlight="true"]')).toHaveLength(1);
  });

  it("charges the lightning and cycles image, video, then audio", () => {
    expect(QUICK_MEDIA_MOTION_PROGRAM.workingTransitionDurationMs).toBe(160);
    expect(QUICK_MEDIA_MOTION_PROGRAM.working.map(({ part }) => part)).toEqual([
      "lightning-active",
      ...MEDIA_PARTS,
    ]);
    expect(QUICK_MEDIA_MOTION_PROGRAM.waiting).toEqual([]);
    const [lightning, ...mediaTracks] = QUICK_MEDIA_MOTION_PROGRAM.working;
    for (const track of QUICK_MEDIA_MOTION_PROGRAM.working) {
      expect(track.options.duration).toBe(3_600);
      expect(track.options.iterations).toBe(Infinity);
      expect(track.options.easing).toBe("linear");
      expect(track.keyframes.every((frame) => (
        Object.keys(frame).every((property) => (
          property === "offset"
          || property === "opacity"
          || property === "transform"
          || property === "easing"
        ))
      ))).toBe(true);
    }
    expect(lightning.keyframes[0]).toEqual({
      offset: 0,
      opacity: 0.24,
      transform: "none",
    });
    expect(lightning.keyframes.some((frame) => (
      frame.opacity === 1
      && frame.transform === "translateY(-6px) scale(1.04)"
    ))).toBe(true);
    expect(lightning.keyframes.at(-1)).toEqual({
      ...lightning.keyframes[0],
      offset: 1,
    });

    const peaks = mediaTracks.map((track) => Number(
      track.keyframes.find((frame) => (
        frame.opacity === 1
        && frame.transform === "translateY(-8px) scale(1.04)"
      ))?.offset,
    ));
    expect(peaks).toEqual([...peaks].sort((left, right) => left - right));
    expect(new Set(peaks).size).toBe(3);
    for (let sample = 0; sample <= 1_000; sample += 1) {
      const progress = sample / 1_000;
      expect(mediaTracks.filter((track) => (
        opacityAt(track, progress) > 0.681
      )).length).toBeLessThanOrEqual(1);
    }
  });

  it("connects the program to the shared motion lifecycle", () => {
    const { container } = render(<QuickMediaAnimation motionState="working" />);
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: container.querySelector("svg") }),
      "working",
      QUICK_MEDIA_MOTION_PROGRAM,
    );
  });
});
