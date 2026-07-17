import type { V2FinalCompositionTimeline } from "../../../types-v2.ts";
import { projectDefaultTimelineToShotLanes } from "./shotTimelineDomain.ts";
import { cloneV2Timeline } from "./v2TimelineModel.ts";

const HISTORY_LIMIT = 100;

export type ShotTimelineHistory = {
  past: V2FinalCompositionTimeline[];
  present: V2FinalCompositionTimeline;
  future: V2FinalCompositionTimeline[];
  coalesceKey: string | null;
};

export type SavedTimelineReconciliation = {
  baseline: V2FinalCompositionTimeline;
  draft: V2FinalCompositionTimeline;
};

export type TimelineConflictResolution = "keep-local" | "reload-remote";

export function createLoadedShotTimelineSession(timeline: V2FinalCompositionTimeline) {
  const baseline = cloneV2Timeline(timeline);
  const draft = projectDefaultTimelineToShotLanes(baseline);
  return { baseline, draft, history: createShotTimelineHistory(draft) };
}

export function createShotTimelineHistory(
  timeline: V2FinalCompositionTimeline,
): ShotTimelineHistory {
  return { past: [], present: timeline, future: [], coalesceKey: null };
}

export function commitShotTimelineHistory(
  history: ShotTimelineHistory,
  timeline: V2FinalCompositionTimeline,
  coalesceKey: string | null = null,
): ShotTimelineHistory {
  if (timelineEquals(history.present, timeline)) return history;
  const coalescing = coalesceKey !== null && coalesceKey === history.coalesceKey;
  const past = coalescing
    ? history.past
    : [...history.past, history.present].slice(-HISTORY_LIMIT);
  return { past, present: timeline, future: [], coalesceKey };
}

export function undoShotTimelineHistory(history: ShotTimelineHistory): ShotTimelineHistory {
  const previous = history.past.at(-1);
  if (!previous) return history;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
    coalesceKey: null,
  };
}

export function redoShotTimelineHistory(history: ShotTimelineHistory): ShotTimelineHistory {
  const next = history.future[0];
  if (!next) return history;
  return {
    past: [...history.past, history.present].slice(-HISTORY_LIMIT),
    present: next,
    future: history.future.slice(1),
    coalesceKey: null,
  };
}

export function reconcileSavedTimeline({
  requestDraft,
  responseTimeline,
  currentDraft,
}: {
  requestDraft: V2FinalCompositionTimeline;
  responseTimeline: V2FinalCompositionTimeline;
  currentDraft: V2FinalCompositionTimeline;
}): SavedTimelineReconciliation {
  return {
    baseline: responseTimeline,
    draft: timelineEquals(requestDraft, currentDraft) ? responseTimeline : currentDraft,
  };
}

export function resolveTimelineConflict({
  localDraft,
  remoteTimeline,
  resolution,
}: {
  localDraft: V2FinalCompositionTimeline;
  remoteTimeline: V2FinalCompositionTimeline;
  resolution: TimelineConflictResolution;
}): SavedTimelineReconciliation {
  return {
    baseline: remoteTimeline,
    draft: resolution === "keep-local" ? localDraft : remoteTimeline,
  };
}

export function createLatestSaveQueue<TSnapshot, TResult>(
  readSnapshot: () => TSnapshot | null,
  saveSnapshot: (snapshot: TSnapshot) => Promise<TResult>,
) {
  let requested = false;
  let running: Promise<TResult | null> | null = null;

  const drain = async () => {
    let latestResult: TResult | null = null;
    while (requested) {
      requested = false;
      const snapshot = readSnapshot();
      if (snapshot !== null) latestResult = await saveSnapshot(snapshot);
    }
    return latestResult;
  };

  return {
    request() {
      requested = true;
      if (!running) {
        const pending = drain();
        running = pending;
        void pending.then(
          () => {
            if (running === pending) running = null;
          },
          () => {
            if (running === pending) running = null;
          },
        );
      }
      return running;
    },
    isRunning() {
      return running !== null;
    },
  };
}

export function shotTimelineEquals(
  left: V2FinalCompositionTimeline | null,
  right: V2FinalCompositionTimeline | null,
) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function timelineEquals(left: V2FinalCompositionTimeline, right: V2FinalCompositionTimeline) {
  return left === right || shotTimelineEquals(left, right);
}
