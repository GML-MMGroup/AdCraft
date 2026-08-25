import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createVideoFrameSampler,
  frameCacheKey,
  frameSampleTimes,
  useVideoFrameStrip,
  VIDEO_FRAME_SEEK_TIMEOUT_MS,
} from "./useVideoFrameStrip.ts";

function frameRequest(overrides: Partial<Parameters<typeof useVideoFrameStrip>[0]> = {}) {
  return {
    assetId: "asset-test",
    mediaUrl: "https://cdn.example.test/video.mp4",
    previewUrl: "https://cdn.example.test/preview.jpg",
    sourceStart: 0,
    sourceEnd: 2,
    renderedWidth: 160,
    active: true,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function setDocumentHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
  document.dispatchEvent(new Event("visibilitychange"));
}

function mockVideoFrameEnvironment(options: {
  currentTime: number;
  duration?: number;
  throwOnSeek?: boolean;
  dispatchSeeked?: boolean;
}) {
  const nativeCreateElement = document.createElement.bind(document);
  const video = nativeCreateElement("video");
  let currentTime = options.currentTime;
  let currentTimeAssignments = 0;
  let seekedListenerCount = 0;
  let seekListenerAttachedBeforeSet = false;
  const addEventListener = video.addEventListener.bind(video);

  video.addEventListener = ((eventType: string, listener: EventListenerOrEventListenerObject, listenerOptions?: boolean | AddEventListenerOptions) => {
    if (eventType === "seeked") seekedListenerCount += 1;
    addEventListener(eventType, listener, listenerOptions);
  }) as typeof video.addEventListener;

  Object.defineProperty(video, "readyState", { configurable: true, value: 2 });
  Object.defineProperty(video, "duration", { configurable: true, value: options.duration ?? 10 });
  Object.defineProperty(video, "currentTime", {
    configurable: true,
    get: () => currentTime,
    set: (value: number) => {
      seekListenerAttachedBeforeSet = seekListenerAttachedBeforeSet || seekedListenerCount > 0;
      if (options.throwOnSeek) throw new Error("seek rejected");
      currentTimeAssignments += 1;
      currentTime = value;
      if (options.dispatchSeeked !== false) video.dispatchEvent(new Event("seeked"));
    },
  });
  video.load = vi.fn();
  video.pause = vi.fn();

  vi.spyOn(document, "createElement").mockImplementation(((tagName: string, elementOptions?: ElementCreationOptions) => (
    tagName === "video" ? video : nativeCreateElement(tagName, elementOptions)
  )) as typeof document.createElement);
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage,
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(new Blob(["frame"])));
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:frame"),
    revokeObjectURL: vi.fn(),
  });

  return {
    video,
    drawImage,
    currentTimeAssignments: () => currentTimeAssignments,
    seekListenerAttachedBeforeSet: () => seekListenerAttachedBeforeSet,
  };
}

afterEach(() => {
  delete (document as Document & { hidden?: boolean }).hidden;
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useVideoFrameStrip", () => {
  it("places frame requests at fixed-width cell midpoints", () => {
    expect(frameSampleTimes({
      start: 2,
      end: 8,
      renderedWidth: 480,
      targetFrameWidth: 80,
    })).toEqual([2.5, 3.5, 4.5, 5.5, 6.5, 7.5]);
  });

  it("rounds frame cache keys to centiseconds", () => {
    expect(frameCacheKey("asset-1", 2.504, 80, 45)).toBe("asset-1:2.50:80x45");
  });

  it("reuses cached samples for a later matching request", async () => {
    const request = {
      assetId: "asset-cache-reuse",
      mediaUrl: "https://cdn.example.test/video.mp4",
      previewUrl: "https://cdn.example.test/preview.jpg",
      sourceStart: 0,
      sourceEnd: 2,
      renderedWidth: 160,
      active: true,
    };
    const firstSampler = vi.fn(async (_url: string, seconds: number) => `blob:first-${seconds}`);
    const first = renderHook(() => useVideoFrameStrip(request, firstSampler));

    await waitFor(() => expect(first.result.current).toEqual([
      { sourceSeconds: 0.5, url: "blob:first-0.5", sampled: true },
      { sourceSeconds: 1.5, url: "blob:first-1.5", sampled: true },
    ]));
    first.unmount();

    const secondSampler = vi.fn(async () => "blob:unexpected");
    const second = renderHook(() => useVideoFrameStrip(request, secondSampler));

    expect(second.result.current).toEqual([
      { sourceSeconds: 0.5, url: "blob:first-0.5", sampled: true },
      { sourceSeconds: 1.5, url: "blob:first-1.5", sampled: true },
    ]);
    expect(secondSampler).not.toHaveBeenCalled();
  });

  it("keeps every requested frame on the preview when sampling fails", async () => {
    const previewUrl = "https://cdn.example.test/preview.jpg";
    const rejectingSampler = vi.fn(async () => {
      throw new Error("video decode failed");
    });
    const { result } = renderHook(() => useVideoFrameStrip({
      assetId: "asset-fallback",
      mediaUrl: "https://cdn.example.test/video.mp4",
      previewUrl,
      sourceStart: 2,
      sourceEnd: 8,
      renderedWidth: 480,
      active: true,
    }, rejectingSampler));

    await waitFor(() => expect(rejectingSampler).toHaveBeenCalledTimes(6));
    expect(result.current).toEqual([
      { sourceSeconds: 2.5, url: previewUrl, sampled: false },
      { sourceSeconds: 3.5, url: previewUrl, sampled: false },
      { sourceSeconds: 4.5, url: previewUrl, sampled: false },
      { sourceSeconds: 5.5, url: previewUrl, sampled: false },
      { sourceSeconds: 6.5, url: previewUrl, sampled: false },
      { sourceSeconds: 7.5, url: previewUrl, sampled: false },
    ]);
  });

  it("keeps null preview fallbacks renderable without inventing an empty URL", () => {
    const { result } = renderHook(() => useVideoFrameStrip(frameRequest({
      assetId: "asset-null-preview",
      previewUrl: null,
      active: false,
    })));

    expect(result.current).toEqual([
      { sourceSeconds: 0.5, url: null, sampled: false },
      { sourceSeconds: 1.5, url: null, sampled: false },
    ]);
  });

  it("aborts the active sampler when the hook unmounts", async () => {
    const aborted = vi.fn();
    const sampler = vi.fn((_url: string, _seconds: number, signal: AbortSignal) => new Promise<string>((_resolve, reject) => {
      signal.addEventListener("abort", () => {
        aborted();
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }));
    const hook = renderHook(() => useVideoFrameStrip(frameRequest({ assetId: "asset-unmount" }), sampler));

    await waitFor(() => expect(sampler).toHaveBeenCalledTimes(1));
    hook.unmount();
    await waitFor(() => expect(aborted).toHaveBeenCalledTimes(1));
  });

  it("does not let an abandoned request overwrite a replacement request", async () => {
    const first = deferred<string>();
    const aborted = vi.fn();
    const sampler = vi.fn((_url: string, seconds: number, signal: AbortSignal) => {
      if (seconds >= 2) return Promise.resolve(`blob:replacement-${seconds}`);
      signal.addEventListener("abort", aborted, { once: true });
      return first.promise;
    });
    const hook = renderHook(
      ({ request }) => useVideoFrameStrip(request, sampler),
      { initialProps: { request: frameRequest({ assetId: "asset-request-change" }) } },
    );

    await waitFor(() => expect(sampler).toHaveBeenCalledTimes(1));
    hook.rerender({ request: frameRequest({
      assetId: "asset-request-change",
      sourceStart: 2,
      sourceEnd: 4,
    }) });
    await waitFor(() => expect(aborted).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(hook.result.current).toEqual([
      { sourceSeconds: 2.5, url: "blob:replacement-2.5", sampled: true },
      { sourceSeconds: 3.5, url: "blob:replacement-3.5", sampled: true },
    ]));

    first.resolve("blob:stale");
    await Promise.resolve();
    expect(hook.result.current).toEqual([
      { sourceSeconds: 2.5, url: "blob:replacement-2.5", sampled: true },
      { sourceSeconds: 3.5, url: "blob:replacement-3.5", sampled: true },
    ]);
  });

  it("aborts hidden sampling and starts a fresh request when visible", async () => {
    const aborted = vi.fn();
    let callCount = 0;
    const sampler = vi.fn((_url: string, seconds: number, signal: AbortSignal) => {
      callCount += 1;
      if (callCount > 1) return Promise.resolve(`blob:visible-${seconds}`);
      return new Promise<string>((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          aborted();
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    });
    const { result } = renderHook(() => useVideoFrameStrip(frameRequest({ assetId: "asset-visibility" }), sampler));

    await waitFor(() => expect(sampler).toHaveBeenCalledTimes(1));
    setDocumentHidden(true);
    await waitFor(() => expect(aborted).toHaveBeenCalledTimes(1));

    setDocumentHidden(false);
    await waitFor(() => expect(result.current).toEqual([
      { sourceSeconds: 0.5, url: "blob:visible-0.5", sampled: true },
      { sourceSeconds: 1.5, url: "blob:visible-1.5", sampled: true },
    ]));
  });

  it("deduplicates concurrent sampling for the same frame cache key", async () => {
    const sample = deferred<string>();
    const sampler = vi.fn(() => sample.promise);
    const request = frameRequest({ assetId: "asset-deduplicated", renderedWidth: 80 });
    const first = renderHook(() => useVideoFrameStrip(request, sampler));
    const second = renderHook(() => useVideoFrameStrip(request, sampler));

    await waitFor(() => expect(sampler).toHaveBeenCalledTimes(1));
    sample.resolve("blob:deduplicated");
    await waitFor(() => expect(first.result.current).toEqual([
      { sourceSeconds: 1, url: "blob:deduplicated", sampled: true },
    ]));
    expect(second.result.current).toEqual([
      { sourceSeconds: 1, url: "blob:deduplicated", sampled: true },
    ]);
  });

  it("revokes unreferenced blob URLs when the bounded cache evicts them", async () => {
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: vi.fn(), revokeObjectURL });
    const sampler = vi.fn(async (_url: string, seconds: number) => `blob:eviction-${seconds}`);

    for (let batch = 0; batch < 11; batch += 1) {
      const hook = renderHook(() => useVideoFrameStrip(frameRequest({
        assetId: "asset-eviction",
        sourceStart: batch * 12,
        sourceEnd: (batch + 1) * 12,
        renderedWidth: 960,
      }), sampler));
      await waitFor(() => expect(hook.result.current.every((sample) => sample.sampled)).toBe(true));
      hook.unmount();
    }

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:eviction-0.5");
  });

  it("subscribes for seek completion before assigning a new currentTime", async () => {
    const media = mockVideoFrameEnvironment({ currentTime: 0 });
    const sampler = createVideoFrameSampler("https://cdn.example.test/video.mp4");
    const controller = new AbortController();
    const frame = sampler.sample("https://cdn.example.test/video.mp4", 1, controller.signal);

    media.video.dispatchEvent(new Event("loadedmetadata"));
    await expect(frame).resolves.toBe("blob:frame");
    expect(media.seekListenerAttachedBeforeSet()).toBe(true);
    sampler.dispose();
  });

  it("extracts an already-current ready frame without waiting for seeked", async () => {
    const media = mockVideoFrameEnvironment({ currentTime: 1 });
    const sampler = createVideoFrameSampler("https://cdn.example.test/video.mp4");
    const controller = new AbortController();
    const frame = sampler.sample("https://cdn.example.test/video.mp4", 1, controller.signal);

    media.video.dispatchEvent(new Event("loadedmetadata"));
    await expect(frame).resolves.toBe("blob:frame");
    expect(media.seekListenerAttachedBeforeSet()).toBe(false);
    sampler.dispose();
  });

  it("waits for delayed seeked before extracting a newly assigned frame", async () => {
    const media = mockVideoFrameEnvironment({ currentTime: 0, dispatchSeeked: false });
    const sampler = createVideoFrameSampler("https://cdn.example.test/video.mp4");
    const controller = new AbortController();
    const frame = sampler.sample("https://cdn.example.test/video.mp4", 1, controller.signal);

    media.video.dispatchEvent(new Event("loadedmetadata"));
    await waitFor(() => expect(media.currentTimeAssignments()).toBe(1));
    expect(media.drawImage).not.toHaveBeenCalled();

    media.video.dispatchEvent(new Event("seeked"));
    await expect(frame).resolves.toBe("blob:frame");
    expect(media.drawImage).toHaveBeenCalledTimes(1);
    sampler.dispose();
  });

  it("falls back after a newly assigned seek times out without drawing a frame", async () => {
    vi.useFakeTimers();
    const media = mockVideoFrameEnvironment({ currentTime: 0, dispatchSeeked: false });
    const { result } = renderHook(() => useVideoFrameStrip(frameRequest({
      assetId: "asset-seek-timeout",
      renderedWidth: 80,
    })));

    await vi.advanceTimersByTimeAsync(0);
    media.video.dispatchEvent(new Event("loadedmetadata"));
    await vi.advanceTimersByTimeAsync(0);
    expect(media.currentTimeAssignments()).toBe(1);

    await vi.advanceTimersByTimeAsync(VIDEO_FRAME_SEEK_TIMEOUT_MS);
    expect(result.current).toEqual([
      { sourceSeconds: 1, url: "https://cdn.example.test/preview.jpg", sampled: false },
    ]);
    expect(media.drawImage).not.toHaveBeenCalled();
    expect(media.video.isConnected).toBe(false);
  });

  it("clears the seek timeout after a successful seek", async () => {
    vi.useFakeTimers();
    const media = mockVideoFrameEnvironment({ currentTime: 0 });
    const sampler = createVideoFrameSampler("https://cdn.example.test/video.mp4");
    const controller = new AbortController();
    const frame = sampler.sample("https://cdn.example.test/video.mp4", 1, controller.signal);

    media.video.dispatchEvent(new Event("loadedmetadata"));
    await expect(frame).resolves.toBe("blob:frame");
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(VIDEO_FRAME_SEEK_TIMEOUT_MS);
    expect(media.drawImage).toHaveBeenCalledTimes(1);
    sampler.dispose();
  });

  it("settles promptly when assigning currentTime throws", async () => {
    const media = mockVideoFrameEnvironment({ currentTime: 0, throwOnSeek: true });
    const sampler = createVideoFrameSampler("https://cdn.example.test/video.mp4");
    const controller = new AbortController();
    const frame = sampler.sample("https://cdn.example.test/video.mp4", 1, controller.signal);

    media.video.dispatchEvent(new Event("loadedmetadata"));
    const outcome = await Promise.race([
      frame.then(() => "resolved", (error: unknown) => error),
      new Promise((resolve) => window.setTimeout(() => resolve("timed out"), 20)),
    ]);
    expect(outcome).toBeInstanceOf(Error);
    sampler.dispose();
  });
});
