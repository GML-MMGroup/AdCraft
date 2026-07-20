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

export type TimelineSessionToken = {
  workflowId: string | null;
  generation: number;
};

export function createTimelineSessionGuard(initialWorkflowId: string | null = null) {
  let current: TimelineSessionToken = { workflowId: initialWorkflowId, generation: 0 };

  const capture = (): TimelineSessionToken => ({ ...current });
  return {
    capture,
    update(workflowId: string | null) {
      const changed = workflowId !== current.workflowId;
      if (changed) current = { workflowId, generation: current.generation + 1 };
      return { changed, token: capture() };
    },
    isCurrent(token: TimelineSessionToken) {
      return token.workflowId === current.workflowId && token.generation === current.generation;
    },
  };
}

export function createRemoteStateEpoch() {
  let epoch = 0;
  const advance = () => {
    epoch += 1;
    return epoch;
  };
  return {
    claim: advance,
    invalidate: advance,
    isCurrent(candidate: number) {
      return candidate === epoch;
    },
  };
}

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
  const current = history.coalesceKey !== null && history.coalesceKey !== coalesceKey
    ? finalizeShotTimelineHistory(history)
    : history;
  if (timelineEquals(current.present, timeline)) return current;
  const coalescing = coalesceKey !== null && coalesceKey === current.coalesceKey;
  const past = coalescing
    ? current.past
    : [...current.past, current.present];
  return {
    past: coalesceKey === null ? past.slice(-HISTORY_LIMIT) : past,
    present: timeline,
    future: coalesceKey === null ? [] : current.future,
    coalesceKey,
  };
}

export function finalizeShotTimelineHistory(history: ShotTimelineHistory): ShotTimelineHistory {
  if (history.coalesceKey === null) return history;
  const gestureOrigin = history.past.at(-1);
  return gestureOrigin && timelineEquals(gestureOrigin, history.present)
    ? { ...history, past: history.past.slice(0, -1), coalesceKey: null }
    : {
      ...history,
      past: history.past.slice(-HISTORY_LIMIT),
      future: [],
      coalesceKey: null,
    };
}

export function undoShotTimelineHistory(history: ShotTimelineHistory): ShotTimelineHistory {
  const current = finalizeShotTimelineHistory(history);
  const previous = current.past.at(-1);
  if (!previous) return current;
  return {
    past: current.past.slice(0, -1),
    present: previous,
    future: [current.present, ...current.future],
    coalesceKey: null,
  };
}

export function redoShotTimelineHistory(history: ShotTimelineHistory): ShotTimelineHistory {
  const current = finalizeShotTimelineHistory(history);
  const next = current.future[0];
  if (!next) return current;
  return {
    past: [...current.past, current.present].slice(-HISTORY_LIMIT),
    present: next,
    future: current.future.slice(1),
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

export function reconcileReloadedTimeline({
  requestDraft,
  remoteTimeline,
  currentDraft,
}: {
  requestDraft: V2FinalCompositionTimeline;
  remoteTimeline: V2FinalCompositionTimeline;
  currentDraft: V2FinalCompositionTimeline;
}): SavedTimelineReconciliation {
  return {
    baseline: remoteTimeline,
    draft: timelineEquals(requestDraft, currentDraft)
      ? remoteTimeline
      : mergeReloadEdits(requestDraft, currentDraft, remoteTimeline),
  };
}

export function rebaseReloadedShotTimelineHistory({
  history,
  requestDraft,
  remoteTimeline,
}: {
  history: ShotTimelineHistory;
  requestDraft: V2FinalCompositionTimeline;
  remoteTimeline: V2FinalCompositionTimeline;
}): ShotTimelineHistory {
  const requestIndex = findLastTimelineIndex(history.past, requestDraft);
  const rebase = (timeline: V2FinalCompositionTimeline) => reconcileReloadedTimeline({
    requestDraft,
    currentDraft: timeline,
    remoteTimeline,
  }).draft;

  if (requestIndex === -1) {
    const present = rebase(history.present);
    return timelineEquals(present, remoteTimeline)
      ? createShotTimelineHistory(remoteTimeline)
      : commitShotTimelineHistory(createShotTimelineHistory(remoteTimeline), present);
  }

  const retainedPast = history.past.slice(requestIndex + 1).map(rebase);
  const present = rebase(history.present);
  const hasRetainedHistory = retainedPast.length > 0 || !timelineEquals(present, remoteTimeline);
  const coalesceKey = hasRetainedHistory ? history.coalesceKey : null;
  const past = hasRetainedHistory ? [remoteTimeline, ...retainedPast] : [];
  return {
    past: past.slice(-(coalesceKey === null ? HISTORY_LIMIT : HISTORY_LIMIT + 1)),
    present,
    future: history.future.map(rebase),
    coalesceKey,
  };
}

export function createLatestSaveQueue<TSnapshot, TResult, TRequest = void>(
  readSnapshot: (request: TRequest) => TSnapshot | null,
  saveSnapshot: (snapshot: TSnapshot) => Promise<TResult>,
  sameContext: (left: TRequest, right: TRequest) => boolean = () => true,
) {
  type Waiter = {
    request: number;
    context: TRequest;
    resolve: (result: TResult | null) => void;
    reject: (error: unknown) => void;
  };
  let requested = 0;
  let processed = 0;
  let running = false;
  let waiters: Waiter[] = [];

  const drain = async () => {
    if (running) return;
    running = true;
    try {
      while (processed < requested) {
        const firstPending = waiters.find((waiter) => waiter.request > processed)!;
        const batchWaiters: Waiter[] = [];
        for (const waiter of waiters) {
          if (waiter.request <= processed) continue;
          if (batchWaiters.length > 0 && !sameContext(firstPending.context, waiter.context)) break;
          batchWaiters.push(waiter);
        }
        const latestRequest = batchWaiters.at(-1)!;
        const batch = latestRequest.request;
        try {
          const snapshot = readSnapshot(latestRequest.context);
          const result = snapshot === null ? null : await saveSnapshot(snapshot);
          processed = batch;
          const settled = waiters.filter((waiter) => waiter.request <= batch);
          waiters = waiters.filter((waiter) => waiter.request > batch);
          settled.forEach((waiter) => waiter.resolve(result));
        } catch (error) {
          processed = batch;
          const settled = waiters.filter((waiter) => waiter.request <= batch);
          waiters = waiters.filter((waiter) => waiter.request > batch);
          settled.forEach((waiter) => waiter.reject(error));
        }
      }
    } finally {
      running = false;
      if (processed < requested) void drain();
    }
  };

  return {
    request(...args: [TRequest] extends [void] ? [] : [context: TRequest]) {
      requested += 1;
      const request = requested;
      const context = args[0] as TRequest;
      const pending = new Promise<TResult | null>((resolve, reject) => {
        waiters.push({ request, context, resolve, reject });
      });
      void drain();
      return pending;
    },
    isRunning() {
      return running;
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

function findLastTimelineIndex(timelines: V2FinalCompositionTimeline[], candidate: V2FinalCompositionTimeline) {
  for (let index = timelines.length - 1; index >= 0; index -= 1) {
    if (timelineEquals(timelines[index], candidate)) return index;
  }
  return -1;
}

function mergeReloadEdits(
  requestDraft: V2FinalCompositionTimeline,
  currentDraft: V2FinalCompositionTimeline,
  remoteTimeline: V2FinalCompositionTimeline,
) {
  return mergeChangedValue(requestDraft, currentDraft, remoteTimeline) as V2FinalCompositionTimeline;
}

function mergeChangedValue(base: unknown, current: unknown, remote: unknown): unknown {
  if (shotTimelineEqualsValue(base, current)) return cloneMergeValue(remote);
  if (Array.isArray(base) && Array.isArray(current) && Array.isArray(remote)) {
    const entityKey = arrayEntityKey(base, current, remote);
    if (!entityKey) return cloneMergeValue(current);
    return mergeEntityArray(base, current, remote, entityKey);
  }
  if (isMergeRecord(base) && isMergeRecord(current) && isMergeRecord(remote)) {
    const result: Record<string, unknown> = {};
    const keys = new Set([...Object.keys(base), ...Object.keys(current), ...Object.keys(remote)]);
    for (const key of keys) {
      if (!(key in current) && key in base) continue;
      if (!(key in base) && key in current) {
        result[key] = cloneMergeValue(current[key]);
        continue;
      }
      result[key] = mergeChangedValue(base[key], current[key], remote[key]);
    }
    return result;
  }
  return cloneMergeValue(current);
}

function mergeEntityArray(
  base: unknown[],
  current: unknown[],
  remote: unknown[],
  key: string,
) {
  const baseById = new Map(base.map((item) => [mergeEntityId(item, key), item]));
  const currentById = new Map(current.map((item) => [mergeEntityId(item, key), item]));
  const remoteById = new Map(remote.map((item) => [mergeEntityId(item, key), item]));
  const result: unknown[] = [];

  for (const remoteItem of remote) {
    const id = mergeEntityId(remoteItem, key);
    const baseItem = baseById.get(id);
    const currentItem = currentById.get(id);
    if (baseItem !== undefined && currentItem === undefined) continue;
    result.push(baseItem === undefined || currentItem === undefined
      ? cloneMergeValue(remoteItem)
      : mergeChangedValue(baseItem, currentItem, remoteItem));
  }
  for (const currentItem of current) {
    const id = mergeEntityId(currentItem, key);
    if (!baseById.has(id) && !remoteById.has(id)) result.push(cloneMergeValue(currentItem));
    if (baseById.has(id) && !remoteById.has(id) && !shotTimelineEqualsValue(baseById.get(id), currentItem)) {
      result.push(cloneMergeValue(currentItem));
    }
  }
  return result;
}

function arrayEntityKey(...arrays: unknown[][]) {
  const values = arrays.flat();
  for (const key of ["clip_id", "track_id"]) {
    if (values.length > 0 && values.every((value) => isMergeRecord(value) && typeof value[key] === "string")) return key;
  }
  return null;
}

function mergeEntityId(value: unknown, key: string) {
  return (value as Record<string, unknown>)[key] as string;
}

function isMergeRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneMergeValue<T>(value: T): T {
  return value === undefined ? value : structuredClone(value);
}

function shotTimelineEqualsValue(left: unknown, right: unknown) {
  return left === right || JSON.stringify(left) === JSON.stringify(right);
}
