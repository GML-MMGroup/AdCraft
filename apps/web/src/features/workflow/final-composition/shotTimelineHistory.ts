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
  if (timelineEquals(history.present, timeline)) return history;
  const coalescing = coalesceKey !== null && coalesceKey === history.coalesceKey;
  const past = coalescing
    ? history.past
    : [...history.past, history.present].slice(-HISTORY_LIMIT);
  return { past, present: timeline, future: [], coalesceKey };
}

export function finalizeShotTimelineHistory(history: ShotTimelineHistory): ShotTimelineHistory {
  return history.coalesceKey === null ? history : { ...history, coalesceKey: null };
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

export function createLatestSaveQueue<TSnapshot, TResult, TRequest = void>(
  readSnapshot: (request: TRequest) => TSnapshot | null,
  saveSnapshot: (snapshot: TSnapshot) => Promise<TResult>,
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
        const batch = requested;
        try {
          const latestRequest = waiters.findLast((waiter) => waiter.request <= batch)!;
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
