import { useId, useLayoutEffect, useRef, type RefObject } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
  AgentRoleMotionTrack,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";
import { SceneDesignerArtwork } from "./SceneDesignerArtwork.tsx";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const SCENE_DURATION_MS = 2_600;
const INTERVAL_EASING = "cubic-bezier(0.77, 0, 0.175, 1)";
const EXIT_EASING = "cubic-bezier(0.23, 1, 0.32, 1)";
const SCAN_OFFSETS = [
  0,
  120 / SCENE_DURATION_MS,
  1_940 / SCENE_DURATION_MS,
  2_120 / SCENE_DURATION_MS,
  1,
] as const;
const SCAN_TRANSFORMS = [
  "translateY(0px)",
  "translateY(0px)",
  "translateY(368px)",
  "translateY(368px)",
  "translateY(368px)",
] as const;
const MASK_TRANSFORMS = [
  "translateY(0px)",
  "translateY(0px)",
  "translateY(368px)",
  "translateY(392px)",
  "translateY(392px)",
] as const;
const PREPARED_WORKING_POSE = [
  ["scene-reveal", "transform", "translateY(0px)"],
  ["construction-hide", "transform", "translateY(0px)"],
  ["scene-scan", "transform", "translateY(0px)"],
  ["scene-scan", "opacity", "1"],
] as const;

function sceneTrack(
  part: "scene-reveal" | "construction-hide" | "scene-scan",
  opacities: readonly number[],
  transforms: readonly string[] = SCAN_TRANSFORMS,
): AgentRoleMotionTrack {
  return {
    part,
    keyframes: SCAN_OFFSETS.map((offset, index) => ({
      offset,
      opacity: opacities[index],
      transform: transforms[index],
      ...(index === 0 ? { easing: EXIT_EASING } : {}),
      ...(index === 1 ? { easing: INTERVAL_EASING } : {}),
      ...(index === 2 ? { easing: EXIT_EASING } : {}),
    })),
    options: {
      duration: SCENE_DURATION_MS,
      iterations: 1,
      easing: "linear",
      fill: "forwards",
    },
  };
}

const SCENE_ACCENT_TRACK: AgentRoleMotionTrack = {
  part: "scene-accent",
  keyframes: [{ opacity: 0.78 }, { opacity: 1 }, { opacity: 0.78 }],
  options: { duration: 2_800, iterations: Infinity, easing: INTERVAL_EASING, fill: "both" },
};

export const SCENE_DESIGNER_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 120,
  workingTransitionDurationMs: 120,
  working: [
    sceneTrack("scene-reveal", [1, 1, 1, 1, 1], MASK_TRANSFORMS),
    sceneTrack("construction-hide", [1, 1, 1, 1, 1], MASK_TRANSFORMS),
    sceneTrack("scene-scan", [0, 1, 1, 0, 0]),
    SCENE_ACCENT_TRACK,
  ],
  waiting: [],
};

interface SceneDesignerAnimationProps {
  motionState: AgentRoleMotionState;
}

function clearPreparedWorkingPose(root: SVGSVGElement): void {
  for (const [part, property] of PREPARED_WORKING_POSE) {
    root.querySelector<SVGGraphicsElement>(`[data-part="${part}"]`)
      ?.style.removeProperty(property);
  }
}

function usePreparedWorkingPose(
  rootRef: RefObject<SVGSVGElement | null>,
  motionState: AgentRoleMotionState,
): void {
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root || motionState !== "working") return undefined;
    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const syncPose = (): void => {
      clearPreparedWorkingPose(root);
      if (mediaQuery.matches) return;
      for (const [part, property, value] of PREPARED_WORKING_POSE) {
        root.querySelector<SVGGraphicsElement>(`[data-part="${part}"]`)
          ?.style.setProperty(property, value);
      }
    };
    syncPose();
    mediaQuery.addEventListener("change", syncPose);
    return () => {
      mediaQuery.removeEventListener("change", syncPose);
      clearPreparedWorkingPose(root);
    };
  }, [motionState, rootRef]);
}

export default function SceneDesignerAnimation({
  motionState,
}: SceneDesignerAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const idPrefix = useId().replaceAll(":", "");
  usePreparedWorkingPose(rootRef, motionState);
  useAgentRoleMotion(rootRef, motionState, SCENE_DESIGNER_MOTION_PROGRAM);

  return (
    <svg ref={rootRef} viewBox="0 0 512 512" aria-hidden="true" data-agent-role="scene-designer" xmlns="http://www.w3.org/2000/svg">
      <SceneDesignerArtwork idPrefix={idPrefix} />
    </svg>
  );
}
