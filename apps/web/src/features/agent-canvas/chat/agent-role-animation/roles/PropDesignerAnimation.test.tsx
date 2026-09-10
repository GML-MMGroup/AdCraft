import { render } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";
import PropDesignerAnimation, {
  PROP_DESIGNER_MOTION_PROGRAM,
} from "./PropDesignerAnimation.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

const REQUIRED_PARTS = [
  "base",
  "lamp-body",
  "stand",
  "shade",
  "shade-light",
  "trim",
  "tassels",
  "pull-chain",
  "blueprint",
  "blueprint-guides",
] as const;

const PRIMARY_GUIDES = [
  "guide-active-horizontal",
  "guide-active-vertical",
  "guide-active-cross",
] as const;

const FIXED_PARTS = [
  "base",
  "lamp-body",
  "stand",
  "shade",
  "trim",
  "blueprint",
  "blueprint-guides",
] as const;

interface Translation {
  x: number;
  y: number;
}

function trackFor(
  part: string,
  phase: "working" | "waiting",
): AgentRoleMotionTrack {
  const track = PROP_DESIGNER_MOTION_PROGRAM[phase]
    .find((candidate) => candidate.part === part);
  expect(track, `missing ${phase} track for ${part}`).toBeDefined();
  return track!;
}

function translationFor(keyframe: Keyframe): Translation {
  const transform = String(keyframe.transform ?? "none");
  const axisMatch = transform.match(/translate([XY])\((-?[\d.]+)px\)/);
  if (axisMatch?.[1] === "X") return { x: Number(axisMatch[2]), y: 0 };
  if (axisMatch?.[1] === "Y") return { x: 0, y: Number(axisMatch[2]) };
  if (transform === "none") return { x: 0, y: 0 };
  throw new Error(`unexpected translation transform ${transform}`);
}

function rotationFor(keyframe: Keyframe): number {
  const transform = String(keyframe.transform ?? "none");
  const match = transform.match(/rotate\((-?[\d.]+)deg\)/);
  if (match) return Number(match[1]);
  if (transform === "none") return 0;
  throw new Error(`unexpected rotation transform ${transform}`);
}

function canonicalValue(keyframe: Keyframe, property: "transform" | "opacity") {
  return keyframe[property] ?? (property === "transform" ? "none" : 1);
}

function firstChangedOffset(track: AgentRoleMotionTrack): number | undefined {
  const first = track.keyframes[0];
  return track.keyframes.find((frame) => (
    canonicalValue(frame, "transform") !== canonicalValue(first, "transform")
    || canonicalValue(frame, "opacity") !== canonicalValue(first, "opacity")
  ))?.offset;
}

function clippedLineLengths(
  artwork: SVGSVGElement,
  partName: string,
  track: AgentRoleMotionTrack,
): number[] {
  const part = artwork.querySelector<SVGGElement>(`[data-part="${partName}"]`)!;
  const line = part.querySelector<SVGLineElement>("line")!;
  const clipId = part.parentElement?.getAttribute("clip-path")
    ?.match(/^url\(#(.+)\)$/)?.[1];
  const clip = artwork.querySelector<SVGRectElement>(
    `clipPath[id="${clipId}"] rect`,
  )!;
  const lineStart = {
    x: Number(line.getAttribute("x1")),
    y: Number(line.getAttribute("y1")),
  };
  const lineEnd = {
    x: Number(line.getAttribute("x2")),
    y: Number(line.getAttribute("y2")),
  };
  const clipStart = {
    x: Number(clip.getAttribute("x")),
    y: Number(clip.getAttribute("y")),
  };
  const clipEnd = {
    x: clipStart.x + Number(clip.getAttribute("width")),
    y: clipStart.y + Number(clip.getAttribute("height")),
  };

  return track.keyframes.map((frame) => {
    const translation = translationFor(frame);
    if (lineStart.x === lineEnd.x) {
      return Math.max(
        0,
        Math.min(Math.max(lineStart.y, lineEnd.y) + translation.y, clipEnd.y)
          - Math.max(Math.min(lineStart.y, lineEnd.y) + translation.y, clipStart.y),
      );
    }
    return Math.max(
      0,
      Math.min(Math.max(lineStart.x, lineEnd.x) + translation.x, clipEnd.x)
        - Math.max(Math.min(lineStart.x, lineEnd.x) + translation.x, clipStart.x),
    );
  });
}

describe("PropDesignerAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it("renders one layered lamp and blueprint contract", () => {
    const { container } = render(<PropDesignerAnimation motionState="idle" />);
    const artwork = assertRoleArtworkContract(
      container,
      "prop-designer",
      REQUIRED_PARTS,
    );

    expect(artwork.querySelectorAll('[data-part="pull-chain"] circle'))
      .toHaveLength(1);
    expect(artwork.querySelectorAll('[data-part="blueprint"] [data-fold]'))
      .toHaveLength(1);
    expect(artwork.querySelector('[data-part="tassels"]')
      ?.closest('[data-part="lamp-body"]')).not.toBeNull();
  });

  it("uses exact guide, chain-response, and waiting periods without duplicate ownership", () => {
    expect(PRIMARY_GUIDES.map((part) => trackFor(part, "working").options.duration))
      .toEqual(PRIMARY_GUIDES.map(() => 3_600));
    expect(trackFor("pull-chain", "working").options.duration).toBe(7_200);
    expect(trackFor("tassels", "working").options.duration).toBe(7_200);
    expect(trackFor("shade-light", "working").options.duration).toBe(7_200);

    expect(PROP_DESIGNER_MOTION_PROGRAM.waiting.map((track) => track.part))
      .toEqual(["shade-light", "guide-active-vertical"]);
    expect(PROP_DESIGNER_MOTION_PROGRAM.waiting.map((track) => (
      track.options.duration
    ))).toEqual([4_800, 4_800]);

    for (const phase of ["working", "waiting"] as const) {
      const parts = PROP_DESIGNER_MOTION_PROGRAM[phase]
        .map((track) => track.part);
      expect(parts).toHaveLength(new Set(parts).size);
    }
  });

  it("keeps the complete lamp silhouette and blueprint sheet fixed", () => {
    const movingParts = new Set([
      ...PROP_DESIGNER_MOTION_PROGRAM.working,
      ...PROP_DESIGNER_MOTION_PROGRAM.waiting,
    ].map((track) => track.part));

    for (const part of FIXED_PARTS) expect(movingParts).not.toContain(part);
    expect(movingParts).not.toContain("root");
  });

  it("reveals the light through a shade-intersecting clip that trims its fill", () => {
    const { container } = render(<PropDesignerAnimation motionState="working" />);
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const light = artwork.querySelector<SVGGElement>('[data-part="shade-light"]')!;
    const clipId = light.getAttribute("clip-path")?.match(/^url\(#(.+)\)$/)?.[1];
    const polygon = artwork.querySelector<SVGPolygonElement>(
      `clipPath[id="${clipId}"] polygon`,
    )!;
    const fill = light.querySelector<SVGRectElement>("rect")!;
    const points = polygon.getAttribute("points")?.trim().split(/\s+/).map((pair) => {
      const [x, y] = pair.split(",").map(Number);
      return { x, y };
    }) ?? [];
    const clipBounds = {
      left: Math.min(...points.map(({ x }) => x)),
      right: Math.max(...points.map(({ x }) => x)),
      top: Math.min(...points.map(({ y }) => y)),
      bottom: Math.max(...points.map(({ y }) => y)),
    };
    const fillBounds = {
      left: Number(fill.getAttribute("x")),
      right: Number(fill.getAttribute("x")) + Number(fill.getAttribute("width")),
      top: Number(fill.getAttribute("y")),
      bottom: Number(fill.getAttribute("y")) + Number(fill.getAttribute("height")),
    };
    const overlapWidth = Math.min(clipBounds.right, fillBounds.right)
      - Math.max(clipBounds.left, fillBounds.left);
    const overlapHeight = Math.min(clipBounds.bottom, fillBounds.bottom)
      - Math.max(clipBounds.top, fillBounds.top);

    expect(points.length).toBeGreaterThanOrEqual(5);
    expect(overlapWidth).toBeGreaterThan(0);
    expect(overlapHeight).toBeGreaterThan(0);
    expect(fillBounds.left < clipBounds.left || fillBounds.right > clipBounds.right)
      .toBe(true);
    expect(fillBounds.top < clipBounds.top || fillBounds.bottom > clipBounds.bottom)
      .toBe(true);
  });

  it("draws spatially distinct blueprint guides in temporal order inside local clips", () => {
    const { container } = render(<PropDesignerAnimation motionState="working" />);
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const centers: { x: number; y: number }[] = [];

    for (const partName of PRIMARY_GUIDES) {
      const part = artwork.querySelector<SVGGElement>(
        `[data-part="${partName}"]`,
      )!;
      const clipId = part.parentElement?.getAttribute("clip-path")
        ?.match(/^url\(#(.+)\)$/)?.[1];
      const clip = artwork.querySelector<SVGRectElement>(
        `clipPath[id="${clipId}"] rect`,
      )!;
      const width = Number(clip.getAttribute("width"));
      const height = Number(clip.getAttribute("height"));
      const lengths = clippedLineLengths(
        artwork,
        partName,
        trackFor(partName, "working"),
      );

      expect(part.closest('[data-part="blueprint-guides"]')).not.toBeNull();
      expect(width).toBeLessThan(100);
      expect(height).toBeLessThan(100);
      expect(Math.max(...lengths)).toBeGreaterThan(Math.min(...lengths));
      centers.push({
        x: Number(clip.getAttribute("x")) + width / 2,
        y: Number(clip.getAttribute("y")) + height / 2,
      });
    }

    expect(new Set(centers.map(({ x, y }) => `${x},${y}`))).toHaveLength(3);
    expect(PRIMARY_GUIDES.map((part) => firstChangedOffset(
      trackFor(part, "working"),
    ))).toEqual([0.18, 0.42, 0.66]);
  });

  it("keeps every guide clip on a static parent window around the animated child", () => {
    const { container } = render(<PropDesignerAnimation motionState="working" />);
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const motionTargets = new Set([
      ...PROP_DESIGNER_MOTION_PROGRAM.working,
      ...PROP_DESIGNER_MOTION_PROGRAM.waiting,
    ].map(({ part }) => part));

    for (const partName of PRIMARY_GUIDES) {
      const animatedPart = artwork.querySelector<SVGGElement>(
        `[data-part="${partName}"]`,
      )!;
      const window = animatedPart.parentElement as SVGGElement;
      const clipReference = window.getAttribute("clip-path");
      const clipId = clipReference?.match(/^url\(#(.+)\)$/)?.[1];

      expect(animatedPart.getAttribute("clip-path"), partName).toBeNull();
      expect(window.tagName.toLowerCase(), partName).toBe("g");
      expect(clipId, partName).toBeDefined();
      expect(window.getAttribute("data-part"), partName).toBeNull();
      expect(motionTargets.has(window.getAttribute("data-part") ?? ""), partName)
        .toBe(false);
      expect(window.style.transform, partName).toBe("");
      expect(artwork.querySelector(
        `clipPath[id="${clipId}"][clipPathUnits="userSpaceOnUse"]`,
      ), partName).not.toBeNull();
    }
  });

  it("emits SSR-safe, instance-unique clip ids and resolvable references", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToString(
      <>
        <PropDesignerAnimation motionState="idle" />
        <PropDesignerAnimation motionState="idle" />
      </>,
    );
    const ids = [...host.querySelectorAll("clipPath")].map((clip) => clip.id);

    expect(ids).toHaveLength(8);
    expect(new Set(ids)).toHaveLength(ids.length);
    expect(ids.every((id) => id !== "" && !id.includes(":"))).toBe(true);
    for (const artwork of host.querySelectorAll("svg")) {
      for (const window of artwork.querySelectorAll<SVGGElement>("g[clip-path]")) {
        const clipId = window.getAttribute("clip-path")
          ?.match(/^url\(#(.+)\)$/)?.[1];
        expect(clipId).toBeDefined();
        expect(artwork.querySelectorAll(`clipPath[id="${clipId}"]`))
          .toHaveLength(1);
      }
    }
  });

  it("moves the chain once, only downward, within the final-size budget", () => {
    const track = trackFor("pull-chain", "working");
    const translations = track.keyframes.map(translationFor);
    const positiveFrames = track.keyframes.filter((frame) => (
      translationFor(frame).y > 0
    ));

    expect(track.keyframes.every((frame) => (
      /^translateY\([\d.]+px\)$/.test(String(frame.transform))
    ))).toBe(true);
    expect(translations.every(({ x, y }) => x === 0 && y >= 0)).toBe(true);
    expect(Math.max(...translations.map(({ y }) => y))).toBeGreaterThan(0);
    expect(Math.max(...translations.map(({ y }) => y))).toBeLessThanOrEqual(24);
    expect(positiveFrames.map((frame) => frame.offset))
      .toEqual([0.16, 0.2, 0.28]);
  });

  it("starts one short damped tassel response after the tug", () => {
    const chain = trackFor("pull-chain", "working");
    const tassels = trackFor("tassels", "working");
    const nonzero = tassels.keyframes
      .map(rotationFor)
      .filter((rotation) => rotation !== 0);

    expect(firstChangedOffset(tassels)).toBeGreaterThan(firstChangedOffset(chain)!);
    expect(nonzero).toEqual([4, -2, 1]);
    expect(nonzero.map(Math.abs)).toEqual([4, 2, 1]);
    expect(Math.max(...nonzero.map(Math.abs))).toBeLessThanOrEqual(6);
    expect(tassels.keyframes.find((frame) => frame.offset === 0.38))
      ?.toMatchObject({ transform: "rotate(0deg)" });
  });

  it("holds the light dark through the chain peak before illumination begins", () => {
    const chain = trackFor("pull-chain", "working");
    const light = trackFor("shade-light", "working");
    const peak = Math.max(...chain.keyframes.map((frame) => (
      translationFor(frame).y
    )));
    const chainPeakHoldEnd = Math.max(...chain.keyframes
      .filter((frame) => translationFor(frame).y === peak)
      .map((frame) => Number(frame.offset)));
    const firstPositiveIndex = light.keyframes.findIndex((frame) => (
      Number(frame.opacity) > 0
    ));
    const heldZero = light.keyframes[firstPositiveIndex - 1];
    const firstPositive = light.keyframes[firstPositiveIndex];

    expect(heldZero?.opacity).toBe(0);
    expect(Number(heldZero?.offset)).toBeGreaterThanOrEqual(chainPeakHoldEnd);
    expect(Number(firstPositive?.offset)).toBeGreaterThan(chainPeakHoldEnd);
  });

  it("keeps waiting light steady while only one guide moves slowly", () => {
    const light = trackFor("shade-light", "waiting");
    const guide = trackFor("guide-active-vertical", "waiting");
    const guideTranslations = guide.keyframes.map(translationFor);

    expect(light.keyframes.every((frame) => (
      frame.opacity === 0.68 && frame.transform === undefined
    ))).toBe(true);
    expect(guide.keyframes.every((frame) => (
      /^translateY\([\d.]+px\)$/.test(String(frame.transform))
    ))).toBe(true);
    expect(Math.max(...guideTranslations.map(({ y }) => y))).toBe(12);
    expect(Math.min(...guideTranslations.map(({ y }) => y))).toBe(0);
  });

  it("uses canonical held seams, transform/opacity keyframes, and explicit origins", () => {
    const { container } = render(<PropDesignerAnimation motionState="working" />);
    const tracks = [
      ...PROP_DESIGNER_MOTION_PROGRAM.working,
      ...PROP_DESIGNER_MOTION_PROGRAM.waiting,
    ];

    for (const track of tracks) {
      const first = track.keyframes[0];
      const second = track.keyframes[1];
      const penultimate = track.keyframes.at(-2)!;
      const last = track.keyframes.at(-1)!;

      expect(first.offset).toBe(0);
      expect(last.offset).toBe(1);
      expect(canonicalValue(last, "transform"))
        .toBe(canonicalValue(first, "transform"));
      expect(canonicalValue(last, "opacity"))
        .toBe(canonicalValue(first, "opacity"));
      expect(canonicalValue(second, "transform"))
        .toBe(canonicalValue(first, "transform"));
      expect(canonicalValue(second, "opacity"))
        .toBe(canonicalValue(first, "opacity"));
      expect(canonicalValue(penultimate, "transform"))
        .toBe(canonicalValue(last, "transform"));
      expect(canonicalValue(penultimate, "opacity"))
        .toBe(canonicalValue(last, "opacity"));
      expect(Number(second.offset) - Number(first.offset)).toBeGreaterThan(0);
      expect(Number(last.offset) - Number(penultimate.offset)).toBeGreaterThan(0);
      expect(track.keyframes.flatMap(Object.keys).every((property) => (
        property === "transform"
        || property === "opacity"
        || property === "offset"
      ))).toBe(true);

      for (const frame of track.keyframes) {
        const transform = String(frame.transform ?? "none");
        const translation = transform.match(
          /translate[XY]\((-?[\d.]+)px\)/,
        );
        const rotation = transform.match(/rotate\((-?[\d.]+)deg\)/);
        if (translation) {
          expect(Math.abs(Number(translation[1]))).toBeLessThanOrEqual(24);
        }
        if (rotation) {
          expect(Math.abs(Number(rotation[1]))).toBeLessThanOrEqual(6);
        }
      }

      const target = container.querySelector<SVGGraphicsElement>(
        `[data-part="${track.part}"]`,
      );
      expect(target, `missing moving target ${track.part}`).not.toBeNull();
      expect(target?.style.transformBox).toBe("fill-box");
      expect(target?.style.transformOrigin).not.toBe("");
    }
  });

  it("connects the root, state, and exported program to the shared lifecycle", () => {
    const { container } = render(<PropDesignerAnimation motionState="waiting" />);
    expect(useAgentRoleMotion).toHaveBeenCalledOnce();

    const [rootRef, motionState, program] = vi.mocked(useAgentRoleMotion)
      .mock.calls[0];
    expect(rootRef.current).toBe(container.querySelector("svg"));
    expect(motionState).toBe("waiting");
    expect(program).toBe(PROP_DESIGNER_MOTION_PROGRAM);
  });
});
