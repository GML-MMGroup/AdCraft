import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentRoleMotionTrack } from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { assertRoleArtworkContract } from "./roleArtworkTestUtils.tsx";
import StoryboardArtistAnimation, {
  STORYBOARD_ARTIST_MOTION_PROGRAM,
} from "./StoryboardArtistAnimation.tsx";

vi.mock("../useAgentRoleMotion.ts", () => ({
  useAgentRoleMotion: vi.fn(),
}));

const REQUIRED_PARTS = [
  "base",
  "panel-sequence",
  "center-panel",
  "pose-advance",
] as const;

const PANEL_IDS = Array.from(
  { length: 9 },
  (_, index) => `panel-${index + 1}`,
);
const PANEL_EMPHASIS_PARTS = PANEL_IDS.map((panelId) => (
  `${panelId}-emphasis`
));
const ACTION_PANEL_IDS = ["panel-2", "panel-3", "panel-6", "panel-9"] as const;
const BASE_ACTION_PARTS = ACTION_PANEL_IDS.map((panelId) => (
  `${panelId}-action-stroke`
));
const ACTIVE_ACTION_PARTS = ACTION_PANEL_IDS.map((panelId) => (
  `${panelId}-active-action-stroke`
));
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
  const track = STORYBOARD_ARTIST_MOTION_PROGRAM[phase]
    .find((candidate) => candidate.part === part);
  expect(track, `missing ${phase} track for ${part}`).toBeDefined();
  return track!;
}

function opacityAt(track: AgentRoleMotionTrack, progress: number): number {
  const frames = track.keyframes;
  const exact = frames.findLast((frame) => Number(frame.offset) === progress);
  if (exact) return Number(exact.opacity ?? 1);
  const nextIndex = frames.findIndex((frame) => Number(frame.offset) > progress);
  if (nextIndex <= 0) return Number(frames[0].opacity ?? 1);
  const previous = frames[nextIndex - 1];
  const next = frames[nextIndex];
  const localProgress = (progress - Number(previous.offset))
    / (Number(next.offset) - Number(previous.offset));
  return Number(previous.opacity ?? 1)
    + (Number(next.opacity ?? 1) - Number(previous.opacity ?? 1))
      * localProgress;
}

function translationFromGroup(group: Element): Point {
  const match = group.getAttribute("transform")
    ?.match(/^translate\((-?[\d.]+)\s+(-?[\d.]+)\)$/);
  if (!match) throw new Error(`unexpected group transform ${group.outerHTML}`);
  return { x: Number(match[1]), y: Number(match[2]) };
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
  if (!translation || !rotation) {
    throw new Error(`unexpected action transform ${transform}`);
  }
  return {
    translation: { x: Number(translation[1]), y: Number(translation[2]) },
    rotation: Number(rotation[1]),
  };
}

function normalizedGeometry(value: string): string {
  return (value.match(/[A-Za-z]|-?[\d.]+/g) ?? []).map((token) => (
    /^[A-Za-z]$/.test(token) ? token : String(Number(token))
  )).join(",");
}

function primitiveGeometrySignature(element: Element): string {
  const attributes = [
    "d",
    "points",
    "x",
    "y",
    "width",
    "height",
    "rx",
    "ry",
    "cx",
    "cy",
    "r",
    "x1",
    "y1",
    "x2",
    "y2",
  ];
  return [
    element.tagName.toLowerCase(),
    ...attributes.flatMap((attribute) => {
      const value = element.getAttribute(attribute);
      return value === null ? [] : [`${attribute}:${normalizedGeometry(value)}`];
    }),
  ].join("|");
}

function contentGeometrySignature(content: Element): string {
  return [...content.querySelectorAll(
    "circle, ellipse, line, path, polygon, polyline, rect",
  )].map(primitiveGeometrySignature).join(";");
}

function poseSignature(frame: Keyframe): string {
  return `${String(frame.transform ?? "none")}|${String(frame.opacity ?? 1)}`;
}

function hasPositiveHoldAt(track: AgentRoleMotionTrack, index: number): boolean {
  const frames = track.keyframes;
  const pose = poseSignature(frames[index]);
  return (index > 0
      && Number(frames[index].offset) > Number(frames[index - 1].offset)
      && poseSignature(frames[index - 1]) === pose)
    || (index < frames.length - 1
      && Number(frames[index + 1].offset) > Number(frames[index].offset)
      && poseSignature(frames[index + 1]) === pose);
}

function expectCanonicalLoop(track: AgentRoleMotionTrack): void {
  const first = track.keyframes[0];
  const last = track.keyframes.at(-1)!;
  expect(first.offset).toBe(0);
  expect(last.offset).toBe(1);
  expect(poseSignature(last)).toBe(poseSignature(first));
  expect(hasPositiveHoldAt(track, 0)).toBe(true);
  expect(hasPositiveHoldAt(track, track.keyframes.length - 1)).toBe(true);

  const peakOpacity = Math.max(...track.keyframes.map((frame) => (
    Number(frame.opacity ?? 1)
  )));
  const translatedDistance = (frame: Keyframe): number => {
    const { translation } = poseFor(frame);
    return Math.hypot(translation.x, translation.y);
  };
  const peakTravel = Math.max(...track.keyframes.map(translatedDistance));
  const peakIndices = track.keyframes.flatMap((frame, index) => (
    Number(frame.opacity ?? 1) === peakOpacity
      && Math.abs(translatedDistance(frame) - peakTravel) < 0.000_001
      ? [index]
      : []
  ));
  expect(peakIndices.some((index) => hasPositiveHoldAt(track, index))).toBe(true);
}

describe("StoryboardArtistAnimation", () => {
  beforeEach(() => {
    vi.mocked(useAgentRoleMotion).mockClear();
  });

  it("renders a fixed three-by-three board with nine distinct stories", () => {
    const { container } = render(
      <StoryboardArtistAnimation motionState="idle" />,
    );
    const artwork = assertRoleArtworkContract(
      container,
      "storyboard-artist",
      REQUIRED_PARTS,
    );
    const cells = [...artwork.querySelectorAll<SVGGElement>(
      '[data-part="base"] > [data-panel-cell]',
    )];
    const contents = [...artwork.querySelectorAll<SVGGElement>(
      "[data-panel-content]",
    )];

    expect(artwork.querySelectorAll("image")).toHaveLength(0);
    expect(cells).toHaveLength(9);
    expect(contents).toHaveLength(9);
    expect(new Set(cells.map((cell) => cell.dataset.panelCell)).size).toBe(9);
    expect(new Set(contents.map((content) => content.dataset.panelContent)).size)
      .toBe(9);
    expect(new Set(contents.map((content) => content.dataset.contentKind)).size)
      .toBe(9);
    const geometrySignatures = contents.map(contentGeometrySignature);
    expect(geometrySignatures.every((signature) => signature.length > 0))
      .toBe(true);
    expect(new Set(geometrySignatures).size).toBe(9);
    expect(contents.every((content) => (
      content.querySelectorAll("path, line, circle, polyline, rect").length > 0
    ))).toBe(true);

    const positions = cells.map(translationFromGroup);
    const xs = [...new Set(positions.map(({ x }) => x))].sort((a, b) => a - b);
    const ys = [...new Set(positions.map(({ y }) => y))].sort((a, b) => a - b);
    expect(xs).toHaveLength(3);
    expect(ys).toHaveLength(3);
    expect(xs[1] - xs[0]).toBe(xs[2] - xs[1]);
    expect(ys[1] - ys[0]).toBe(ys[2] - ys[1]);
    expect(new Set(positions.map(({ x, y }) => `${x},${y}`)).size).toBe(9);

    const frames = cells.map((cell) => (
      cell.querySelector<SVGRectElement>("[data-panel-frame]")!
    ));
    expect(new Set(frames.map((frame) => [
      frame.getAttribute("x"),
      frame.getAttribute("y"),
      frame.getAttribute("width"),
      frame.getAttribute("height"),
    ].join(","))).size).toBe(1);
    expect(artwork.querySelector('[data-panel-cell="panel-5"] [data-part="center-panel"]'))
      .not.toBeNull();
  });

  it("layers exact yellow active content over blue base content in every reading-order panel", () => {
    const { container } = render(
      <StoryboardArtistAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;

    for (const panelId of PANEL_IDS) {
      const cell = artwork.querySelector<SVGGElement>(
        `[data-panel-cell="${panelId}"]`,
      )!;
      const baseContent = cell.querySelector<SVGGElement>(
        `[data-panel-content="${panelId}"]`,
      )!;
      const emphasis = artwork.querySelector<SVGGElement>(
        `[data-part="${panelId}-emphasis"]`,
      )!;
      const activeContent = emphasis.querySelector<SVGGElement>(
        `[data-active-panel-content="${panelId}"]`,
      )!;
      const baseFrame = cell.querySelector<SVGRectElement>("[data-panel-frame]")!;
      const activeFrame = emphasis.querySelector<SVGRectElement>(
        "[data-active-panel-frame]",
      )!;
      expect(baseContent, `missing base content for ${panelId}`).not.toBeNull();
      expect(activeContent, `missing active content for ${panelId}`).not.toBeNull();
      expect(activeFrame, `missing active frame for ${panelId}`).not.toBeNull();
      if (!baseContent || !activeContent || !activeFrame) return;
      const basePaint = [...baseContent.querySelectorAll("[fill], [stroke]")]
        .flatMap((element) => [element.getAttribute("fill"), element.getAttribute("stroke")])
        .filter((value): value is string => value !== null);
      const activePaint = [...activeContent.querySelectorAll("[fill], [stroke]")]
        .flatMap((element) => [element.getAttribute("fill"), element.getAttribute("stroke")])
        .filter((value): value is string => value !== null);

      expect(contentGeometrySignature(activeContent))
        .toBe(contentGeometrySignature(baseContent));
      expect(basePaint).not.toHaveLength(0);
      expect(activePaint).not.toHaveLength(0);
      expect(basePaint.every((paint) => paint === "#7899E2" || paint === "none"))
        .toBe(true);
      expect(activePaint.every((paint) => paint === "#FFB323" || paint === "none"))
        .toBe(true);
      for (const attribute of ["x", "y", "width", "height", "rx", "stroke-width"]) {
        expect(activeFrame.getAttribute(attribute)).toBe(baseFrame.getAttribute(attribute));
      }
      expect(activeFrame.getAttribute("fill")).toBe("none");
      expect(activeFrame.getAttribute("stroke")).toBe("#FFB323");
    }
  });

  it("uses exact periods, targets, properties, and the shared runtime hook", () => {
    const { container } = render(
      <StoryboardArtistAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const workingParts = STORYBOARD_ARTIST_MOTION_PROGRAM.working
      .map(({ part }) => part);

    expect(workingParts).toEqual([
      ...PANEL_EMPHASIS_PARTS,
      ...BASE_ACTION_PARTS,
      ...ACTIVE_ACTION_PARTS,
    ]);
    expect([...PANEL_EMPHASIS_PARTS, ...BASE_ACTION_PARTS, ...ACTIVE_ACTION_PARTS].map((part) => (
      trackFor(part, "working").options.duration
    ))).toEqual([...PANEL_EMPHASIS_PARTS, ...BASE_ACTION_PARTS, ...ACTIVE_ACTION_PARTS]
      .map(() => 3_600));
    expect(STORYBOARD_ARTIST_MOTION_PROGRAM.waiting).toEqual([]);

    for (const phase of ["working", "waiting"] as const) {
      const tracks = STORYBOARD_ARTIST_MOTION_PROGRAM[phase];
      expect(tracks.map(({ part }) => part))
        .toHaveLength(new Set(tracks.map(({ part }) => part)).size);
      expect(tracks.every(({ options }) => (
        options.iterations === Infinity
        && options.easing === "linear"
      ))).toBe(true);
      expect(tracks.every(({ keyframes }) => keyframes.every((frame) => (
        Object.keys(frame).every((property) => (
          property === "offset"
          || property === "opacity"
          || property === "transform"
        ))
      )))).toBe(true);
    }

    expect(useAgentRoleMotion).toHaveBeenCalledOnce();
    expect(useAgentRoleMotion).toHaveBeenCalledWith(
      expect.objectContaining({ current: artwork }),
      "working",
      STORYBOARD_ARTIST_MOTION_PROGRAM,
    );
  });

  it("maps local emphasis to each fixed cell in rendered reading order", () => {
    const { container } = render(
      <StoryboardArtistAnimation motionState="working" />,
    );
    const artwork = container.querySelector<SVGSVGElement>("svg")!;
    const cells = [...artwork.querySelectorAll<SVGGElement>(
      '[data-part="base"] > [data-panel-cell]',
    )];
    const readingOrder = [...cells].sort((left, right) => {
      const leftPoint = translationFromGroup(left);
      const rightPoint = translationFromGroup(right);
      return leftPoint.y - rightPoint.y || leftPoint.x - rightPoint.x;
    }).map((cell) => cell.dataset.panelCell);
    const activationOrder = [...PANEL_EMPHASIS_PARTS].sort((left, right) => (
      Number(trackFor(left, "working").keyframes.find((frame) => (
        Number(frame.opacity) > 0 && Number(frame.offset) > 0.04
      ))?.offset)
        - Number(trackFor(right, "working").keyframes.find((frame) => (
          Number(frame.opacity) > 0 && Number(frame.offset) > 0.04
        ))?.offset)
    )).map((part) => part.replace("-emphasis", ""));

    expect(activationOrder).toEqual(readingOrder);
    for (const panelId of PANEL_IDS) {
      const cell = artwork.querySelector<SVGGElement>(
        `[data-panel-cell="${panelId}"]`,
      )!;
      const owner = artwork.querySelector<SVGGElement>(
        `[data-emphasis-owner="${panelId}"]`,
      )!;
      const emphasis = owner.querySelector<SVGGElement>(
        `[data-part="${panelId}-emphasis"]`,
      )!;
      const emphasisFrame = emphasis.querySelector<SVGRectElement>("rect")!;
      const activeContent = emphasis.querySelector<SVGGElement>(
        `[data-active-panel-content="${panelId}"]`,
      )!;
      const activeContentClip = activeContent.closest<SVGGElement>(
        "[data-active-content-clip]",
      )!;
      const baseFrame = cell.querySelector<SVGRectElement>("[data-panel-frame]")!;

      expect(owner.closest('[data-part="panel-sequence"]')).not.toBeNull();
      expect(translationFromGroup(owner)).toEqual(translationFromGroup(cell));
      expect(owner.getAttribute("clip-path")).toBeNull();
      expect(emphasisFrame.closest("[clip-path]")).toBeNull();
      expect(activeContentClip.getAttribute("clip-path") ?? "")
        .toMatch(/^url\(#.+\)$/);
      expect(activeContentClip).not.toContain(emphasisFrame);
      for (const attribute of [
        "x",
        "y",
        "width",
        "height",
        "rx",
        "stroke-width",
      ]) {
        expect(emphasisFrame.getAttribute(attribute))
          .toBe(baseFrame.getAttribute(attribute));
      }
      expect(emphasis.style.transformBox).toBe("fill-box");
      expect(emphasis.style.transformOrigin).toBe("center");
      expect(trackFor(`${panelId}-emphasis`, "working").keyframes.every(
        (frame) => frame.transform === undefined,
      )).toBe(true);
    }

    const cellParts = cells.map((cell) => cell.getAttribute("data-part"));
    const movingParts = STORYBOARD_ARTIST_MOTION_PROGRAM.working
      .map(({ part }) => part);
    expect(movingParts.some((part) => cellParts.includes(part))).toBe(false);
    expect(movingParts).not.toContain("base");
    expect(movingParts).not.toContain("panel-sequence");
    expect(movingParts).not.toContain("center-panel");
    expect(movingParts).not.toContain("pose-advance");
  });

  it("moves paired blue and yellow action gestures in lockstep inside their panel windows", () => {
    for (const panelId of ACTION_PANEL_IDS) {
      const baseTrack = trackFor(`${panelId}-action-stroke`, "working");
      const activeTrack = trackFor(`${panelId}-active-action-stroke`, "working");
      const emphasisTrack = trackFor(`${panelId}-emphasis`, "working");

      expect(activeTrack.keyframes).toEqual(baseTrack.keyframes);
      expect(activeTrack.options).toEqual(baseTrack.options);
      expect(baseTrack.options.duration).toBe(3_600);
      expect(baseTrack.keyframes.some((frame) => (
        String(frame.transform ?? "none") !== "none"
      ))).toBe(true);
      expect(baseTrack.keyframes.filter((frame) => (
        String(frame.transform ?? "none") !== "none"
      )).every((frame) => (
        opacityAt(emphasisTrack, Number(frame.offset)) > 0
      ))).toBe(true);
    }
  });

  it("keeps continuous cyclic focus with only brief adjacent handoffs", () => {
    const tracks = PANEL_EMPHASIS_PARTS.map((part) => (
      trackFor(part, "working")
    ));
    const panel1 = trackFor("panel-1-emphasis", "working");
    const panel9 = trackFor("panel-9-emphasis", "working");

    expect(poseSignature(panel1.keyframes[0]))
      .toBe(poseSignature(panel1.keyframes.at(-1)!));
    expect(poseSignature(panel9.keyframes[0]))
      .toBe(poseSignature(panel9.keyframes.at(-1)!));
    expect(opacityAt(panel9, 0)).toBeGreaterThan(0);
    expect(opacityAt(panel1, 0.02)).toBe(0);
    expect(opacityAt(panel1, 0.03)).toBeGreaterThan(0);
    expect(opacityAt(panel9, 0.03)).toBeGreaterThan(0);
    expect(opacityAt(panel1, 0.04)).toBeGreaterThan(0);
    expect(opacityAt(panel9, 0.04)).toBe(0);

    for (let sample = -20_000; sample <= 20_000; sample += 1) {
      const progress = ((sample / 20_000) % 1 + 1) % 1;
      const focusCount = tracks.filter((track) => (
        opacityAt(track, progress) > 0.000_001
      )).length;
      expect(focusCount).toBeGreaterThanOrEqual(1);
      expect(focusCount).toBeLessThanOrEqual(2);
    }
  });

  it("uses one yellow sequence while reserving the center frame for still states", () => {
    const { container: workingContainer } = render(
      <StoryboardArtistAnimation motionState="working" />,
    );
    const workingArtwork = workingContainer.querySelector<SVGSVGElement>("svg")!;
    const emphasisRects = [...workingArtwork.querySelectorAll<SVGRectElement>(
      "[data-emphasis-owner] rect",
    )];
    const workingBaseFrames = [...workingArtwork.querySelectorAll<SVGRectElement>(
      "[data-panel-frame]",
    )];

    expect(emphasisRects).toHaveLength(9);
    expect(emphasisRects.every((rect) => (
      rect.getAttribute("stroke") === "#FFB323"
    ))).toBe(true);
    expect(workingBaseFrames.every((rect) => (
      rect.getAttribute("stroke") === "#FAFBFF"
    ))).toBe(true);
    expect(new Set(PANEL_EMPHASIS_PARTS.map((part) => (
      Math.max(...trackFor(part, "working").keyframes.map((frame) => (
        Number(frame.opacity)
      )))
    )))).toEqual(new Set([0.88]));

    for (const motionState of ["idle", "waiting"] as const) {
      const { container } = render(
        <StoryboardArtistAnimation motionState={motionState} />,
      );
      const frames = [...container.querySelectorAll<SVGRectElement>(
        "[data-panel-frame]",
      )];
      expect(frames.filter((frame) => (
        frame.getAttribute("stroke") === "#FFB323"
      ))).toEqual([frames[4]]);
      expect([...container.querySelectorAll<SVGGElement>("[data-panel-content]")]
        .every((content) => [...content.querySelectorAll("[fill], [stroke]")]
          .flatMap((element) => [element.getAttribute("fill"), element.getAttribute("stroke")])
          .filter((paint): paint is string => paint !== null)
          .every((paint) => paint === "#7899E2" || paint === "none")))
        .toBe(true);
    }
  });

  it("returns every local target to the DOM pose with held seams and peaks", () => {
    const { container } = render(
      <StoryboardArtistAnimation motionState="working" />,
    );
    const tracks = [
      ...STORYBOARD_ARTIST_MOTION_PROGRAM.working,
      ...STORYBOARD_ARTIST_MOTION_PROGRAM.waiting,
    ];

    for (const track of tracks) {
      expectCanonicalLoop(track);
      const target = container.querySelector<SVGGraphicsElement>(
        `[data-part="${track.part}"]`,
      )!;
      const first = track.keyframes[0];
      expect(target.getAttribute("opacity") ?? "1")
        .toBe(String(first.opacity ?? 1));
      expect(target.style.transform || "none")
        .toBe(String(first.transform ?? "none"));
      expect(target.style.transformBox).toBe("fill-box");
      expect(target.style.transformOrigin).toBe("center");
    }
  });
});
