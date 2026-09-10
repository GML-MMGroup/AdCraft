import { preloadCanvasPreviewPersistent } from "./canvasPreviewCache.ts";

export type CanvasPreviewPriority = "warm" | "idle";

export interface CanvasPreviewCandidate {
  key: string;
  url: string;
  priority: CanvasPreviewPriority;
  /** Screen-space distance from the current viewport center; lower is sooner. */
  distance?: number;
}

export interface CanvasPreviewPrefetchScheduler {
  update(candidates: readonly CanvasPreviewCandidate[]): void;
  setPaused(paused: boolean): void;
  dispose(): void;
}

interface SchedulerOptions {
  preload?: (url: string, cacheKey?: string) => Promise<void>;
  warmConcurrency?: number;
  idleConcurrency?: number;
}

export function createCanvasPreviewPrefetchScheduler(
  options: SchedulerOptions = {},
): CanvasPreviewPrefetchScheduler {
  const preload = options.preload ?? preloadCanvasPreviewPersistent;
  const warmConcurrency = Math.max(1, options.warmConcurrency ?? 2);
  const idleConcurrency = Math.max(1, options.idleConcurrency ?? 1);
  const queued = new Map<string, CanvasPreviewCandidate>();
  const running = new Map<string, CanvasPreviewPriority>();
  let paused = false;
  let disposed = false;

  const pump = () => {
    if (disposed) return;
    const start = (priority: CanvasPreviewPriority, limit: number) => {
      if (priority === "idle" && paused) return;
      const active = [...running.values()].filter((activePriority) => activePriority === priority).length;
      const available = Math.max(0, limit - active);
      const candidates = [...queued.values()]
        .filter((item) => item.priority === priority && !running.has(item.key))
        .sort((a, b) => (a.distance ?? Number.POSITIVE_INFINITY) - (b.distance ?? Number.POSITIVE_INFINITY))
        .slice(0, available);
      for (const item of candidates) {
        running.set(item.key, item.priority);
        void preload(item.url, item.key).catch(() => undefined).finally(() => {
          running.delete(item.key);
          if (queued.get(item.key)?.url === item.url) queued.delete(item.key);
          pump();
        });
      }
    };
    start("warm", warmConcurrency);
    start("idle", idleConcurrency);
  };

  return {
    update(candidates) {
      if (disposed) return;
      const next = new Map(candidates.map((item) => [item.key, item]));
      for (const key of queued.keys()) {
        if (!next.has(key) && !running.has(key)) queued.delete(key);
      }
      for (const item of candidates) {
        if (!running.has(item.key)) queued.set(item.key, item);
      }
      pump();
    },
    setPaused(nextPaused) {
      paused = nextPaused;
      pump();
    },
    dispose() {
      disposed = true;
      queued.clear();
      running.clear();
    },
  };
}
