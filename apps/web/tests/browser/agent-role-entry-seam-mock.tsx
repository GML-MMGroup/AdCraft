import { useState } from "react";
import { createRoot } from "react-dom/client";

import BgmDirectorAnimation, {
  BGM_DIRECTOR_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/BgmDirectorAnimation.tsx";
import CharacterDesignerAnimation, {
  CHARACTER_DESIGNER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/CharacterDesignerAnimation.tsx";
import ProductDesignerAnimation, {
  PRODUCT_DESIGNER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/ProductDesignerAnimation.tsx";
import PropDesignerAnimation, {
  PROP_DESIGNER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/PropDesignerAnimation.tsx";
import QuickMediaAnimation, {
  QUICK_MEDIA_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/QuickMediaAnimation.tsx";
import SceneDesignerAnimation, {
  SCENE_DESIGNER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/SceneDesignerAnimation.tsx";
import ScriptWriterAnimation, {
  SCRIPT_WRITER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/ScriptWriterAnimation.tsx";
import StoryboardArtistAnimation, {
  STORYBOARD_ARTIST_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/StoryboardArtistAnimation.tsx";
import VideoDirectorAnimation, {
  VIDEO_DIRECTOR_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/VideoDirectorAnimation.tsx";
import WorldSettingAnimation, {
  WORLD_SETTING_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/WorldSettingAnimation.tsx";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
} from "../../src/features/agent-canvas/chat/agent-role-animation/types.ts";

const ROLE_DEFINITIONS = {
  world: {
    slug: "world-setting",
    component: WorldSettingAnimation,
    program: WORLD_SETTING_MOTION_PROGRAM,
  },
  product: {
    slug: "product-designer",
    component: ProductDesignerAnimation,
    program: PRODUCT_DESIGNER_MOTION_PROGRAM,
  },
  prop: {
    slug: "prop-designer",
    component: PropDesignerAnimation,
    program: PROP_DESIGNER_MOTION_PROGRAM,
  },
  character: {
    slug: "character-designer",
    component: CharacterDesignerAnimation,
    program: CHARACTER_DESIGNER_MOTION_PROGRAM,
  },
  scene: {
    slug: "scene-designer",
    component: SceneDesignerAnimation,
    program: SCENE_DESIGNER_MOTION_PROGRAM,
  },
  script: {
    slug: "script-writer",
    component: ScriptWriterAnimation,
    program: SCRIPT_WRITER_MOTION_PROGRAM,
  },
  storyboard: {
    slug: "storyboard-artist",
    component: StoryboardArtistAnimation,
    program: STORYBOARD_ARTIST_MOTION_PROGRAM,
  },
  video: {
    slug: "video-director",
    component: VideoDirectorAnimation,
    program: VIDEO_DIRECTOR_MOTION_PROGRAM,
  },
  bgm: {
    slug: "bgm-director",
    component: BgmDirectorAnimation,
    program: BGM_DIRECTOR_MOTION_PROGRAM,
  },
  quick: {
    slug: "quick-media",
    component: QuickMediaAnimation,
    program: QUICK_MEDIA_MOTION_PROGRAM,
  },
} as const;

type RoleName = keyof typeof ROLE_DEFINITIONS;

interface Pose {
  matrix: [number, number, number, number, number, number];
  opacity: number;
  rotation: number;
  scaleX: number;
  scaleY: number;
  x: number;
  y: number;
}

interface EntryProbeResult {
  activePart: string;
  maxOpacityDelta: number;
  maxRotationDelta: number;
  maxScaleXDelta: number;
  maxScaleYDelta: number;
  maxTranslationFinalPx: number;
  role: RoleName;
  sampleTimeMs: number;
}

interface ContinuityProbeResult {
  maxMatrixDelta: number;
  maxOpacityDelta: number;
  maxScaleXDelta: number;
  maxScaleYDelta: number;
  role: RoleName;
}

interface LoopStartObservation {
  entryAnimationCount: number;
  expectedPhaseMs: number;
  loopCount: number;
  maxInitialPhaseDeltaMs: number;
  maxObservedPhaseMs: number;
  minObservedPhaseMs: number;
  role: RoleName;
}

interface PendingContinuityProbe {
  entryEnd: Map<string, Pose>;
  loops: Animation[];
  parts: Map<string, SVGGraphicsElement>;
  program: AgentRoleMotionProgram;
  role: RoleName;
}

function readPose(part: SVGGraphicsElement): Pose {
  const style = getComputedStyle(part);
  const matrix = new DOMMatrixReadOnly(style.transform === "none" ? undefined : style.transform);
  return {
    matrix: [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f],
    x: matrix.e,
    y: matrix.f,
    rotation: Math.atan2(matrix.b, matrix.a) * 180 / Math.PI,
    scaleX: Math.hypot(matrix.a, matrix.b),
    scaleY: Math.hypot(matrix.c, matrix.d),
    opacity: Number(style.opacity),
  };
}

function poseDelta(before: Pose, after: Pose): Omit<EntryProbeResult, "activePart" | "role" | "sampleTimeMs"> {
  return {
    maxTranslationFinalPx: Math.hypot(after.x - before.x, after.y - before.y) / 16,
    maxRotationDelta: Math.abs(after.rotation - before.rotation),
    maxScaleXDelta: Math.abs(after.scaleX - before.scaleX),
    maxScaleYDelta: Math.abs(after.scaleY - before.scaleY),
    maxOpacityDelta: Math.abs(after.opacity - before.opacity),
  };
}

function scoreDelta(delta: ReturnType<typeof poseDelta>): number {
  return Math.max(
    delta.maxTranslationFinalPx / 0.125,
    delta.maxRotationDelta / 0.25,
    delta.maxScaleXDelta / 0.01,
    delta.maxScaleYDelta / 0.01,
    delta.maxOpacityDelta / 0.08,
  );
}

function findRoleSvg(role: RoleName): SVGSVGElement {
  const svg = document.querySelector<SVGSVGElement>(
    `[data-agent-role="${ROLE_DEFINITIONS[role].slug}"]`,
  );
  if (!svg) throw new Error(`Missing SVG for ${role}`);
  return svg;
}

function uniqueParts(root: SVGSVGElement, program: AgentRoleMotionProgram): Map<string, SVGGraphicsElement> {
  return new Map((program.workingIntro ?? program.working).map((track) => {
    const part = root.querySelector<SVGGraphicsElement>(`[data-part="${track.part}"]`);
    if (!part) throw new Error(`Missing ${track.part}`);
    return [track.part, part];
  }));
}

function sampleRole(role: RoleName, sampleTimeMs?: number): EntryProbeResult {
  const { program } = ROLE_DEFINITIONS[role];
  const time = sampleTimeMs ?? program.workingEntryTimeMs;
  const root = findRoleSvg(role);
  const parts = uniqueParts(root, program);
  const before = new Map([...parts].map(([name, part]) => [name, readPose(part)]));
  const animations = (program.workingIntro ?? program.working).map((track) => {
    const animation = parts.get(track.part)!.animate(track.keyframes, {
      ...track.options,
      fill: "both",
    });
    void animation.finished.catch(() => undefined);
    animation.pause();
    animation.currentTime = time;
    return animation;
  });
  const deltas = [...parts].map(([name, part]) => ({
    name,
    ...(() => {
      const delta = poseDelta(before.get(name)!, readPose(part));
      return part.dataset.motionMeasurement === "internal-clip"
        ? { ...delta, maxTranslationFinalPx: 0 }
        : delta;
    })(),
  }));
  for (const animation of animations) animation.cancel();
  const active = deltas.reduce((best, candidate) => (
    scoreDelta(candidate) > scoreDelta(best) ? candidate : best
  ));
  return {
    role,
    sampleTimeMs: time,
    activePart: active.name,
    maxTranslationFinalPx: Math.max(...deltas.map((delta) => delta.maxTranslationFinalPx)),
    maxRotationDelta: Math.max(...deltas.map((delta) => delta.maxRotationDelta)),
    maxScaleXDelta: Math.max(...deltas.map((delta) => delta.maxScaleXDelta)),
    maxScaleYDelta: Math.max(...deltas.map((delta) => delta.maxScaleYDelta)),
    maxOpacityDelta: Math.max(...deltas.map((delta) => delta.maxOpacityDelta)),
  };
}

let activateRole: (role: RoleName | null) => void = () => {
  throw new Error("Probe is not mounted");
};
let pendingContinuityProbe: PendingContinuityProbe | null = null;

function timingDuration(animation: Animation): number {
  return Number((animation.effect as KeyframeEffect | null)?.getTiming().duration);
}

async function waitFor<T>(label: string, read: () => T | null, timeoutMs = 1_000): Promise<T> {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    const result = read();
    if (result !== null) return result;
    await new Promise(requestAnimationFrame);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function observeLoopStart(role: RoleName): Promise<LoopStartObservation> {
  if (pendingContinuityProbe) throw new Error("Complete the pending continuity probe first");
  activateRole(role);
  const root = findRoleSvg(role);
  const { program } = ROLE_DEFINITIONS[role];
  const parts = uniqueParts(root, program);
  const entryDuration = program.workingTransitionDurationMs ?? 220;
  const entryAnimations = await waitFor(`${role} entry`, () => {
    const entries = root.getAnimations({ subtree: true }).filter(
      (animation) => timingDuration(animation) === entryDuration,
    );
    return entries.length > 0 ? entries : null;
  });
  for (const animation of entryAnimations) {
    animation.pause();
    animation.currentTime = entryDuration;
  }
  await new Promise(requestAnimationFrame);
  const entryEnd = new Map([...parts].map(([name, part]) => [name, readPose(part)]));
  const nativeAnimate = Element.prototype.animate;
  const loopStarts: Array<{ animation: Animation; currentTime: number }> = [];
  Element.prototype.animate = function captureLoopStart(keyframes, options) {
    const animation = nativeAnimate.call(this, keyframes, options);
    if (root.contains(this)) {
      queueMicrotask(() => {
        loopStarts.push({
          animation,
          currentTime: Number(animation.currentTime),
        });
        animation.pause();
      });
    }
    return animation;
  };
  try {
    for (const animation of entryAnimations) animation.finish();
    await waitFor(`${role} loop capture`, () => (
      loopStarts.length === (program.workingIntro ?? program.working).length ? true : null
    ));
  } finally {
    Element.prototype.animate = nativeAnimate;
  }
  const observedTimes = loopStarts.map(({ currentTime }) => currentTime);
  const loops = loopStarts.map(({ animation }) => animation);
  pendingContinuityProbe = { entryEnd, loops, parts, program, role };
  return {
    role,
    entryAnimationCount: entryAnimations.length,
    loopCount: loops.length,
    expectedPhaseMs: program.workingEntryTimeMs,
    minObservedPhaseMs: Math.min(...observedTimes),
    maxObservedPhaseMs: Math.max(...observedTimes),
    maxInitialPhaseDeltaMs: Math.max(...observedTimes.map((time) => (
      Math.abs(time - program.workingEntryTimeMs)
    ))),
  };
}

async function compareEntryAndLoopPose(role: RoleName): Promise<ContinuityProbeResult> {
  const pending = pendingContinuityProbe;
  if (!pending || pending.role !== role) throw new Error(`No pending continuity probe for ${role}`);
  const { entryEnd, loops, parts, program } = pending;
  for (const animation of loops) animation.currentTime = program.workingEntryTimeMs;
  await new Promise(requestAnimationFrame);
  const loopStart = new Map([...parts].map(([name, part]) => [name, readPose(part)]));
  const matrixDeltas = [...parts].map(([name]) => {
    const before = entryEnd.get(name)!;
    const after = loopStart.get(name)!;
    return Math.max(...after.matrix.map((component, index) => (
      Math.abs(component - before.matrix[index])
    )));
  });
  const scaleXDeltas = [...parts].map(([name]) => (
    Math.abs(loopStart.get(name)!.scaleX - entryEnd.get(name)!.scaleX)
  ));
  const scaleYDeltas = [...parts].map(([name]) => (
    Math.abs(loopStart.get(name)!.scaleY - entryEnd.get(name)!.scaleY)
  ));
  const opacityDeltas = [...parts].map(([name]) => (
    Math.abs(loopStart.get(name)!.opacity - entryEnd.get(name)!.opacity)
  ));
  pendingContinuityProbe = null;
  activateRole(null);
  await waitFor(`${role} idle cleanup`, () => (
    document.getAnimations().length === 0 ? true : null
  ));
  return {
    role,
    maxMatrixDelta: Math.max(...matrixDeltas),
    maxOpacityDelta: Math.max(...opacityDeltas),
    maxScaleXDelta: Math.max(...scaleXDeltas),
    maxScaleYDelta: Math.max(...scaleYDeltas),
  };
}

function App() {
  const [active, setActive] = useState<RoleName | null>(null);
  activateRole = setActive;
  return Object.entries(ROLE_DEFINITIONS).map(([name, definition]) => {
    const Component = definition.component;
    const motionState: AgentRoleMotionState = active === name ? "working" : "idle";
    return (
      <div key={name} data-probe-role={name}>
        <Component motionState={motionState} />
      </div>
    );
  });
}

Object.assign(window, {
  agentRoleEntryProbe: {
    roleNames: Object.keys(ROLE_DEFINITIONS) as RoleName[],
    sampleRole,
    observeLoopStart,
    compareEntryAndLoopPose,
  },
});

createRoot(document.getElementById("root")!).render(<App />);
