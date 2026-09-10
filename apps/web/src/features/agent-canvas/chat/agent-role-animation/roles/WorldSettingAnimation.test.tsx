import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";
import WorldSettingAnimation, {
  WORLD_SETTING_MOTION_PROGRAM,
} from "./WorldSettingAnimation.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

describe("WorldSettingAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it("renders an enlarged globe between masked rear and foreground orbit layers", () => {
    const { container } = render(<WorldSettingAnimation motionState="idle" />);
    const artwork = assertRoleArtworkContract(container, "world-setting", [
      "base",
      "orbit-back",
      "globe-shell",
      "land-window",
      "land-strip",
      "orbit-front",
    ]);

    expect(artwork.querySelector('[data-part="globe-structure"]')).toBeNull();
    expect(artwork.querySelector('[data-part="orbit-star"]')).toBeNull();
    expect(artwork.querySelector('[data-part="highlight"]')).toBeNull();
    expect(artwork.querySelector('[data-part="accent-star"]')).not.toBeNull();
    expect(artwork.querySelector('path[d^="M111 258C113 159"]')).toBeNull();
    expect(artwork.querySelectorAll("[data-land-copy]")).toHaveLength(2);
    expect(artwork.querySelector('[data-part="land-window"]')?.getAttribute("clip-path"))
      .toMatch(/^url\(#.+\)$/);
    expect(artwork.querySelector("[data-globe-disk]")?.getAttribute("r"))
      .toBe("142");
    expect(artwork.querySelector("[data-globe-disk]")?.getAttribute("cx"))
      .toBe("266");
    expect(artwork.querySelector("[data-globe-disk]")?.getAttribute("cy"))
      .toBe("286");
    expect(artwork.querySelector("[data-land-clip]")?.getAttribute("r"))
      .toBe("138");
    expect(artwork.querySelector("[data-land-clip]")?.getAttribute("cx"))
      .toBe("266");
    expect(artwork.querySelector("[data-land-clip]")?.getAttribute("cy"))
      .toBe("286");
    expect(artwork.querySelector("[data-land-scale]")?.getAttribute("transform"))
      .toBe("translate(266 286) scale(1.173553719) translate(-250 -306)");

    const occlusion = artwork.querySelector("mask circle")!;
    expect(occlusion.getAttribute("cx")).toBe("266");
    expect(occlusion.getAttribute("cy")).toBe("286");

    const back = artwork.querySelector('[data-part="orbit-back"]')!;
    const globe = artwork.querySelector('[data-part="globe-shell"]')!;
    const front = artwork.querySelector('[data-part="orbit-front"]')!;
    expect(back.getAttribute("mask")).toMatch(/^url\(#.+\)$/);
    expect(front.getAttribute("clip-path")).toMatch(/^url\(#.+\)$/);
    expect(back.compareDocumentPosition(globe) & Node.DOCUMENT_POSITION_FOLLOWING)
      .not.toBe(0);
    expect(globe.compareDocumentPosition(front) & Node.DOCUMENT_POSITION_FOLLOWING)
      .not.toBe(0);
  });

  it("moves the land seamlessly and gives the star one restrained twinkle", () => {
    expect(WORLD_SETTING_MOTION_PROGRAM.working.map(({ part }) => part))
      .toEqual(["land-strip", "accent-star"]);
    const track = WORLD_SETTING_MOTION_PROGRAM.working[0];
    expect(track.part).toBe("land-strip");
    expect(track.keyframes).toEqual([
      { offset: 0, transform: "translateX(0px)" },
      { offset: 1, transform: "translateX(-242px)" },
    ]);
    expect(track.options).toEqual({
      duration: 5_600,
      iterations: Infinity,
      easing: "linear",
    });

    const star = WORLD_SETTING_MOTION_PROGRAM.working[1];
    expect(star.options).toEqual({
      duration: 5_600,
      iterations: Infinity,
      easing: "linear",
    });
    expect(star.keyframes).toEqual([
      { offset: 0, opacity: 0.84, transform: "scale(1)" },
      {
        offset: 0.1,
        opacity: 0.84,
        transform: "scale(1)",
        easing: "cubic-bezier(0.77, 0, 0.175, 1)",
      },
      {
        offset: 0.16,
        opacity: 1,
        transform: "scale(1.08)",
        easing: "cubic-bezier(0.77, 0, 0.175, 1)",
      },
      { offset: 0.22, opacity: 0.84, transform: "scale(1)" },
      { offset: 1, opacity: 0.84, transform: "scale(1)" },
    ]);
    expect((0.16 - 0.1) * 5_600).toBeCloseTo(336, 6);
    expect((0.22 - 0.16) * 5_600).toBeCloseTo(336, 6);
    expect(WORLD_SETTING_MOTION_PROGRAM.waiting).toEqual([]);

    const { container } = render(<WorldSettingAnimation motionState="idle" />);
    const starArtwork = container.querySelector<SVGGElement>(
      '[data-part="accent-star"]',
    )!;
    expect(starArtwork.style.transformBox).toBe("fill-box");
    expect(starArtwork.style.transformOrigin).toBe("center");
    expect(starArtwork.style.opacity).toBe("0.84");
  });

  it("uses a detailed real-map atlas with fixed sphere projection and limb masking", () => {
    const { container } = render(<WorldSettingAnimation motionState="idle" />);
    const copies = [...container.querySelectorAll("[data-land-copy]")];
    const atlases = copies.map((copy) => (
      copy.querySelector<SVGPathElement>(
        '[data-land-atlas="natural-earth-110m"]',
      )
    ));

    expect(copies).toHaveLength(2);
    expect(atlases.every(Boolean)).toBe(true);
    expect(atlases[0]?.getAttribute("d")).toBe(atlases[1]?.getAttribute("d"));
    expect((atlases[0]?.getAttribute("d")?.match(/M/g) ?? []).length)
      .toBeGreaterThanOrEqual(40);
    expect((atlases[0]?.getAttribute("d")?.match(/L/g) ?? []).length)
      .toBeGreaterThanOrEqual(500);
    expect(container.querySelector("[data-land-projection]")?.getAttribute("transform"))
      .toBe("translate(250 306) rotate(-8) scale(1 0.82) translate(-250 -306)");
    expect(container.querySelector("[data-land-limb-mask]")?.getAttribute("mask"))
      .toMatch(/^url\(#.+\)$/);
    const base = container.querySelector('[data-part="base"]')!;
    expect(container.querySelector('path[d^="M419 302"]')).toBeNull();
    expect(base.querySelector('path[stroke="#7899E2"]')).toBeNull();
  });

  it("connects the state and root to the shared motion lifecycle", () => {
    const { container } = render(<WorldSettingAnimation motionState="working" />);

    expect(useAgentRoleMotion).toHaveBeenCalledOnce();
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: container.querySelector("svg") }),
      "working",
      WORLD_SETTING_MOTION_PROGRAM,
    );
  });
});
