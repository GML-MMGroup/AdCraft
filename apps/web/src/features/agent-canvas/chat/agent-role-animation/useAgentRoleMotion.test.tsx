import { act, render } from "@testing-library/react";
import { type RefObject, useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
} from "./types.ts";
import { PRODUCT_DESIGNER_MOTION_PROGRAM } from "./roles/ProductDesignerAnimation.tsx";
import { PROP_DESIGNER_MOTION_PROGRAM } from "./roles/PropDesignerAnimation.tsx";
import { CHARACTER_DESIGNER_MOTION_PROGRAM } from "./roles/CharacterDesignerAnimation.tsx";
import { QUICK_MEDIA_MOTION_PROGRAM } from "./roles/QuickMediaAnimation.tsx";
import { SCENE_DESIGNER_MOTION_PROGRAM } from "./roles/SceneDesignerAnimation.tsx";
import { SCRIPT_WRITER_MOTION_PROGRAM } from "./roles/ScriptWriterAnimation.tsx";
import { STORYBOARD_ARTIST_MOTION_PROGRAM } from "./roles/StoryboardArtistAnimation.tsx";
import { VIDEO_DIRECTOR_MOTION_PROGRAM } from "./roles/VideoDirectorAnimation.tsx";
import { WORLD_SETTING_MOTION_PROGRAM } from "./roles/WorldSettingAnimation.tsx";
import {
  createAgentRoleMotionController,
  useAgentRoleMotion,
} from "./useAgentRoleMotion.ts";

const PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 220,
  working: [{
    part: "tool",
    keyframes: [
      { transform: "translateY(0px)" },
      { transform: "translateY(-1px)" },
      { transform: "translateY(0px)" },
    ],
    options: { duration: 3_000, iterations: Infinity, easing: "ease-in-out" },
  }],
  waiting: [{
    part: "tool",
    keyframes: [{ opacity: 0.72 }, { opacity: 1 }, { opacity: 0.72 }],
    options: { duration: 4_800, iterations: Infinity, easing: "ease-in-out" },
  }],
};

interface MockAnimation {
  play: ReturnType<typeof vi.fn>;
  pause: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
  finished: Promise<Animation>;
  playState: AnimationPlayState;
  currentTime: CSSNumberish | null;
}

interface MockMediaQueryList {
  readonly media: string;
  matches: boolean;
  onchange: ((this: MediaQueryList, event: MediaQueryListEvent) => unknown) | null;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
  addListener: ReturnType<typeof vi.fn>;
  removeListener: ReturnType<typeof vi.fn>;
  dispatchEvent: ReturnType<typeof vi.fn>;
}

let animations: MockAnimation[];
let finishResolvers: Array<() => void>;
let mediaQueryList: MockMediaQueryList;
let mediaListeners: Set<(event: MediaQueryListEvent) => void>;
let hidden: boolean;
let originalAnimate: PropertyDescriptor | undefined;
let originalHidden: PropertyDescriptor | undefined;

function createMockAnimation(): MockAnimation {
  let resolveFinished!: () => void;
  const finished = new Promise<Animation>((resolve) => {
    resolveFinished = () => resolve(animation as unknown as Animation);
  });
  const animation: MockAnimation = {
    play: vi.fn(() => {
      animation.playState = "running";
    }),
    pause: vi.fn(() => {
      animation.playState = "paused";
    }),
    cancel: vi.fn(() => {
      animation.playState = "idle";
    }),
    finished,
    playState: "running",
    currentTime: null,
  };
  finishResolvers.push(resolveFinished);
  animations.push(animation);
  return animation;
}

function stubComputedStyles(
  ...poses: Array<{ transform: string; opacity: string }>
): ReturnType<typeof vi.fn> {
  let index = 0;
  const getStyle = vi.fn(() => (
    poses[Math.min(index++, poses.length - 1)] as unknown as CSSStyleDeclaration
  ));
  vi.stubGlobal("getComputedStyle", getStyle);
  return getStyle;
}

function animationDuration(index: number): number | undefined {
  const options = vi.mocked(Element.prototype.animate).mock.calls[index]?.[1];
  return typeof options?.duration === "number" ? options.duration : undefined;
}

async function completeAnimationsWithDuration(duration: number): Promise<void> {
  const indices = animations.flatMap((animation, index) => (
    animationDuration(index) === duration && animation.playState !== "idle"
      ? [index]
      : []
  ));
  await act(async () => {
    for (const index of indices) finishResolvers[index]();
    await Promise.all(indices.map((index) => animations[index].finished));
  });
}

async function completeWorkingEntry(): Promise<void> {
  await completeAnimationsWithDuration(220);
}

function activeAnimationIndicesWithDuration(duration: number): number[] {
  return animations.flatMap((animation, index) => (
    animationDuration(index) === duration && animation.playState !== "idle"
      ? [index]
      : []
  ));
}

function throwOnAnimateCall(callNumber: number): void {
  let invocation = 0;
  vi.mocked(Element.prototype.animate).mockImplementation(() => {
    invocation += 1;
    if (invocation === callNumber) throw new Error("synthetic WAAPI failure");
    return createMockAnimation() as unknown as Animation;
  });
}

async function flushAsyncTransitions(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function keyframeOffset(frame: Keyframe, index: number, length: number): number {
  return typeof frame.offset === "number" ? frame.offset : index / (length - 1);
}

function cubicBezierCoordinate(
  time: number,
  controlPoint1: number,
  controlPoint2: number,
): number {
  const inverse = 1 - time;
  return 3 * inverse * inverse * time * controlPoint1
    + 3 * inverse * time * time * controlPoint2
    + time * time * time;
}

function easingProgress(easing: string | undefined, progress: number): number {
  if (!easing || easing === "linear") return progress;
  const match = easing.match(
    /^cubic-bezier\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)$/,
  );
  if (!match) throw new Error(`Unsupported test easing: ${easing}`);
  const [, x1Text, y1Text, x2Text, y2Text] = match;
  const [x1, y1, x2, y2] = [x1Text, y1Text, x2Text, y2Text].map(Number);
  let lower = 0;
  let upper = 1;
  for (let iteration = 0; iteration < 32; iteration += 1) {
    const candidate = (lower + upper) / 2;
    if (cubicBezierCoordinate(candidate, x1, x2) < progress) {
      lower = candidate;
    } else {
      upper = candidate;
    }
  }
  return cubicBezierCoordinate((lower + upper) / 2, y1, y2);
}

interface NumericPose {
  x: number;
  y: number;
  rotation: number;
  scale: number;
  opacity: number;
}

function numericPose(frame: Keyframe): NumericPose {
  const transform = String(frame.transform ?? "none");
  const translate = transform.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/);
  const translateX = transform.match(/translateX\((-?[\d.]+)px\)/);
  const translateY = transform.match(/translateY\((-?[\d.]+)px\)/);
  const rotation = transform.match(/rotate\((-?[\d.]+)deg\)/);
  const scale = transform.match(/scale\((-?[\d.]+)\)/);
  return {
    x: Number(translate?.[1] ?? translateX?.[1] ?? 0),
    y: Number(translate?.[2] ?? translateY?.[1] ?? 0),
    rotation: Number(rotation?.[1] ?? 0),
    scale: Number(scale?.[1] ?? 1),
    opacity: Number(frame.opacity ?? 1),
  };
}

function interpolatePose(from: NumericPose, to: NumericPose, progress: number): NumericPose {
  const interpolate = (start: number, end: number) => start + (end - start) * progress;
  return {
    x: interpolate(from.x, to.x),
    y: interpolate(from.y, to.y),
    rotation: interpolate(from.rotation, to.rotation),
    scale: interpolate(from.scale, to.scale),
    opacity: interpolate(from.opacity, to.opacity),
  };
}

function sampleTrackPose(
  track: AgentRoleMotionProgram["working"][number],
  timeMs: number,
): NumericPose {
  const iterationProgress = timeMs / Number(track.options.duration);
  const progress = easingProgress(
    String(track.options.easing ?? "linear"),
    iterationProgress,
  );
  const frames = track.keyframes;
  const exactIndex = frames.findIndex((frame, index) => (
    Math.abs(keyframeOffset(frame, index, frames.length) - progress) < 0.000001
  ));
  if (exactIndex >= 0) return numericPose(frames[exactIndex]);
  const rightIndex = frames.findIndex((frame, index) => (
    keyframeOffset(frame, index, frames.length) > progress
  ));
  if (rightIndex <= 0) return numericPose(frames[Math.max(0, rightIndex)]);
  if (rightIndex < 0) return numericPose(frames.at(-1)!);
  const leftIndex = rightIndex - 1;
  const leftOffset = keyframeOffset(frames[leftIndex], leftIndex, frames.length);
  const rightOffset = keyframeOffset(frames[rightIndex], rightIndex, frames.length);
  return interpolatePose(
    numericPose(frames[leftIndex]),
    numericPose(frames[rightIndex]),
    easingProgress(
      String(frames[leftIndex].easing ?? "linear"),
      (progress - leftOffset) / (rightOffset - leftOffset),
    ),
  );
}

function poseIsNoncanonical(pose: NumericPose, canonical: NumericPose): boolean {
  return Math.abs(pose.x - canonical.x) > 0.001
    || Math.abs(pose.y - canonical.y) > 0.001
    || Math.abs(pose.rotation - canonical.rotation) > 0.001
    || Math.abs(pose.scale - canonical.scale) > 0.001
    || Math.abs(pose.opacity - canonical.opacity) > 0.001;
}

function cssPose(pose: NumericPose): CSSStyleDeclaration {
  return {
    transform: `translate(${pose.x}px, ${pose.y}px) rotate(${pose.rotation}deg) scale(${pose.scale})`,
    opacity: String(pose.opacity),
  } as unknown as CSSStyleDeclaration;
}

function setReducedMotion(matches: boolean): void {
  mediaQueryList.matches = matches;
  const event = { matches, media: mediaQueryList.media } as MediaQueryListEvent;
  for (const listener of mediaListeners) {
    listener(event);
  }
}

function MotionHarness({
  motionState,
  program = PROGRAM,
  rootRef,
}: {
  motionState: AgentRoleMotionState;
  program?: AgentRoleMotionProgram;
  rootRef?: RefObject<SVGSVGElement | null>;
}) {
  const localRootRef = useRef<SVGSVGElement>(null);
  const resolvedRootRef = rootRef ?? localRootRef;
  useAgentRoleMotion(resolvedRootRef, motionState, program);

  return (
    <svg ref={resolvedRootRef}>
      <g data-part="tool" style={{ opacity: 0.5, transform: "translateX(2px)" }} />
    </svg>
  );
}

describe("useAgentRoleMotion", () => {
  beforeEach(() => {
    animations = [];
    finishResolvers = [];
    mediaListeners = new Set();
    hidden = false;

    originalAnimate = Object.getOwnPropertyDescriptor(Element.prototype, "animate");
    Object.defineProperty(Element.prototype, "animate", {
      configurable: true,
      value: vi.fn(() => createMockAnimation()),
    });

    originalHidden = Object.getOwnPropertyDescriptor(document, "hidden");
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => hidden,
    });

    mediaQueryList = {
      media: "(prefers-reduced-motion: reduce)",
      matches: false,
      onchange: null,
      addEventListener: vi.fn((type: string, listener: (event: MediaQueryListEvent) => void) => {
        if (type === "change") mediaListeners.add(listener);
      }),
      removeEventListener: vi.fn((type: string, listener: (event: MediaQueryListEvent) => void) => {
        if (type === "change") mediaListeners.delete(listener);
      }),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    };
    vi.stubGlobal("matchMedia", vi.fn((query: string) => {
      expect(query).toBe("(prefers-reduced-motion: reduce)");
      return mediaQueryList as unknown as MediaQueryList;
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (originalAnimate) {
      Object.defineProperty(Element.prototype, "animate", originalAnimate);
    } else {
      Reflect.deleteProperty(Element.prototype, "animate");
    }
    if (originalHidden) {
      Object.defineProperty(document, "hidden", originalHidden);
    } else {
      Reflect.deleteProperty(document, "hidden");
    }
  });

  it("enters the browser-sampled working pose over exactly 220ms before starting the loop", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [
      '<g data-part="tool" ',
      'style="transform: translateX(2px); opacity: 0.5"></g>',
    ].join("");
    const underlyingPose = {
      transform: "matrix(1, 0, 0, 1, 2, 0)",
      opacity: "0.5",
    };
    const sampledWorkingPose = {
      transform: "matrix(1, 0, 0, 1, 2, -0.2)",
      opacity: "0.5",
    };
    const getStyle = stubComputedStyles(underlyingPose, sampledWorkingPose);
    const controller = createAgentRoleMotionController(root, PROGRAM);

    controller.playWorking();

    expect(getStyle).toHaveBeenCalledTimes(2);
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      1,
      PROGRAM.working[0].keyframes,
      { ...PROGRAM.working[0].options, fill: "both" },
    );
    expect(animations[0].pause).toHaveBeenCalledOnce();
    expect(animations[0].currentTime).toBe(220);
    expect(animations[0].cancel).toHaveBeenCalledOnce();
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      2,
      [underlyingPose, sampledWorkingPose],
      {
        duration: 220,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
    expect(Element.prototype.animate).toHaveBeenCalledTimes(2);

    await act(async () => {
      finishResolvers[1]();
      await animations[1].finished;
    });

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      3,
      PROGRAM.working[0].keyframes,
      { ...PROGRAM.working[0].options, fill: "both" },
    );
    expect(animations[2].currentTime).toBe(220);
  });

  it("hands a finite intro off to the loop once, at time zero", async () => {
    const program = {
      ...PROGRAM,
      workingIntro: [{ ...PROGRAM.working[0], options: { duration: 3_200, iterations: 1 } }],
    };
    render(<MotionHarness motionState="working" program={program} />);
    await completeWorkingEntry();
    expect(activeAnimationIndicesWithDuration(3_200)).toHaveLength(1);
    expect(activeAnimationIndicesWithDuration(3_000)).toHaveLength(0);
    await completeAnimationsWithDuration(3_200);
    const loops = activeAnimationIndicesWithDuration(3_000);
    expect(loops).toHaveLength(1);
    expect(animations[loops[0]].currentTime).toBe(0);
    expect(activeAnimationIndicesWithDuration(3_200)).toHaveLength(0);
  });

  it.each(["idle", "waiting", "unmount"] as const)(
    "does not let an interrupted intro restart after %s",
    async (nextState) => {
      const program = {
        ...PROGRAM,
        workingIntro: [{ ...PROGRAM.working[0], options: { duration: 3_200, iterations: 1 } }],
      };
      const view = render(<MotionHarness motionState="working" program={program} />);
      await completeWorkingEntry();
      const intros = activeAnimationIndicesWithDuration(3_200);
      expect(intros).toHaveLength(1);
      if (nextState === "unmount") view.unmount();
      else view.rerender(<MotionHarness motionState={nextState} program={program} />);
      await act(async () => { intros.forEach((index) => finishResolvers[index]()); });
      expect(activeAnimationIndicesWithDuration(3_000)).toHaveLength(0);
    },
  );

  it("keeps a loop paused when intro completion races a hidden page", async () => {
    const program = {
      ...PROGRAM,
      workingIntro: [{ ...PROGRAM.working[0], options: { duration: 3_200, iterations: 1 } }],
    };
    render(<MotionHarness motionState="working" program={program} />);
    await completeWorkingEntry();
    hidden = true;
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await completeAnimationsWithDuration(3_200);
    const loops = activeAnimationIndicesWithDuration(3_000);
    expect(loops).toHaveLength(1);
    expect(animations[loops[0]].playState).toBe("paused");
    hidden = false;
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(animations[loops[0]].playState).toBe("running");
  });

  it("honors a role-specific working transition duration", () => {
    const program: AgentRoleMotionProgram = {
      ...PROGRAM,
      workingTransitionDurationMs: 160,
    };
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="tool"></g>';
    stubComputedStyles(
      { transform: "none", opacity: "1" },
      { transform: "translateY(-1px)", opacity: "1" },
    );

    createAgentRoleMotionController(root, program).playWorking();

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      2,
      [
        { transform: "none", opacity: "1" },
        { transform: "translateY(-1px)", opacity: "1" },
      ],
      {
        duration: 160,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
  });

  it.each([
    ["World", WORLD_SETTING_MOTION_PROGRAM],
    ["Product", PRODUCT_DESIGNER_MOTION_PROGRAM],
    ["Prop", PROP_DESIGNER_MOTION_PROGRAM],
    ["Character", CHARACTER_DESIGNER_MOTION_PROGRAM],
    ["Scene", SCENE_DESIGNER_MOTION_PROGRAM],
    ["Script", SCRIPT_WRITER_MOTION_PROGRAM],
    ["Storyboard", STORYBOARD_ARTIST_MOTION_PROGRAM],
    ["Video", VIDEO_DIRECTOR_MOTION_PROGRAM],
    ["Quick Media", QUICK_MEDIA_MOTION_PROGRAM],
  ] as const)("gives %s a visible, bounded, continuous entry seam", async (_name, program) => {
    expect(program.workingEntryTimeMs).toBeGreaterThan(0);
    const entryTracks = program.workingIntro ?? program.working;
    const sampledPoses = new Map(entryTracks.map((track) => [
      track.part,
      sampleTrackPose(track, program.workingEntryTimeMs),
    ]));
    const canonicalPoses = new Map(entryTracks.map((track) => [
      track.part,
      numericPose(track.keyframes[0]),
    ]));
    expect([...sampledPoses].some(([part, pose]) => (
      poseIsNoncanonical(pose, canonicalPoses.get(part)!)
    ))).toBe(true);
    for (const [part, pose] of sampledPoses) {
      const canonical = canonicalPoses.get(part)!;
      expect(Math.hypot(pose.x - canonical.x, pose.y - canonical.y) / 16).toBeLessThanOrEqual(1.5);
      expect(Math.abs(pose.rotation)).toBeLessThanOrEqual(6);
    }

    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [...sampledPoses.keys()]
      .map((part) => `<g data-part="${part}"></g>`)
      .join("");
    vi.stubGlobal("getComputedStyle", vi.fn((part: SVGGraphicsElement) => {
      const previewIsSampling = animations.some((animation) => (
        animation.currentTime === program.workingEntryTimeMs
        && animation.playState === "paused"
      ));
      return cssPose(
        previewIsSampling
          ? sampledPoses.get(part.dataset.part ?? "")!
          : canonicalPoses.get(part.dataset.part ?? "")!,
      );
    }));
    const controller = createAgentRoleMotionController(root, program);

    controller.playWorking();

    const entryDuration = program.workingTransitionDurationMs ?? 220;
    const entryIndices = activeAnimationIndicesWithDuration(entryDuration);
    expect(entryIndices.length).toBeGreaterThan(0);
    expect(entryIndices.some((index) => {
      const frames = vi.mocked(Element.prototype.animate).mock.calls[index][0] as Keyframe[];
      return JSON.stringify(frames[1]) !== JSON.stringify(frames[0]);
    })).toBe(true);
    await completeAnimationsWithDuration(entryDuration);
    const liveLoops = animations.filter((animation) => animation.playState !== "idle");
    expect(liveLoops).toHaveLength(entryTracks.length);
    expect(liveLoops.every((animation) => (
      animation.currentTime === program.workingEntryTimeMs
    ))).toBe(true);
  });

  it("uses the program entry sample for both the 220ms target and loop continuation", async () => {
    const program = { ...PROGRAM, workingEntryTimeMs: 640 };
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="tool"></g>';
    const controller = createAgentRoleMotionController(root, program);

    controller.playWorking();

    expect(animations[0].currentTime).toBe(640);
    expect(animationDuration(1)).toBe(220);
    await act(async () => {
      finishResolvers[1]();
      await animations[1].finished;
    });
    expect(animations[2].currentTime).toBe(640);
  });

  it("rolls back a partially-created waiting loop when the second track throws", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="first"></g><g data-part="second"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [],
      waiting: [
        { ...PROGRAM.waiting[0], part: "first" },
        { ...PROGRAM.waiting[0], part: "second" },
      ],
    };
    throwOnAnimateCall(2);
    const controller = createAgentRoleMotionController(root, program);

    controller.playWaiting();
    await flushAsyncTransitions();

    expect(Element.prototype.animate).toHaveBeenCalledTimes(2);
    expect(animations).toHaveLength(1);
    expect(animations[0].cancel).toHaveBeenCalledOnce();
    expect(animations[0].playState).toBe("idle");
  });

  it("rolls back a partially-created working entry when the second part throws", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="first"></g><g data-part="second"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [
        { ...PROGRAM.working[0], part: "first" },
        { ...PROGRAM.working[0], part: "second" },
      ],
      waiting: [],
    };
    throwOnAnimateCall(4);
    const controller = createAgentRoleMotionController(root, program);

    controller.playWorking();
    await flushAsyncTransitions();

    expect(Element.prototype.animate).toHaveBeenCalledTimes(4);
    expect(animations).toHaveLength(3);
    expect(animations[2].cancel).toHaveBeenCalledOnce();
    expect(animations.every((animation) => animation.playState === "idle")).toBe(true);
  });

  it("rolls back a partially-created working loop after entry completes", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="first"></g><g data-part="second"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [
        { ...PROGRAM.working[0], part: "first" },
        { ...PROGRAM.working[0], part: "second" },
      ],
      waiting: [],
    };
    throwOnAnimateCall(6);
    const controller = createAgentRoleMotionController(root, program);

    controller.playWorking();
    await completeWorkingEntry();
    await flushAsyncTransitions();

    expect(Element.prototype.animate).toHaveBeenCalledTimes(6);
    expect(animations).toHaveLength(5);
    expect(animations[4].cancel).toHaveBeenCalledOnce();
    expect(animations.every((animation) => animation.playState === "idle")).toBe(true);
  });

  it("rolls back a partially-created waiting transition", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="first"></g><g data-part="second"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [
        { ...PROGRAM.working[0], part: "first" },
        { ...PROGRAM.working[0], part: "second" },
      ],
      waiting: [
        { ...PROGRAM.waiting[0], part: "first" },
        { ...PROGRAM.waiting[0], part: "second" },
      ],
    };
    throwOnAnimateCall(8);
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();

    controller.playWaiting();
    await flushAsyncTransitions();

    expect(Element.prototype.animate).toHaveBeenCalledTimes(8);
    expect(animations).toHaveLength(7);
    expect(animations[6].cancel).toHaveBeenCalledOnce();
    expect(animations.every((animation) => animation.playState === "idle")).toBe(true);
  });

  it("resolves settle after rolling back a partially-created batch", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="first"></g><g data-part="second"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [
        { ...PROGRAM.working[0], part: "first" },
        { ...PROGRAM.working[0], part: "second" },
      ],
      waiting: [],
    };
    throwOnAnimateCall(8);
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();

    await expect(controller.settle()).resolves.toBeUndefined();

    expect(Element.prototype.animate).toHaveBeenCalledTimes(8);
    expect(animations).toHaveLength(7);
    expect(animations[6].cancel).toHaveBeenCalledOnce();
    expect(animations.every((animation) => animation.playState === "idle")).toBe(true);
  });

  it("keeps the SVG still without throwing when WAAPI is unavailable", () => {
    Reflect.deleteProperty(Element.prototype, "animate");
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="tool"></g>';
    const controller = createAgentRoleMotionController(root, PROGRAM);

    expect(() => controller.playWorking()).not.toThrow();
    expect(animations).toHaveLength(0);
  });

  it("interrupts the 220ms entry without starting a stale working loop", async () => {
    const { rerender } = render(<MotionHarness motionState="working" />);
    const entryIndex = activeAnimationIndicesWithDuration(220)[0];
    const entryAnimation = animations[entryIndex];

    rerender(<MotionHarness motionState="waiting" />);
    const callCount = animations.length;
    expect(entryAnimation.cancel).toHaveBeenCalledOnce();

    await act(async () => {
      finishResolvers[entryIndex]();
      await entryAnimation.finished;
    });

    expect(Element.prototype.animate).toHaveBeenCalledTimes(callCount);
    expect(vi.mocked(Element.prototype.animate).mock.calls.filter(
      ([frames]) => frames === PROGRAM.working[0].keyframes,
    )).toHaveLength(1);
  });

  it("hands working motion into waiting motion before settling idle", async () => {
    const { rerender } = render(<MotionHarness motionState="working" />);

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      1,
      PROGRAM.working[0].keyframes,
      { ...PROGRAM.working[0].options, fill: "both" },
    );

    await completeWorkingEntry();

    rerender(<MotionHarness motionState="waiting" />);

    expect(animations[2].pause).toHaveBeenCalledOnce();
    expect(animations[2].cancel).toHaveBeenCalledOnce();
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      4,
      PROGRAM.waiting[0].keyframes,
      { ...PROGRAM.waiting[0].options, fill: "both" },
    );
    expect(animations[3].pause).toHaveBeenCalledOnce();
    expect(animations[3].currentTime).toBe(0);
    expect(animations[3].cancel).toHaveBeenCalledOnce();
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      5,
      [
        { transform: "translateX(2px)", opacity: "0.5" },
        { transform: "translateX(2px)", opacity: "0.5" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
    expect(Element.prototype.animate).toHaveBeenCalledTimes(5);

    await act(async () => {
      finishResolvers[4]();
      await animations[4].finished;
    });

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      6,
      PROGRAM.waiting[0].keyframes,
      { ...PROGRAM.waiting[0].options, fill: "both" },
    );

    rerender(<MotionHarness motionState="idle" />);

    expect(animations[5].pause).toHaveBeenCalledOnce();
    expect(animations[5].cancel).toHaveBeenCalledOnce();
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      7,
      [
        { transform: "translateX(2px)", opacity: "0.5" },
        { transform: "translateX(2px)", opacity: "0.5" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
  });

  it("settles to a noncanonical underlying pose exposed after fill cancellation", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [
      '<g data-part="tool" ',
      'style="transform: translateX(4px); opacity: 0.2"></g>',
    ].join("");
    const part = root.querySelector<SVGGraphicsElement>('[data-part="tool"]')!;
    const activePose = {
      transform: "matrix(1, 0, 0, 1, 11, 0)",
      opacity: "0.73",
    };
    const underlyingPose = {
      transform: "matrix(1, 0, 0, 1, 4, 0)",
      opacity: "0.2",
    };
    const controller = createAgentRoleMotionController(root, PROGRAM);
    controller.playWorking();
    await completeWorkingEntry();
    const workingAnimation = animations[2];
    const getStyle = vi.fn(() => (
      workingAnimation.playState === "idle" ? underlyingPose : activePose
    ) as unknown as CSSStyleDeclaration);
    vi.stubGlobal("getComputedStyle", getStyle);
    const settlePromise = controller.settle();

    expect(getStyle).toHaveBeenCalledTimes(2);
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      4,
      [activePose, underlyingPose],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );

    await act(async () => {
      finishResolvers[3]();
      await settlePromise;
    });

    expect(animations[3].cancel).toHaveBeenCalledOnce();
    const exposedStyle = getComputedStyle(part);
    expect({
      transform: exposedStyle.transform,
      opacity: exposedStyle.opacity,
    }).toEqual(underlyingPose);
  });

  it.each(["working", "waiting"] as const)(
    "settles Prop %s light and guides to their authored hidden pose",
    async (phase) => {
      const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      const activeTracks = PROP_DESIGNER_MOTION_PROGRAM[phase];
      const parts = [...new Set(activeTracks.map((track) => track.part))];
      const hiddenParts = parts.filter((part) => (
        part === "shade-light" || part.startsWith("guide-active-")
      ));
      root.innerHTML = parts.map((part) => (
        `<g data-part="${part}" style="opacity: ${
          hiddenParts.includes(part) ? 0 : 1
        }; transform: none"></g>`
      )).join("");
      const underlyingPoses = new Map(parts.map((part) => {
        const target = root.querySelector<SVGGraphicsElement>(
          `[data-part="${part}"]`,
        )!;
        const style = getComputedStyle(target);
        return [target, { transform: style.transform, opacity: style.opacity }];
      }));
      if (phase === "working") {
        const controller = createAgentRoleMotionController(
          root,
          PROP_DESIGNER_MOTION_PROGRAM,
        );
        controller.playWorking();
        await completeWorkingEntry();
        const activeAnimations = animations.slice(-activeTracks.length);
        vi.stubGlobal("getComputedStyle", vi.fn((target: SVGGraphicsElement) => {
          const part = target.dataset.part ?? "";
          const active = activeAnimations.some(
            (animation) => animation.playState !== "idle",
          );
          if (active && hiddenParts.includes(part)) {
            return {
              transform: part === "shade-light"
                ? "none"
                : "matrix(1, 0, 0, 1, 0, 12)",
              opacity: part === "shade-light" ? "0.68" : "0.58",
            } as unknown as CSSStyleDeclaration;
          }
          return underlyingPoses.get(target) as unknown as CSSStyleDeclaration;
        }));
        const settlePromise = controller.settle();
        const settleIndices = activeAnimationIndicesWithDuration(180);

        for (const part of hiddenParts) {
          const partIndex = parts.indexOf(part);
          const settleFrames = vi.mocked(Element.prototype.animate)
            .mock.calls[settleIndices[partIndex]]?.[0] as Keyframe[];
          expect(Number(settleFrames[0]?.opacity), `${phase} ${part} start`)
            .toBeGreaterThan(0);
          expect(settleFrames[1]?.opacity, `${phase} ${part} endpoint`).toBe("0");
        }

        await act(async () => {
          for (const index of settleIndices) finishResolvers[index]();
          await settlePromise;
        });
      } else {
        vi.stubGlobal("getComputedStyle", vi.fn((target: SVGGraphicsElement) => {
        const part = target.dataset.part ?? "";
        const active = animations.slice(0, activeTracks.length)
          .some((animation) => animation.playState !== "idle");
        if (active && hiddenParts.includes(part)) {
          return {
            transform: part === "shade-light"
              ? "none"
              : "matrix(1, 0, 0, 1, 0, 12)",
            opacity: part === "shade-light" ? "0.68" : "0.58",
          } as unknown as CSSStyleDeclaration;
        }
        return underlyingPoses.get(target) as unknown as CSSStyleDeclaration;
        }));
        const controller = createAgentRoleMotionController(
          root,
          PROP_DESIGNER_MOTION_PROGRAM,
        );
        controller.playWaiting();
        const settlePromise = controller.settle();
        const settleIndices = activeAnimationIndicesWithDuration(180);

        for (const part of hiddenParts) {
          const partIndex = parts.indexOf(part);
          const settleFrames = vi.mocked(Element.prototype.animate)
            .mock.calls[settleIndices[partIndex]]?.[0] as Keyframe[];
          expect(Number(settleFrames[0]?.opacity), `${phase} ${part} start`)
            .toBeGreaterThan(0);
          expect(settleFrames[1]?.opacity, `${phase} ${part} endpoint`).toBe("0");
        }

        await act(async () => {
          for (const index of settleIndices) finishResolvers[index]();
          await settlePromise;
        });
      }

      for (const part of hiddenParts) {
        const target = root.querySelector<SVGGraphicsElement>(
          `[data-part="${part}"]`,
        )!;
        expect(getComputedStyle(target).opacity, `${phase} ${part} exposed`)
          .toBe("0");
      }
    },
  );

  it("settles working-only parts while shared parts enter their waiting start pose", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [
      '<g data-part="shared" style="transform: translateX(9px); opacity: 0.6"></g>',
      '<g data-part="working-only" style="transform: translateY(-7px); opacity: 0.4"></g>',
    ].join("");
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [
        {
          part: "shared",
          keyframes: [{ transform: "none" }, { transform: "translateX(12px)" }],
          options: { duration: 3_200, iterations: Infinity },
        },
        {
          part: "working-only",
          keyframes: [{ opacity: 1 }, { opacity: 0.5 }],
          options: { duration: 3_200, iterations: Infinity },
        },
      ],
      waiting: [{
        part: "shared",
        keyframes: [
          { transform: "translateX(3px)", opacity: 0.8 },
          { transform: "none", opacity: 1 },
        ],
        options: { duration: 4_800, iterations: Infinity },
      }],
    };
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();
    controller.playWaiting();

    const settleIndices = activeAnimationIndicesWithDuration(180);

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      settleIndices[0] + 1,
      [
        { transform: "translateX(9px)", opacity: "0.6" },
        { transform: "translateX(9px)", opacity: "0.6" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      settleIndices[1] + 1,
      [
        { transform: "translateY(-7px)", opacity: "0.4" },
        { transform: "translateY(-7px)", opacity: "0.4" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );

    await act(async () => {
      for (const index of settleIndices) finishResolvers[index]();
      await Promise.all(settleIndices.map((index) => animations[index].finished));
    });

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      animations.length,
      program.waiting[0].keyframes,
      { ...program.waiting[0].options, fill: "both" },
    );
  });

  it("hands a waiting-only part into its noncanonical first pose", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [
      '<g data-part="working" style="transform: translateY(-5px); opacity: 0.5"></g>',
      '<g data-part="waiting-only" ',
      'style="transform: translateX(4px); opacity: 1"></g>',
    ].join("");
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        part: "working",
        keyframes: [{ transform: "none" }, { transform: "translateY(-8px)" }],
        options: { duration: 3_200, iterations: Infinity },
      }],
      waiting: [{
        part: "waiting-only",
        keyframes: [
          { opacity: 0.7 },
          { opacity: 1 },
        ],
        options: { duration: 4_800, iterations: Infinity },
      }],
    };
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();
    controller.playWaiting();

    const settleIndices = activeAnimationIndicesWithDuration(180);

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      settleIndices[0] + 1,
      [
        { transform: "translateY(-5px)", opacity: "0.5" },
        { transform: "translateY(-5px)", opacity: "0.5" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      settleIndices[1] + 1,
      [
        { transform: "translateX(4px)", opacity: "1" },
        { transform: "translateX(4px)", opacity: "1" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );

    await act(async () => {
      for (const index of settleIndices) finishResolvers[index]();
      await Promise.all(settleIndices.map((index) => animations[index].finished));
    });
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      animations.length,
      program.waiting[0].keyframes,
      { ...program.waiting[0].options, fill: "both" },
    );
  });

  it("merges first frames from independent same-part waiting tracks", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [
      '<g data-part="shared" ',
      'style="transform: translateX(9px); opacity: 0.55"></g>',
    ].join("");
    const transformTrack = {
      part: "shared",
      keyframes: [
        { transform: "translateX(3px)" },
        { transform: "translateX(6px)" },
      ],
      options: { duration: 4_800, iterations: Infinity },
    } satisfies AgentRoleMotionProgram["waiting"][number];
    const opacityTrack = {
      part: "shared",
      keyframes: [{ opacity: 0.65 }, { opacity: 1 }],
      options: { duration: 4_800, iterations: Infinity },
    } satisfies AgentRoleMotionProgram["waiting"][number];
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        part: "shared",
        keyframes: [{ transform: "none" }, { transform: "translateX(12px)" }],
        options: { duration: 3_200, iterations: Infinity },
      }],
      waiting: [transformTrack, opacityTrack],
    };
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();
    controller.playWaiting();

    const settleIndex = activeAnimationIndicesWithDuration(180)[0];

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      settleIndex + 1,
      [
        { transform: "translateX(9px)", opacity: "0.55" },
        { transform: "translateX(9px)", opacity: "0.55" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );

    await act(async () => {
      finishResolvers[settleIndex]();
      await animations[settleIndex].finished;
    });
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      animations.length - 1,
      transformTrack.keyframes,
      { ...transformTrack.options, fill: "both" },
    );
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      animations.length,
      opacityTrack.keyframes,
      { ...opacityTrack.options, fill: "both" },
    );
  });

  it("uses the browser-sampled pose when inherited or invalid keyframe values are ignored", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="shared"></g>';
    const inheritedInvalidFrame = Object.assign(
      Object.create({ transform: "translateX(999px)" }) as Keyframe,
      { opacity: "definitely-invalid" },
    );
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        part: "shared",
        keyframes: [{ transform: "none" }, { transform: "translateX(12px)" }],
        options: { duration: 3_200, iterations: Infinity },
      }],
      waiting: [{
        part: "shared",
        keyframes: [inheritedInvalidFrame, { opacity: 1 }],
        options: { duration: 4_800, iterations: Infinity },
      }],
    };
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();
    const getStyle = stubComputedStyles(
      { transform: "matrix(1, 0, 0, 1, 9, 0)", opacity: "0.55" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.8" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.8" },
    );

    controller.playWaiting();

    const settleCall = vi.mocked(Element.prototype.animate).mock.calls.find(
      ([, options]) => options?.duration === 180,
    );
    expect(getStyle).toHaveBeenCalledTimes(3);
    const waitingPreviewIndex = vi.mocked(Element.prototype.animate).mock.calls
      .findIndex(([frames], index) => (
        index >= 3 && frames === program.waiting[0].keyframes
      ));
    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      waitingPreviewIndex + 1,
      program.waiting[0].keyframes,
      { ...program.waiting[0].options, fill: "both" },
    );
    expect(animations[waitingPreviewIndex].currentTime).toBe(0);
    expect(animations[waitingPreviewIndex].cancel).toHaveBeenCalledOnce();
    expect(settleCall?.[0]).toEqual([
      { transform: "matrix(1, 0, 0, 1, 9, 0)", opacity: "0.55" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.8" },
    ]);
  });

  it("uses the browser-composited pose for additive same-part waiting tracks", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="shared"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        part: "shared",
        keyframes: [{ transform: "none" }, { transform: "translateX(12px)" }],
        options: { duration: 3_200, iterations: Infinity },
      }],
      waiting: [3, 5].map((distance) => ({
        part: "shared",
        keyframes: [
          { transform: `translateX(${distance}px)` },
          { transform: `translateX(${distance + 1}px)` },
        ],
        options: { duration: 4_800, iterations: Infinity, composite: "add" },
      })),
    };
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();
    const getStyle = stubComputedStyles(
      { transform: "matrix(1, 0, 0, 1, 9, 0)", opacity: "0.55" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.8" },
      { transform: "matrix(1, 0, 0, 1, 12, 0)", opacity: "0.8" },
    );

    controller.playWaiting();

    const settleCall = vi.mocked(Element.prototype.animate).mock.calls.find(
      ([, options]) => options?.duration === 180,
    );
    expect(getStyle).toHaveBeenCalledTimes(3);
    for (const [index, waitingTrack] of program.waiting.entries()) {
      expect(Element.prototype.animate).toHaveBeenNthCalledWith(
        index + 4,
        waitingTrack.keyframes,
        { ...waitingTrack.options, fill: "both" },
      );
      expect(animations[index + 3].currentTime).toBe(0);
      expect(animations[index + 3].cancel).toHaveBeenCalledOnce();
    }
    expect(settleCall?.[0]).toEqual([
      { transform: "matrix(1, 0, 0, 1, 9, 0)", opacity: "0.55" },
      { transform: "matrix(1, 0, 0, 1, 12, 0)", opacity: "0.8" },
    ]);
  });

  it("preserves a noncanonical underlying transform omitted by waiting", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="shared"></g>';
    const program: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        part: "shared",
        keyframes: [{ transform: "none" }, { transform: "translateX(12px)" }],
        options: { duration: 3_200, iterations: Infinity },
      }],
      waiting: [{
        part: "shared",
        keyframes: [{ opacity: 0.65 }, { opacity: 1 }],
        options: { duration: 4_800, iterations: Infinity },
      }],
    };
    const controller = createAgentRoleMotionController(root, program);
    controller.playWorking();
    await completeWorkingEntry();
    stubComputedStyles(
      { transform: "matrix(1, 0, 0, 1, 9, 0)", opacity: "0.55" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.8" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.65" },
    );

    controller.playWaiting();

    const settleCall = vi.mocked(Element.prototype.animate).mock.calls.find(
      ([, options]) => options?.duration === 180,
    );
    expect(settleCall?.[0]).toEqual([
      { transform: "matrix(1, 0, 0, 1, 9, 0)", opacity: "0.55" },
      { transform: "matrix(1, 0, 0, 1, 4, 0)", opacity: "0.65" },
    ]);
  });

  it("does not start a stale waiting loop when its handoff is interrupted", async () => {
    const { rerender } = render(<MotionHarness motionState="working" />);
    await completeWorkingEntry();
    rerender(<MotionHarness motionState="waiting" />);
    const handoffIndex = activeAnimationIndicesWithDuration(180)[0];
    const handoffAnimation = animations[handoffIndex];

    rerender(<MotionHarness motionState="working" />);
    const replacementAnimation = animations.at(-1)!;
    const callCount = animations.length;

    await act(async () => {
      finishResolvers[handoffIndex]();
      await handoffAnimation.finished;
    });

    expect(handoffAnimation.cancel).toHaveBeenCalledOnce();
    expect(replacementAnimation.cancel).not.toHaveBeenCalled();
    expect(Element.prototype.animate).toHaveBeenCalledTimes(callCount);
  });

  it("does not start a stale waiting loop after idle interrupts its handoff", async () => {
    const { rerender } = render(<MotionHarness motionState="working" />);
    await completeWorkingEntry();
    rerender(<MotionHarness motionState="waiting" />);
    const handoffIndex = activeAnimationIndicesWithDuration(180)[0];
    const handoffAnimation = animations[handoffIndex];

    rerender(<MotionHarness motionState="idle" />);
    const idleSettleAnimation = animations.at(-1)!;
    const callCount = animations.length;

    await act(async () => {
      finishResolvers[handoffIndex]();
      await handoffAnimation.finished;
    });

    expect(handoffAnimation.cancel).toHaveBeenCalledOnce();
    expect(idleSettleAnimation.cancel).not.toHaveBeenCalled();
    expect(Element.prototype.animate).toHaveBeenCalledTimes(callCount);
  });

  it("does not start a stale waiting loop after disposal", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = '<g data-part="tool"></g>';
    const controller = createAgentRoleMotionController(root, PROGRAM);
    controller.playWorking();
    await completeWorkingEntry();
    controller.playWaiting();
    const handoffIndex = activeAnimationIndicesWithDuration(180)[0];
    const handoffAnimation = animations[handoffIndex];

    controller.dispose();
    const callCount = animations.length;
    await act(async () => {
      finishResolvers[handoffIndex]();
      await handoffAnimation.finished;
    });

    expect(handoffAnimation.cancel).toHaveBeenCalledOnce();
    expect(Element.prototype.animate).toHaveBeenCalledTimes(callCount);
  });

  it("settles an arbitrary Product sweep pose into its still waiting state", async () => {
    const root = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    root.innerHTML = [
      '<g data-part="glass-sweep" ',
      'style="transform: translateX(11px); opacity: 0.63"></g>',
    ].join("");
    const controller = createAgentRoleMotionController(
      root,
      PRODUCT_DESIGNER_MOTION_PROGRAM,
    );
    controller.playWorking();
    await completeWorkingEntry();
    stubComputedStyles(
      { transform: "translateX(11px)", opacity: "0.63" },
      { transform: "none", opacity: "1" },
      { transform: "matrix(1, 0, 0, 1, 0, 0)", opacity: "1" },
    );
    controller.playWaiting();

    const settleIndex = activeAnimationIndicesWithDuration(180)[0];

    expect(Element.prototype.animate).toHaveBeenNthCalledWith(
      settleIndex + 1,
      [
        { transform: "translateX(11px)", opacity: "0.63" },
        { transform: "matrix(1, 0, 0, 1, 0, 0)", opacity: "1" },
      ],
      {
        duration: 180,
        easing: "cubic-bezier(.23, 1, .32, 1)",
        fill: "both",
      },
    );
    const callCount = animations.length;

    await act(async () => {
      finishResolvers[settleIndex]();
      await animations[settleIndex].finished;
    });
    expect(Element.prototype.animate).toHaveBeenCalledTimes(callCount);
  });

  it("does not let an unfinished settle clear a newer working loop", async () => {
    const { rerender } = render(<MotionHarness motionState="waiting" />);
    rerender(<MotionHarness motionState="idle" />);

    const settleAnimation = animations[1];
    rerender(<MotionHarness motionState="working" />);
    const replacementAnimation = animations.at(-1)!;

    await act(async () => {
      finishResolvers[1]();
      await settleAnimation.finished;
    });

    expect(settleAnimation.cancel).toHaveBeenCalledOnce();
    expect(replacementAnimation.cancel).not.toHaveBeenCalled();
  });

  it("always uses both fill while preserving track timing", () => {
    const fillProgram: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        ...PROGRAM.working[0],
        options: {
          duration: 3_000,
          iterations: Infinity,
          easing: "ease-in-out",
          fill: "none",
        },
      }],
      waiting: [],
    };

    render(<MotionHarness motionState="working" program={fillProgram} />);

    expect(Element.prototype.animate).toHaveBeenCalledWith(
      fillProgram.working[0].keyframes,
      {
        duration: 3_000,
        iterations: Infinity,
        easing: "ease-in-out",
        fill: "both",
      },
    );
  });

  it("cancels every owned animation on unmount", () => {
    const removeDocumentListener = vi.spyOn(document, "removeEventListener");
    const { rerender, unmount } = render(<MotionHarness motionState="working" />);
    rerender(<MotionHarness motionState="waiting" />);
    rerender(<MotionHarness motionState="idle" />);

    unmount();

    expect(animations).toHaveLength(5);
    for (const animation of animations) {
      expect(animation.cancel).toHaveBeenCalled();
    }
    expect(mediaListeners.size).toBe(0);
    expect(removeDocumentListener).toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    );
    expect(mediaQueryList.removeEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );
  });

  it("skips a track whose data-part descendant is missing", () => {
    const missingPartProgram: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [{
        ...PROGRAM.working[0],
        part: "absent",
      }],
      waiting: [],
    };

    expect(() => render(
      <MotionHarness motionState="working" program={missingPartProgram} />,
    )).not.toThrow();
    expect(animations).toHaveLength(0);
  });

  it("skips a missing waiting target during handoff and loop start", async () => {
    const missingWaitingProgram: AgentRoleMotionProgram = {
      workingEntryTimeMs: 220,
      working: [PROGRAM.working[0]],
      waiting: [{
        ...PROGRAM.waiting[0],
        part: "absent",
      }],
    };
    const { rerender } = render(
      <MotionHarness motionState="working" program={missingWaitingProgram} />,
    );
    await completeWorkingEntry();
    rerender(
      <MotionHarness motionState="waiting" program={missingWaitingProgram} />,
    );

    const settleIndex = activeAnimationIndicesWithDuration(180)[0];
    expect(animations).toHaveLength(4);
    await act(async () => {
      finishResolvers[settleIndex]();
      await animations[settleIndex].finished;
    });
    expect(animations).toHaveLength(4);
    expect(Element.prototype.animate).toHaveBeenCalledTimes(4);
  });

  it("pauses while hidden and resumes when the motion state remains active", () => {
    render(<MotionHarness motionState="working" />);
    const workingAnimation = animations[1];

    act(() => {
      hidden = true;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(workingAnimation.pause).toHaveBeenCalledOnce();

    act(() => {
      hidden = false;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(workingAnimation.play).toHaveBeenCalledOnce();
  });

  it.each(["working", "waiting"] as const)(
    "resumes and completes a hidden idle settle entered from %s",
    async (initialState) => {
      const { rerender } = render(<MotionHarness motionState={initialState} />);
      const activeAnimation = animations.at(-1)!;

      act(() => {
        hidden = true;
        document.dispatchEvent(new Event("visibilitychange"));
      });
      rerender(<MotionHarness motionState="idle" />);
      const settleIndex = activeAnimationIndicesWithDuration(180)[0];
      const settleAnimation = animations[settleIndex];
      expect(settleAnimation.pause).toHaveBeenCalledOnce();

      act(() => {
        hidden = false;
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(settleAnimation.play).toHaveBeenCalledOnce();

      await act(async () => {
        finishResolvers[settleIndex]();
        await settleAnimation.finished;
      });
      expect(settleAnimation.cancel).toHaveBeenCalledOnce();
      expect(activeAnimation.play).not.toHaveBeenCalled();
      expect(Element.prototype.animate).toHaveBeenCalledTimes(
        initialState === "working" ? 3 : 2,
      );
    },
  );

  it("does not revive an idle loop on visibility restore", () => {
    const { rerender } = render(<MotionHarness motionState="working" />);
    act(() => {
      hidden = true;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    rerender(<MotionHarness motionState="idle" />);
    const settleAnimation = animations.at(-1)!;

    act(() => {
      hidden = false;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(settleAnimation.play).toHaveBeenCalledOnce();
    expect(animations[1].play).not.toHaveBeenCalled();
  });

  it("keeps a working-to-waiting handoff paused while hidden and resumes it", () => {
    const { rerender } = render(<MotionHarness motionState="working" />);

    act(() => {
      hidden = true;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    rerender(<MotionHarness motionState="waiting" />);
    const handoffAnimation = animations.at(-1)!;
    expect(handoffAnimation.pause).toHaveBeenCalledOnce();

    act(() => {
      hidden = false;
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(handoffAnimation.play).toHaveBeenCalledOnce();
  });

  it("does not create work or wait animations when reduced motion is already preferred", () => {
    mediaQueryList.matches = true;
    const { rerender } = render(<MotionHarness motionState="working" />);
    rerender(<MotionHarness motionState="waiting" />);

    expect(animations).toHaveLength(0);
  });

  it("does not create a controller or global listeners for a never-active idle SVG", () => {
    const addDocumentListener = vi.spyOn(document, "addEventListener");

    const { unmount } = render(<MotionHarness motionState="idle" />);

    expect(window.matchMedia).not.toHaveBeenCalled();
    expect(addDocumentListener).not.toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    );
    expect(mediaQueryList.addEventListener).not.toHaveBeenCalled();
    expect(animations).toHaveLength(0);
    unmount();
  });

  it("releases listeners after idle settle and recreates them for later work", async () => {
    const addDocumentListener = vi.spyOn(document, "addEventListener");
    const removeDocumentListener = vi.spyOn(document, "removeEventListener");
    const { rerender } = render(<MotionHarness motionState="working" />);
    await completeWorkingEntry();

    rerender(<MotionHarness motionState="idle" />);
    const settleIndex = activeAnimationIndicesWithDuration(180)[0];
    await act(async () => {
      finishResolvers[settleIndex]();
      await animations[settleIndex].finished;
    });

    expect(removeDocumentListener).toHaveBeenCalledWith(
      "visibilitychange",
      expect.any(Function),
    );
    expect(mediaQueryList.removeEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function),
    );

    const listenerAdds = addDocumentListener.mock.calls.filter(
      ([type]) => type === "visibilitychange",
    ).length;
    rerender(<MotionHarness motionState="working" />);
    expect(addDocumentListener.mock.calls.filter(
      ([type]) => type === "visibilitychange",
    )).toHaveLength(listenerAdds + 1);
    expect(mediaQueryList.addEventListener).toHaveBeenCalledTimes(2);
    expect(activeAnimationIndicesWithDuration(220)).toHaveLength(1);
  });

  it("cancels active motion when reduced motion becomes preferred", () => {
    const { rerender } = render(<MotionHarness motionState="working" />);
    const entryAnimation = animations[1];

    act(() => setReducedMotion(true));
    expect(entryAnimation.cancel).toHaveBeenCalledOnce();

    rerender(<MotionHarness motionState="waiting" />);
    expect(animations).toHaveLength(2);
  });
});
