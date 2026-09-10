import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createCanvasPreviewPrefetchScheduler,
  type CanvasPreviewCandidate,
} from "./canvasPreviewPrefetch.ts";

const candidate = (key: string, priority: "warm" | "idle"): CanvasPreviewCandidate => ({
  key,
  url: `/${key}.webp?v=${key}`,
  priority,
});

describe("canvasPreviewPrefetch scheduler", () => {
  afterEach(() => vi.useRealTimers());

  it("limits warm work to two and idle work to one", async () => {
    vi.useFakeTimers();
    const release: (() => void)[] = [];
    const preload = vi.fn(() => new Promise<void>((resolve) => release.push(resolve)));
    const scheduler = createCanvasPreviewPrefetchScheduler({ preload });

    scheduler.update([
      candidate("warm-1", "warm"),
      candidate("warm-2", "warm"),
      candidate("warm-3", "warm"),
      candidate("idle-1", "idle"),
      candidate("idle-2", "idle"),
    ]);
    await vi.runOnlyPendingTimersAsync();
    expect(preload).toHaveBeenCalledTimes(3);

    release.splice(0).forEach((resolve) => resolve());
    await vi.runOnlyPendingTimersAsync();
    expect(preload).toHaveBeenCalledTimes(5);
    scheduler.dispose();
  });

  it("pauses idle work while preserving warm work and removes stale queued work", async () => {
    vi.useFakeTimers();
    const release: (() => void)[] = [];
    const preload = vi.fn(() => new Promise<void>((resolve) => release.push(resolve)));
    const scheduler = createCanvasPreviewPrefetchScheduler({ preload });
    scheduler.setPaused(true);
    scheduler.update([candidate("warm", "warm"), candidate("idle", "idle")]);
    await vi.runOnlyPendingTimersAsync();
    expect(preload).toHaveBeenCalledTimes(1);

    scheduler.update([candidate("warm", "warm"), candidate("new-idle", "idle")]);
    release.splice(0).forEach((resolve) => resolve());
    scheduler.setPaused(false);
    await vi.runOnlyPendingTimersAsync();
    expect(preload).toHaveBeenCalledWith("/new-idle.webp?v=new-idle", expect.anything());
    expect(preload).not.toHaveBeenCalledWith("/idle.webp?v=idle", expect.anything());
    scheduler.dispose();
  });

  it("starts the nearest queued preview before a farther candidate", async () => {
    const preload = vi.fn(async () => undefined);
    const scheduler = createCanvasPreviewPrefetchScheduler({ preload, warmConcurrency: 1, idleConcurrency: 1 });

    scheduler.update([
      { ...candidate("far", "warm"), distance: 900 },
      { ...candidate("near", "warm"), distance: 20 },
    ]);
    await Promise.resolve();

    expect(preload).toHaveBeenNthCalledWith(1, "/near.webp?v=near", "near");
    scheduler.dispose();
  });
});
