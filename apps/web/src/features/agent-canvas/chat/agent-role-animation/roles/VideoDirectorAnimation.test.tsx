import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";
import VideoDirectorAnimation, {
  VIDEO_DIRECTOR_MOTION_PROGRAM,
} from "./VideoDirectorAnimation.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

const REQUIRED_PARTS = [
  "base",
  "left-reel",
  "right-reel",
  "lens",
  "focus-brackets",
  "record-indicator",
  "directing-pen",
  "directing-path",
] as const;

const FOCUS_PARTS = [
  "focus-bracket-top-left",
  "focus-bracket-top-right",
  "focus-bracket-bottom-left",
  "focus-bracket-bottom-right",
] as const;

const INTERVAL_EASING = "cubic-bezier(0.77, 0, 0.175, 1)";

interface Point {
  x: number;
  y: number;
}

interface Pose {
  translation: Point;
  rotation: number;
}

function trackFor(
  part: string,
  phase: "working" | "waiting",
): AgentRoleMotionTrack {
  const track = VIDEO_DIRECTOR_MOTION_PROGRAM[phase]
    .find((candidate) => candidate.part === part);
  expect(track, `missing ${phase} track for ${part}`).toBeDefined();
  return track!;
}

function poseFor(frame: Keyframe): Pose {
  const transform = String(frame.transform ?? "none");
  if (transform === "none") {
    return { translation: { x: 0, y: 0 }, rotation: 0 };
  }
  const translation = transform.match(
    /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/,
  );
  const rotation = transform.match(/rotate\((-?[\d.]+)deg\)/);
  const rotateOnly = transform.match(/^rotate\((-?[\d.]+)deg\)$/);
  if (rotateOnly) {
    return {
      translation: { x: 0, y: 0 },
      rotation: Number(rotateOnly[1]),
    };
  }
  if (!translation) throw new Error(`unexpected transform ${transform}`);
  return {
    translation: {
      x: Number(translation[1]),
      y: Number(translation[2]),
    },
    rotation: Number(rotation?.[1] ?? 0),
  };
}

function canonicalPose(frame: Keyframe): string {
  return `${String(frame.transform ?? "none")}|${String(frame.opacity ?? 1)}`;
}

function underlyingPose(element: SVGGraphicsElement): string {
  const computed = getComputedStyle(element);
  const authoredTransform = element.style.transform
    || element.getAttribute("transform");
  const transform = authoredTransform
    || (computed.transform && computed.transform !== "none"
      ? computed.transform
      : "none");
  const authoredOpacity = element.style.opacity || element.getAttribute("opacity");
  const opacity = authoredOpacity || computed.opacity || "1";
  return `${transform}|${opacity}`;
}

function hasPositiveHold(track: AgentRoleMotionTrack, index: number): boolean {
  const frames = track.keyframes;
  const pose = canonicalPose(frames[index]);
  return (index > 0
      && Number(frames[index].offset) > Number(frames[index - 1].offset)
      && canonicalPose(frames[index - 1]) === pose)
    || (index < frames.length - 1
      && Number(frames[index + 1].offset) > Number(frames[index].offset)
      && canonicalPose(frames[index + 1]) === pose);
}

function expectCanonicalHeldLoop(track: AgentRoleMotionTrack): void {
  expect(track.keyframes[0].offset).toBe(0);
  expect(track.keyframes.at(-1)?.offset).toBe(1);
  expect(canonicalPose(track.keyframes.at(-1)!))
    .toBe(canonicalPose(track.keyframes[0]));
  expect(hasPositiveHold(track, 0)).toBe(true);
  expect(hasPositiveHold(track, track.keyframes.length - 1)).toBe(true);
  const poses = track.keyframes.map(canonicalPose);
  const noncanonicalIndices = poses.flatMap((pose, index) => (
    pose !== poses[0] ? [index] : []
  ));
  expect(noncanonicalIndices.length).toBeGreaterThan(0);
  expect(noncanonicalIndices.some((index) => hasPositiveHold(track, index)))
    .toBe(true);
}

function numericAttribute(element: Element, attribute: string): number {
  const value = Number(element.getAttribute(attribute));
  expect(Number.isFinite(value), `${attribute} on ${element.outerHTML}`).toBe(true);
  return value;
}

function reelCenter(reel: SVGGElement): Point {
  const rim = reel.querySelector<SVGCircleElement>("[data-reel-rim]")!;
  return {
    x: numericAttribute(rim, "cx"),
    y: numericAttribute(rim, "cy"),
  };
}

function rotatePoint(point: Point, center: Point, angle: number): Point {
  const radians = angle * Math.PI / 180;
  const local = { x: point.x - center.x, y: point.y - center.y };
  return {
    x: center.x + local.x * Math.cos(radians) - local.y * Math.sin(radians),
    y: center.y + local.x * Math.sin(radians) + local.y * Math.cos(radians),
  };
}

function reelInkPoints(reel: SVGGElement): Point[] {
  const spokePoints = [...reel.querySelectorAll<SVGLineElement>(
    "[data-reel-spoke]",
  )].flatMap((spoke) => {
    expect(spoke.getAttribute("stroke")).not.toBe("none");
    expect(numericAttribute(spoke, "stroke-width")).toBeGreaterThan(0);
    return [
      {
        x: numericAttribute(spoke, "x1"),
        y: numericAttribute(spoke, "y1"),
      },
      {
        x: numericAttribute(spoke, "x2"),
        y: numericAttribute(spoke, "y2"),
      },
    ];
  });
  const marker = reel.querySelector<SVGCircleElement>("[data-reel-marker]")!;
  expect(marker.getAttribute("fill")).not.toBe("none");
  const markerCenter = {
    x: numericAttribute(marker, "cx"),
    y: numericAttribute(marker, "cy"),
  };
  const markerRadius = numericAttribute(marker, "r");
  const markerBoundary = [
    { x: markerCenter.x - markerRadius, y: markerCenter.y },
    { x: markerCenter.x + markerRadius, y: markerCenter.y },
    { x: markerCenter.x, y: markerCenter.y - markerRadius },
    { x: markerCenter.x, y: markerCenter.y + markerRadius },
  ];
  return [...spokePoints, ...markerBoundary];
}

function polylinePoints(
  polyline: SVGPolylineElement | SVGPolygonElement,
): Point[] {
  const values = polyline.getAttribute("points")?.match(/-?[\d.]+/g)?.map(Number)
    ?? [];
  expect(values.length).toBeGreaterThanOrEqual(4);
  expect(values.length % 2).toBe(0);
  return Array.from({ length: values.length / 2 }, (_, index) => ({
    x: values[index * 2],
    y: values[index * 2 + 1],
  }));
}

function distanceToSegment(point: Point, start: Point, end: Point): number {
  const delta = { x: end.x - start.x, y: end.y - start.y };
  const lengthSquared = delta.x ** 2 + delta.y ** 2;
  const progress = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1,
    ((point.x - start.x) * delta.x + (point.y - start.y) * delta.y)
      / lengthSquared,
  ));
  return Math.hypot(
    point.x - (start.x + progress * delta.x),
    point.y - (start.y + progress * delta.y),
  );
}

function distanceToRoute(point: Point, route: Point[]): number {
  return Math.min(...route.slice(1).map((end, index) => (
    distanceToSegment(point, route[index], end)
  )));
}

describe("VideoDirectorAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it.each(["idle", "working", "waiting"] as const)(
    "omits the upper vertical dashed decoration in %s state",
    (motionState) => {
      const { container } = render(
        <VideoDirectorAnimation motionState={motionState} />,
      );
      expect(container.querySelector('[data-part="base"] > line[stroke-dasharray]'))
        .toBeNull();
      expect(container.querySelector('[data-directing-route][stroke-dasharray]'))
        .not.toBeNull();
    },
  );

  it("renders a hand-built, layered camera matching the semantic contract", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="idle" />,
    );
    const artwork = assertRoleArtworkContract(
      container,
      "video-director",
      REQUIRED_PARTS,
    );

    expect(artwork.querySelectorAll("image")).toHaveLength(0);
    expect(artwork.querySelector('[data-part="base"] [data-camera-body]'))
      .not.toBeNull();
    expect(artwork.querySelector('[data-part="lens"] [data-lens-aperture]'))
      .not.toBeNull();
    const aperture = artwork.querySelector('[data-lens-aperture]')!;
    expect(aperture.tagName.toLowerCase()).toBe("polygon");
    expect(polylinePoints(aperture as SVGPolygonElement)).toHaveLength(4);
    expect(artwork.querySelectorAll('[data-part="focus-brackets"] > [data-part]'))
      .toHaveLength(4);
    expect(artwork.querySelector('[data-part="record-indicator"] [data-part="record-dot"]'))
      .not.toBeNull();
    expect(artwork.querySelector('[data-part="directing-path"] [data-directing-route]'))
      .not.toBeNull();
  });

  it("uses exact periods, unique targets, allowed properties, and the shared hook", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;

    expect(VIDEO_DIRECTOR_MOTION_PROGRAM.working.map(({ part }) => part))
      .toEqual([
        "left-reel",
        "right-reel",
        ...FOCUS_PARTS,
        "lens-focus-pass",
        "record-dot",
        "directing-pen",
      ]);
    for (const part of ["left-reel", "right-reel"]) {
      expect(trackFor(part, "working").options.duration).toBe(1_600);
    }
    expect(trackFor("directing-pen", "working").options.duration).toBe(2_800);
    for (const part of [...FOCUS_PARTS, "lens-focus-pass", "record-dot"]) {
      expect(trackFor(part, "working").options.duration).toBe(5_600);
    }
    expect(VIDEO_DIRECTOR_MOTION_PROGRAM.workingEntryTimeMs).toBe(16);

    expect(VIDEO_DIRECTOR_MOTION_PROGRAM.waiting.map(({ part }) => part))
      .toEqual(["left-reel", "right-reel", "record-dot"]);
    expect(VIDEO_DIRECTOR_MOTION_PROGRAM.waiting.every(
      ({ options }) => options.duration === 4_800,
    )).toBe(true);

    for (const phase of ["working", "waiting"] as const) {
      const tracks = VIDEO_DIRECTOR_MOTION_PROGRAM[phase];
      expect(tracks.map(({ part }) => part))
        .toHaveLength(new Set(tracks.map(({ part }) => part)).size);
      expect(tracks.every(({ options }) => (
        options.iterations === Infinity && options.easing === "linear"
      ))).toBe(true);
      expect(tracks.every(({ keyframes }) => keyframes.every((frame) => (
        Object.keys(frame).every((property) => (
          property === "offset"
          || property === "easing"
          || property === "opacity"
          || property === "transform"
        ))
      )))).toBe(true);
    }

    expect(useAgentRoleMotion).toHaveBeenCalledOnce();
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: artwork }),
      "working",
      VIDEO_DIRECTOR_MOTION_PROGRAM,
    );
  });

  it("eases every changing interval locally while preserving the shared linear clock", () => {
    const easingControlPoints = INTERVAL_EASING.match(/[\d.]+/g)?.map(Number);
    expect(easingControlPoints).toEqual([0.77, 0, 0.175, 1]);
    const startVelocity = 3 * easingControlPoints![1];
    const endVelocity = 3 * (1 - easingControlPoints![3]);
    expect(startVelocity).toBe(0);
    expect(endVelocity).toBe(0);

    for (const phase of ["working", "waiting"] as const) {
      for (const track of VIDEO_DIRECTOR_MOTION_PROGRAM[phase]) {
        expect(track.options.easing).toBe("linear");
        if (track.part === "left-reel" || track.part === "right-reel") {
          expect(track.keyframes.every((frame) => frame.easing === undefined))
            .toBe(true);
          continue;
        }
        for (let index = 0; index < track.keyframes.length - 1; index += 1) {
          const current = track.keyframes[index];
          const next = track.keyframes[index + 1];
          const changesPose = canonicalPose(current) !== canonicalPose(next);
          if (changesPose) {
            expect(
              current.easing,
              `${phase}/${track.part} interval ${String(current.offset)}-${String(next.offset)}`,
            ).toBe(INTERVAL_EASING);
          }
        }
      }
    }
  });

  it("rotates asymmetric reel ink in continuous full turns at the faster working rate", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const signedPeaks: number[] = [];

    for (const part of ["left-reel", "right-reel"] as const) {
      const reel = artwork.querySelector<SVGGElement>(`[data-part="${part}"]`)!;
      const center = reelCenter(reel);
      expect(reel.style.transformBox).toBe("fill-box");
      expect(reel.style.transformOrigin).toBe("center");
      expect(Number(reel.dataset.reelCenterX)).toBe(center.x);
      expect(Number(reel.dataset.reelCenterY)).toBe(center.y);
      expect(reel.querySelectorAll("[data-reel-spoke]").length)
        .toBeGreaterThanOrEqual(3);
      const marker = reel.querySelector<SVGElement>("[data-reel-marker]")!;
      expect(marker.getAttribute("fill")).toBe("#FFB323");

      const track = trackFor(part, "working");
      const rotations = track.keyframes.map((frame) => poseFor(frame).rotation);
      const fullTurn = rotations.at(-1)!;
      signedPeaks.push(fullTurn);
      expect(rotations).toEqual([0, part === "left-reel" ? -360 : 360]);
      expect(track.keyframes).toEqual([
        { offset: 0, transform: "rotate(0deg)" },
        { offset: 1, transform: `rotate(${String(fullTurn)}deg)` },
      ]);
      expect(track.options.duration).toBe(1_600);

      const inkTravel = reelInkPoints(reel).map((point) => {
        const transformed = rotatePoint(point, center, fullTurn / 4);
        return Math.hypot(
          transformed.x - point.x,
          transformed.y - point.y,
        );
      });
      expect(Math.min(...inkTravel)).toBeGreaterThanOrEqual(18);
      expect(Math.max(...inkTravel)).toBeGreaterThanOrEqual(46);
    }

    expect(Math.sign(signedPeaks[0])).toBe(-Math.sign(signedPeaks[1]));

    for (const [part, end] of [
      ["left-reel", -360],
      ["right-reel", 360],
    ] as const) {
      const waiting = trackFor(part, "waiting");
      expect(waiting.keyframes).toEqual([
        { offset: 0, transform: "rotate(0deg)" },
        { offset: 1, transform: `rotate(${String(end)}deg)` },
      ]);
      expect(waiting.options.duration).toBe(4_800);
    }
  });

  it("keeps the camera, lens housing, path, and semantic containers fixed", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const targets = new Set([
      ...VIDEO_DIRECTOR_MOTION_PROGRAM.working,
      ...VIDEO_DIRECTOR_MOTION_PROGRAM.waiting,
    ].map(({ part }) => part));

    for (const fixedPart of [
      "base",
      "lens",
      "focus-brackets",
      "record-indicator",
      "directing-path",
    ]) {
      expect(targets.has(fixedPart), `${fixedPart} must stay fixed`).toBe(false);
      const element = artwork.querySelector(`[data-part="${fixedPart}"]`)!;
      expect(element.getAttribute("transform")).toBeNull();
      expect(element.getAttribute("style")).toBeNull();
    }

    const focusPass = trackFor("lens-focus-pass", "working");
    expect(focusPass.keyframes.every((frame) => frame.transform === undefined))
      .toBe(true);
  });

  it("converges four brackets symmetrically toward the rendered lens without crossing", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const aperture = artwork.querySelector<SVGPolygonElement>(
      '[data-part="lens"] [data-lens-aperture]',
    )!;
    const aperturePoints = polylinePoints(aperture);
    const apertureXs = aperturePoints.map(({ x }) => x);
    const apertureYs = aperturePoints.map(({ y }) => y);
    const lensCenter = {
      x: (Math.min(...apertureXs) + Math.max(...apertureXs)) / 2,
      y: (Math.min(...apertureYs) + Math.max(...apertureYs)) / 2,
    };
    const peakTranslations = new Map<string, Point>();

    for (const part of FOCUS_PARTS) {
      const bracket = artwork.querySelector<SVGGElement>(
        `[data-part="${part}"]`,
      )!;
      const start = {
        x: Number(bracket.dataset.focusAnchorX),
        y: Number(bracket.dataset.focusAnchorY),
      };
      const track = trackFor(part, "working");
      const poses = track.keyframes.map(poseFor);
      const peak = poses.reduce((best, pose) => (
        Math.hypot(pose.translation.x, pose.translation.y)
          > Math.hypot(best.translation.x, best.translation.y)
          ? pose
          : best
      ), poses[0]);
      peakTranslations.set(part, peak.translation);

      expect(bracket.style.transformBox).toBe("view-box");
      expect(bracket.style.transformOrigin)
        .toBe(`${start.x}px ${start.y}px`);
      expect(poses[0].translation).toEqual({ x: 0, y: 0 });
      expect(Math.hypot(peak.translation.x, peak.translation.y))
        .toBeLessThanOrEqual(24);
      expect(Math.abs(peak.rotation)).toBe(0);

      const end = {
        x: start.x + peak.translation.x,
        y: start.y + peak.translation.y,
      };
      expect(Math.hypot(end.x - lensCenter.x, end.y - lensCenter.y))
        .toBeLessThan(Math.hypot(start.x - lensCenter.x, start.y - lensCenter.y));
      expect(Math.sign(end.x - lensCenter.x))
        .toBe(Math.sign(start.x - lensCenter.x));
      expect(Math.sign(end.y - lensCenter.y))
        .toBe(Math.sign(start.y - lensCenter.y));
    }

    expect(peakTranslations.get("focus-bracket-top-left"))
      .toEqual({ x: 12, y: 8 });
    expect(peakTranslations.get("focus-bracket-bottom-right"))
      .toEqual({ x: -12, y: -8 });
    expect(peakTranslations.get("focus-bracket-top-right"))
      .toEqual({ x: -12, y: 8 });
    expect(peakTranslations.get("focus-bracket-bottom-left"))
      .toEqual({ x: 12, y: -8 });
  });

  it("pulses only the local orange record dot in working and waiting", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="waiting" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const indicator = artwork.querySelector<SVGGElement>(
      '[data-part="record-indicator"]',
    )!;
    const dot = indicator.querySelector<SVGCircleElement>(
      '[data-part="record-dot"] circle',
    )!;

    expect(dot.getAttribute("fill")).toBe("#FFB323");
    expect(indicator.querySelector("[data-record-housing]")).not.toBeNull();
    for (const phase of ["working", "waiting"] as const) {
      const track = trackFor("record-dot", phase);
      expect(track.keyframes.every((frame) => frame.transform === undefined))
        .toBe(true);
      expect(new Set(track.keyframes.map((frame) => frame.opacity)).size)
        .toBeGreaterThan(1);
    }
    expect(VIDEO_DIRECTOR_MOTION_PROGRAM.waiting.map(({ part }) => part))
      .not.toContain("record-indicator");
  });

  it("moves the pen tip on the rendered dotted route within translation and angle budgets", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const routeElement = artwork.querySelector<SVGPolylineElement>(
      '[data-part="directing-path"] [data-directing-route]',
    )!;
    const route = polylinePoints(routeElement);
    const pen = artwork.querySelector<SVGGElement>(
      '[data-part="directing-pen"]',
    )!;
    const penTip = {
      x: Number(pen.dataset.penTipX),
      y: Number(pen.dataset.penTipY),
    };
    const track = trackFor("directing-pen", "working");

    expect(routeElement.getAttribute("stroke-dasharray")).not.toBeNull();
    expect(pen.style.transformBox).toBe("view-box");
    expect(pen.style.transformOrigin).toBe(`${penTip.x}px ${penTip.y}px`);
    expect(distanceToRoute(penTip, route)).toBeLessThanOrEqual(0.001);
    for (const frame of track.keyframes) {
      const pose = poseFor(frame);
      const transformedTip = {
        x: penTip.x + pose.translation.x,
        y: penTip.y + pose.translation.y,
      };
      expect(distanceToRoute(transformedTip, route)).toBeLessThanOrEqual(0.001);
      expect(Math.hypot(pose.translation.x, pose.translation.y))
        .toBeLessThanOrEqual(24);
      expect(Math.abs(pose.rotation)).toBeLessThanOrEqual(6);
    }
    expect(track.keyframes.some((frame) => (
      Math.hypot(
        poseFor(frame).translation.x,
        poseFor(frame).translation.y,
      ) > 0
    ))).toBe(true);
  });

  it("keeps full-turn reel seams continuous and holds other turnarounds", () => {
    for (const phase of ["working", "waiting"] as const) {
      for (const track of VIDEO_DIRECTOR_MOTION_PROGRAM[phase]) {
        if (track.part === "left-reel" || track.part === "right-reel") {
          expect(track.keyframes[0]).toEqual({
            offset: 0,
            transform: "rotate(0deg)",
          });
          expect(track.keyframes.at(-1)?.transform)
            .toMatch(/^rotate\(-?360deg\)$/);
          continue;
        }
        expectCanonicalHeldLoop(track);
      }
    }
  });

  it("anchors both endpoints of every track to its rendered underlying pose", () => {
    const { container } = render(
      <VideoDirectorAnimation motionState="idle" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;

    for (const phase of ["working", "waiting"] as const) {
      for (const track of VIDEO_DIRECTOR_MOTION_PROGRAM[phase]) {
        const target = artwork.querySelector<SVGGraphicsElement>(
          `[data-part="${track.part}"]`,
        );
        expect(target, `missing rendered target ${track.part}`).not.toBeNull();
        if (track.part === "left-reel" || track.part === "right-reel") {
          expect(track.keyframes[0].transform).toBe("rotate(0deg)");
          expect(track.keyframes.at(-1)?.transform)
            .toMatch(/^rotate\(-?360deg\)$/);
          expect(track.keyframes.every((frame) => frame.opacity === undefined))
            .toBe(true);
          continue;
        }
        const underlying = underlyingPose(target!);
        expect(
          canonicalPose(track.keyframes[0]),
          `${phase}/${track.part} first endpoint`,
        ).toBe(underlying);
        expect(
          canonicalPose(track.keyframes.at(-1)!),
          `${phase}/${track.part} last endpoint`,
        ).toBe(underlying);
      }
    }
  });
});
