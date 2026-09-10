import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import ProductDesignerAnimation, {
  PRODUCT_DESIGNER_MOTION_PROGRAM,
} from "./ProductDesignerAnimation.tsx";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

function trackFor(part: string): AgentRoleMotionTrack {
  const track = PRODUCT_DESIGNER_MOTION_PROGRAM.working
    .find((candidate) => candidate.part === part);
  expect(track).toBeDefined();
  return track!;
}

describe("ProductDesignerAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it("keeps only the phone, glass sweep, and camera flash", () => {
    const { container } = render(<ProductDesignerAnimation motionState="idle" />);
    const artwork = assertRoleArtworkContract(container, "product-designer", [
      "base",
      "camera-cluster",
      "glass-sweep",
      "camera-flash",
    ]);

    expect(artwork.querySelector("[data-phone-body]")).not.toBeNull();
    for (const removed of [
      "vertical-measure",
      "horizontal-measure",
      "construction-dashes",
      "drafting-details",
      "surface-highlight",
    ]) {
      expect(artwork.querySelector(`[data-part="${removed}"]`)).toBeNull();
    }
    expect(artwork.querySelector('[data-part="glass-sweep"]')?.parentElement
      ?.getAttribute("clip-path")).toMatch(/^url\(#.+\)$/);
    const flashGroup = artwork.querySelector('[data-part="camera-flash"]')!;
    for (const primitive of ["core", "star", "rays", "halo"]) {
      expect(flashGroup.querySelector(`[data-flash-${primitive}]`)).not.toBeNull();
    }
  });

  it("runs one material sweep followed by one short flash and a quiet hold", () => {
    expect(PRODUCT_DESIGNER_MOTION_PROGRAM.working.map(({ part }) => part))
      .toEqual(["glass-sweep", "camera-flash"]);
    expect(PRODUCT_DESIGNER_MOTION_PROGRAM.waiting).toEqual([]);

    const sweep = trackFor("glass-sweep");
    const flash = trackFor("camera-flash");
    expect(sweep.options.duration).toBe(3_200);
    expect(flash.options.duration).toBe(3_200);
    expect(sweep.options.iterations).toBe(Infinity);
    expect(flash.options.iterations).toBe(Infinity);

    const sweepVisible = sweep.keyframes.filter((frame) => Number(frame.opacity) > 0);
    expect((Number(sweepVisible.at(-1)?.offset) - Number(sweepVisible[0].offset)) * 3_200)
      .toBe(1_200);
    const flashVisible = flash.keyframes.filter((frame) => Number(frame.opacity) > 0);
    expect((Number(flashVisible.at(-1)?.offset) - Number(flashVisible[0].offset)) * 3_200)
      .toBeCloseTo(180, 6);
    expect(flashVisible.some((frame) => frame.transform === "scale(1)")).toBe(true);
    expect(flashVisible.some((frame) => frame.transform === "scale(1.28)"))
      .toBe(true);
    expect((Number(flashVisible[1].offset) - Number(flashVisible[0].offset)) * 3_200)
      .toBeCloseTo(35, 6);
    expect((Number(flashVisible[2].offset) - Number(flashVisible[1].offset)) * 3_200)
      .toBeCloseTo(55, 6);
    expect((Number(flashVisible[3].offset) - Number(flashVisible[2].offset)) * 3_200)
      .toBeCloseTo(90, 6);
  });

  it("connects the motion program to the shared lifecycle", () => {
    const { container } = render(<ProductDesignerAnimation motionState="working" />);
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: container.querySelector("svg") }),
      "working",
      PRODUCT_DESIGNER_MOTION_PROGRAM,
    );
  });
});
