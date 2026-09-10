import { useEffect, useRef, type RefObject } from "react";
import type {
  AgentRoleMotionController,
  AgentRoleMotionProgram,
  AgentRoleMotionState,
  AgentRoleMotionTrack,
} from "./types.ts";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const WORKING_ENTRY_DURATION_MS = 220;
const WORKING_ENTRY_OPTIONS: KeyframeAnimationOptions = {
  duration: WORKING_ENTRY_DURATION_MS,
  easing: "cubic-bezier(.23, 1, .32, 1)",
  fill: "both",
};
const SETTLE_OPTIONS: KeyframeAnimationOptions = {
  duration: 180,
  easing: "cubic-bezier(.23, 1, .32, 1)",
  fill: "both",
};

interface OwnedAnimation {
  animation: Animation;
  part: SVGGraphicsElement;
}

interface ResolvedTrack {
  part: SVGGraphicsElement;
  track: AgentRoleMotionTrack;
}

export function createAgentRoleMotionController(
  root: SVGSVGElement,
  program: AgentRoleMotionProgram,
): AgentRoleMotionController {
  let animations: OwnedAnimation[] = [];
  let transitionGeneration = 0;
  let disposed = false;
  let paused = false;

  const cancelAnimations = (): void => {
    for (const { animation } of animations) {
      try {
        animation.cancel();
      } catch {
        // A broken WAAPI implementation must not strand the remaining batch.
      }
    }
    animations = [];
  };

  const createOwnedAnimations = <T extends { part: SVGGraphicsElement }>(
    entries: T[],
    create: (entry: T) => Animation,
    configure?: (animation: Animation) => void,
  ): OwnedAnimation[] | null => {
    const created: OwnedAnimation[] = [];
    animations = created;
    try {
      for (const entry of entries) {
        const animation = create(entry);
        created.push({ part: entry.part, animation });
        void animation.finished.catch(() => undefined);
        configure?.(animation);
      }
      return created;
    } catch {
      cancelAnimations();
      return null;
    }
  };

  const resolveTracks = (tracks: AgentRoleMotionTrack[]): ResolvedTrack[] => (
    tracks.flatMap((track) => {
      const part = root.querySelector<SVGGraphicsElement>(`[data-part="${track.part}"]`);
      if (!part || typeof part.animate !== "function") return [];
      return [{ part, track }];
    })
  );

  const startTracks = (
    tracks: AgentRoleMotionTrack[],
    currentTime?: number,
  ): boolean => {
    const started = createOwnedAnimations(
      resolveTracks(tracks),
      ({ part, track }) => part.animate(track.keyframes, {
        ...track.options,
        fill: "both",
      }),
      (animation) => {
        if (currentTime !== undefined) {
          animation.currentTime = currentTime;
        }
        if (paused) animation.pause();
      },
    );
    return started !== null;
  };

  const transitionToWorking = async (): Promise<void> => {
    try {
      if (disposed) return;

      const entryGeneration = ++transitionGeneration;
      const initialTracks = program.workingIntro?.length
        ? program.workingIntro
        : program.working;
      const resolvedWorkingTracks = resolveTracks(initialTracks);
      const activeParts = new Set(animations.map(({ part }) => part));
      const parts = [...new Set([
        ...activeParts,
        ...resolvedWorkingTracks.map(({ part }) => part),
      ])];
      for (const { animation } of animations) animation.pause();
      const activePoses = new Map(
        [...activeParts].map((part) => {
          const style = getComputedStyle(part);
          return [part, { transform: style.transform, opacity: style.opacity }];
        }),
      );
      cancelAnimations();

      if (disposed || entryGeneration !== transitionGeneration || parts.length === 0) return;

      const underlyingPoses = new Map(parts.map((part) => {
        const style = getComputedStyle(part);
        return [part, { transform: style.transform, opacity: style.opacity }];
      }));
      const previewAnimations = createOwnedAnimations(
        resolvedWorkingTracks,
        ({ part, track }) => part.animate(track.keyframes, {
          ...track.options,
          fill: "both",
        }),
        (animation) => {
          animation.pause();
          animation.currentTime = program.workingEntryTimeMs;
        },
      );
      if (!previewAnimations) return;
      const workingPoses = new Map(parts.map((part) => {
        const style = getComputedStyle(part);
        return [part, { transform: style.transform, opacity: style.opacity }];
      }));
      cancelAnimations();

      if (disposed || entryGeneration !== transitionGeneration) return;

      const entryAnimations = createOwnedAnimations(
        parts.map((part) => ({ part })),
        ({ part }) => part.animate([
          activePoses.get(part) ?? underlyingPoses.get(part)!,
          workingPoses.get(part)!,
        ], {
          ...WORKING_ENTRY_OPTIONS,
          duration: program.workingTransitionDurationMs
            ?? WORKING_ENTRY_DURATION_MS,
        }),
        (animation) => {
          if (paused) animation.pause();
        },
      );
      if (!entryAnimations) return;

      await Promise.allSettled(
        entryAnimations.map(({ animation }) => animation.finished),
      );

      if (disposed || entryGeneration !== transitionGeneration) return;

      cancelAnimations();
      if (!startTracks(initialTracks, program.workingEntryTimeMs)) return;
      if (initialTracks === program.working) return;

      // The controller retains ownership across the first-pass/loop seam, including
      // hidden-page pauses and interruption by Waiting, Idle, or disposal.
      await Promise.allSettled(animations.map(({ animation }) => animation.finished));
      if (disposed || entryGeneration !== transitionGeneration) return;
      cancelAnimations();
      startTracks(program.working, 0);
    } catch {
      cancelAnimations();
    }
  };

  const transitionToWaiting = async (): Promise<void> => {
    try {
      if (disposed) return;

      const handoffGeneration = ++transitionGeneration;
      if (animations.length === 0) {
        startTracks(program.waiting);
        return;
      }

      const resolvedWaitingTracks = resolveTracks(program.waiting);
      const activeParts = new Set(animations.map(({ part }) => part));
      const parts = [...new Set([
        ...activeParts,
        ...resolvedWaitingTracks.map(({ part }) => part),
      ])];
      for (const { animation } of animations) animation.pause();
      const activePoses = new Map(
        [...activeParts].map((part) => {
          const style = getComputedStyle(part);
          return [part, { transform: style.transform, opacity: style.opacity }];
        }),
      );
      cancelAnimations();

      if (disposed || handoffGeneration !== transitionGeneration) return;

      const underlyingPoses = new Map(parts.map((part) => {
        const style = getComputedStyle(part);
        return [part, { transform: style.transform, opacity: style.opacity }];
      }));

      const previewAnimations = createOwnedAnimations(
        resolvedWaitingTracks,
        ({ part, track }) => part.animate(track.keyframes, {
          ...track.options,
          fill: "both",
        }),
        (animation) => {
          animation.pause();
          animation.currentTime = 0;
        },
      );
      if (!previewAnimations) return;

      const waitingPoses = new Map(parts.map((part) => {
        const style = getComputedStyle(part);
        return [part, { transform: style.transform, opacity: style.opacity }];
      }));
      cancelAnimations();

      if (disposed || handoffGeneration !== transitionGeneration) return;

      const poses = parts.map((part) => ({
        part,
        from: activePoses.get(part) ?? underlyingPoses.get(part)!,
        to: waitingPoses.get(part)!,
      }));
      const handoffAnimations = createOwnedAnimations(
        poses,
        ({ part, from, to }) => part.animate([from, to], SETTLE_OPTIONS),
        (animation) => {
          if (paused) animation.pause();
        },
      );
      if (!handoffAnimations) return;

      await Promise.allSettled(
        handoffAnimations.map(({ animation }) => animation.finished),
      );

      if (disposed || handoffGeneration !== transitionGeneration) return;

      cancelAnimations();
      startTracks(program.waiting);
    } catch {
      cancelAnimations();
    }
  };

  return {
    playWorking(): void {
      void transitionToWorking();
    },

    playWaiting(): void {
      void transitionToWaiting();
    },

    async settle(): Promise<void> {
      try {
        if (disposed) return;

        const settleGeneration = ++transitionGeneration;
        const parts = [...new Set(animations.map(({ part }) => part))];

        for (const { animation } of animations) {
          animation.pause();
        }
        const activePoses = parts.map((part) => {
          const style = getComputedStyle(part);
          return {
            part,
            transform: style.transform,
            opacity: style.opacity,
          };
        });
        cancelAnimations();

        if (disposed || settleGeneration !== transitionGeneration) return;

        const underlyingPoses = new Map(parts.map((part) => {
          const style = getComputedStyle(part);
          return [part, { transform: style.transform, opacity: style.opacity }];
        }));

        if (disposed || settleGeneration !== transitionGeneration) return;

        const settleAnimations = createOwnedAnimations(
          activePoses,
          ({ part, transform, opacity }) => part.animate([
            { transform, opacity },
            underlyingPoses.get(part)!,
          ], SETTLE_OPTIONS),
          (animation) => {
            if (paused) animation.pause();
          },
        );
        if (!settleAnimations) return;

        await Promise.allSettled(
          settleAnimations.map(({ animation }) => animation.finished),
        );

        if (disposed || settleGeneration !== transitionGeneration) return;

        cancelAnimations();
      } catch {
        cancelAnimations();
      }
    },

    pause(): void {
      if (disposed) return;
      paused = true;
      for (const { animation } of animations) {
        if (animation.playState !== "paused") animation.pause();
      }
    },

    resume(): void {
      if (disposed) return;
      paused = false;
      for (const { animation } of animations) {
        if (animation.playState === "paused") {
          animation.play();
        }
      }
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      transitionGeneration += 1;
      cancelAnimations();
    },
  };
}

interface MotionRuntime {
  syncState(): void;
  dispose(): void;
}

export function useAgentRoleMotion(
  rootRef: RefObject<SVGSVGElement | null>,
  motionState: AgentRoleMotionState,
  program: AgentRoleMotionProgram,
): void {
  const motionStateRef = useRef(motionState);
  const runtimeRef = useRef<MotionRuntime | null>(null);
  motionStateRef.current = motionState;

  useEffect(() => {
    return () => {
      runtimeRef.current?.dispose();
      runtimeRef.current = null;
    };
  }, [program, rootRef]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || (motionState === "idle" && !runtimeRef.current)) return;

    if (!runtimeRef.current) {
      const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
      let controller: AgentRoleMotionController | null = null;
      let resumeIdleSettle = false;
      let syncGeneration = 0;
      let disposed = false;

      const ensureController = (): AgentRoleMotionController => {
        controller ??= createAgentRoleMotionController(root, program);
        return controller;
      };

      const releaseRuntime = (runtime: MotionRuntime): void => {
        if (runtimeRef.current !== runtime) return;
        runtimeRef.current = null;
        runtime.dispose();
      };

      const handleVisibilityChange = (): void => {
        if (document.hidden) {
          if (motionStateRef.current === "idle") resumeIdleSettle = true;
          controller?.pause();
          return;
        }

        if (!mediaQuery.matches && (
          motionStateRef.current !== "idle" || resumeIdleSettle
        )) {
          resumeIdleSettle = false;
          controller?.resume();
        }
      };

      const syncState = (): void => {
        const generation = ++syncGeneration;
        if (mediaQuery.matches) {
          resumeIdleSettle = false;
          controller?.dispose();
          controller = null;
          if (motionStateRef.current === "idle") releaseRuntime(runtime);
          return;
        }

        const activeController = ensureController();
        switch (motionStateRef.current) {
          case "working":
            resumeIdleSettle = false;
            activeController.playWorking();
            break;
          case "waiting":
            resumeIdleSettle = false;
            activeController.playWaiting();
            break;
          case "idle":
            resumeIdleSettle = document.hidden;
            void activeController.settle().then(() => {
              if (
                !disposed
                && generation === syncGeneration
                && motionStateRef.current === "idle"
                && controller === activeController
              ) {
                releaseRuntime(runtime);
              }
            });
            break;
        }

        if (document.hidden) activeController.pause();
      };

      const handleMotionPreferenceChange = (): void => {
        syncState();
      };

      const runtime: MotionRuntime = {
        syncState,
        dispose(): void {
          if (disposed) return;
          disposed = true;
          syncGeneration += 1;
          document.removeEventListener("visibilitychange", handleVisibilityChange);
          mediaQuery.removeEventListener("change", handleMotionPreferenceChange);
          controller?.dispose();
          controller = null;
        },
      };
      runtimeRef.current = runtime;
      document.addEventListener("visibilitychange", handleVisibilityChange);
      mediaQuery.addEventListener("change", handleMotionPreferenceChange);
    }

    runtimeRef.current.syncState();
  }, [motionState, program, rootRef]);
}
