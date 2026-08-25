import { useEffect, useMemo, useRef, useState } from "react";

const TARGET_FRAME_WIDTH = 80;
const TARGET_FRAME_HEIGHT = 45;
const MAX_FRAME_SAMPLES = 12;
const MAX_CACHED_FRAME_URLS = 120;
const SEEK_EPSILON_SECONDS = 0.001;
export const VIDEO_FRAME_SEEK_TIMEOUT_MS = 4_000;

export interface VideoFrameSample {
  sourceSeconds: number;
  url: string | null;
  sampled: boolean;
}

export interface VideoFrameRequest {
  assetId: string;
  mediaUrl: string | null;
  previewUrl: string | null;
  sourceStart: number;
  sourceEnd: number;
  renderedWidth: number;
  active: boolean;
}

export type VideoFrameSampler = (
  mediaUrl: string,
  sourceSeconds: number,
  signal: AbortSignal,
) => Promise<string>;

export interface VideoFrameSamplerSession {
  sample: VideoFrameSampler;
  dispose: () => void;
}

interface FrameSampleTimesInput {
  start: number;
  end: number;
  renderedWidth: number;
  targetFrameWidth: number;
}

interface StripState {
  key: string;
  samples: VideoFrameSample[];
}

interface CacheEntry {
  url: string;
  references: number;
  cached: boolean;
}

interface FrameLease {
  url: string;
  release: () => void;
}

interface PendingFrame {
  controller: AbortController;
  consumers: number;
  promise: Promise<CacheEntry>;
}

interface SamplingRun {
  controller: AbortController;
  session: VideoFrameSamplerSession | null;
  sessionOperations: number;
  stopped: boolean;
}

const frameUrlCache = new Map<string, CacheEntry>();
const pendingFrames = new Map<string, PendingFrame>();

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function abortError(): Error {
  const error = new Error("Video frame sampling was aborted");
  error.name = "AbortError";
  return error;
}

function seekTimeoutError(): Error {
  const error = new Error("Video frame seek timed out");
  error.name = "TimeoutError";
  return error;
}

function revokeBlobUrl(url: string): void {
  if (url.startsWith("blob:") && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
}

function releaseCacheEntry(entry: CacheEntry): void {
  entry.references -= 1;
  if (entry.references === 0 && !entry.cached) revokeBlobUrl(entry.url);
}

function retainCacheEntry(entry: CacheEntry): FrameLease {
  entry.references += 1;
  let released = false;
  return {
    url: entry.url,
    release: () => {
      if (released) return;
      released = true;
      releaseCacheEntry(entry);
    },
  };
}

function evictOverflow(): void {
  while (frameUrlCache.size > MAX_CACHED_FRAME_URLS) {
    const oldest = frameUrlCache.entries().next().value as [string, CacheEntry] | undefined;
    if (!oldest) return;
    frameUrlCache.delete(oldest[0]);
    oldest[1].cached = false;
    if (oldest[1].references === 0) revokeBlobUrl(oldest[1].url);
  }
}

function cacheLease(key: string): FrameLease | null {
  const entry = frameUrlCache.get(key);
  if (!entry) return null;
  frameUrlCache.delete(key);
  frameUrlCache.set(key, entry);
  return retainCacheEntry(entry);
}

function cacheFrameUrl(key: string, url: string): CacheEntry {
  const existing = frameUrlCache.get(key);
  if (existing) {
    frameUrlCache.delete(key);
    frameUrlCache.set(key, existing);
    if (existing.url !== url) revokeBlobUrl(url);
    return existing;
  }

  const entry: CacheEntry = { url, references: 0, cached: true };
  frameUrlCache.set(key, entry);
  evictOverflow();
  return entry;
}

function awaitWithAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError());

  return new Promise<T>((resolve, reject) => {
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    const onAbort = () => {
      cleanup();
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error: unknown) => {
        cleanup();
        reject(error);
      },
    );
  });
}

function sharedFrame(
  key: string,
  signal: AbortSignal,
  sample: (signal: AbortSignal) => Promise<string>,
): Promise<CacheEntry> {
  let pending = pendingFrames.get(key);
  if (!pending) {
    const controller = new AbortController();
    pending = {
      controller,
      consumers: 0,
      promise: Promise.resolve()
        .then(() => sample(controller.signal))
        .then((url) => {
          if (controller.signal.aborted) {
            revokeBlobUrl(url);
            throw abortError();
          }
          return cacheFrameUrl(key, url);
        }),
    };
    pendingFrames.set(key, pending);
    void pending.promise.then(
      () => {
        if (pendingFrames.get(key) === pending) pendingFrames.delete(key);
      },
      () => {
        if (pendingFrames.get(key) === pending) pendingFrames.delete(key);
      },
    );
  }

  pending.consumers += 1;
  return awaitWithAbort(pending.promise, signal).finally(() => {
    pending.consumers -= 1;
    if (pending.consumers === 0 && pendingFrames.get(key) === pending && !pending.controller.signal.aborted) {
      pending.controller.abort();
    }
  });
}

export function frameSampleTimes(input: FrameSampleTimesInput): number[] {
  const start = finiteOr(input.start, 0);
  const end = Math.max(start, finiteOr(input.end, start));
  const width = Math.max(0, finiteOr(input.renderedWidth, 0));
  const targetWidth = Math.max(1, finiteOr(input.targetFrameWidth, TARGET_FRAME_WIDTH));
  const count = Math.min(MAX_FRAME_SAMPLES, Math.ceil(width / targetWidth));
  const duration = end - start;

  if (count === 0 || duration === 0) return [];
  return Array.from({ length: count }, (_, index) => start + ((index + 0.5) * duration) / count);
}

export function frameCacheKey(assetId: string, sourceSeconds: number, width: number, height: number): string {
  return `${assetId}:${finiteOr(sourceSeconds, 0).toFixed(2)}:${width}x${height}`;
}

function requestKey(request: VideoFrameRequest): string {
  return [
    request.assetId,
    request.mediaUrl,
    request.previewUrl,
    request.sourceStart,
    request.sourceEnd,
    request.renderedWidth,
    request.active,
  ].join("|");
}

function frameTimesFor(request: VideoFrameRequest): number[] {
  return frameSampleTimes({
    start: request.sourceStart,
    end: request.sourceEnd,
    renderedWidth: request.renderedWidth,
    targetFrameWidth: TARGET_FRAME_WIDTH,
  });
}

function fallbackSamples(request: VideoFrameRequest): VideoFrameSample[] {
  return frameTimesFor(request).map((sourceSeconds) => ({
    sourceSeconds,
    url: request.previewUrl,
    sampled: false,
  }));
}

function waitForMediaEvent(
  target: HTMLVideoElement,
  type: "loadedmetadata" | "seeked",
  signal: AbortSignal,
): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError());

  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      target.removeEventListener(type, onSuccess);
      target.removeEventListener("error", onError);
      signal.removeEventListener("abort", onAbort);
    };
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback();
    };
    const onSuccess = () => finish(resolve);
    const onError = () => finish(() => reject(new Error(`Video ${type} failed`)));
    const onAbort = () => finish(() => reject(abortError()));
    target.addEventListener(type, onSuccess, { once: true });
    target.addEventListener("error", onError, { once: true });
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function seekVideo(video: HTMLVideoElement, targetTime: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(abortError());
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA
    && Math.abs(video.currentTime - targetTime) <= SEEK_EPSILON_SECONDS) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let timeoutId: number | null = null;
    const cleanup = () => {
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("error", onError);
      signal.removeEventListener("abort", onAbort);
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    };
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback();
    };
    const onSeeked = () => finish(resolve);
    const onError = () => finish(() => reject(new Error("Video seek failed")));
    const onAbort = () => finish(() => reject(abortError()));

    video.addEventListener("seeked", onSeeked, { once: true });
    video.addEventListener("error", onError, { once: true });
    signal.addEventListener("abort", onAbort, { once: true });
    timeoutId = window.setTimeout(() => finish(() => reject(seekTimeoutError())), VIDEO_FRAME_SEEK_TIMEOUT_MS);
    try {
      video.currentTime = targetTime;
    } catch (error) {
      finish(() => reject(error));
      return;
    }
  });
}

function canvasBlobUrl(canvas: HTMLCanvasElement, signal: AbortSignal): Promise<string> {
  if (signal.aborted) return Promise.reject(abortError());

  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback();
    };
    const onAbort = () => finish(() => reject(abortError()));
    signal.addEventListener("abort", onAbort, { once: true });
    try {
      canvas.toBlob((blob) => {
        if (!blob) {
          finish(() => reject(new Error("Video frame canvas was empty")));
          return;
        }
        if (signal.aborted) {
          finish(() => reject(abortError()));
          return;
        }
        finish(() => resolve(URL.createObjectURL(blob)));
      }, "image/jpeg", 0.82);
    } catch (error) {
      finish(() => reject(error));
    }
  });
}

export function createVideoFrameSampler(mediaUrl: string): VideoFrameSamplerSession {
  const video = document.createElement("video");
  const canvas = document.createElement("canvas");
  let disposed = false;
  let metadata: Promise<void> | null = null;

  video.muted = true;
  video.preload = "metadata";
  video.playsInline = true;
  video.hidden = true;
  video.style.display = "none";
  document.body.append(video);

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.remove();
  };

  const loadMetadata = (signal: AbortSignal): Promise<void> => {
    if (metadata) return metadata;
    const event = waitForMediaEvent(video, "loadedmetadata", signal);
    video.src = mediaUrl;
    video.load();
    metadata = event;
    return metadata;
  };

  return {
    sample: async (_requestedUrl, sourceSeconds, signal) => {
      try {
        await loadMetadata(signal);
        if (disposed || signal.aborted) throw abortError();

        const duration = Number.isFinite(video.duration) ? video.duration : sourceSeconds;
        const safeTime = Math.max(0, Math.min(sourceSeconds, Math.max(0, duration - SEEK_EPSILON_SECONDS)));
        await seekVideo(video, safeTime, signal);
        if (disposed || signal.aborted) throw abortError();

        canvas.width = TARGET_FRAME_WIDTH;
        canvas.height = TARGET_FRAME_HEIGHT;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Video frame canvas is unavailable");
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        return await canvasBlobUrl(canvas, signal);
      } catch (error) {
        if (signal.aborted || (error instanceof Error && error.name === "TimeoutError")) dispose();
        throw error;
      }
    },
    dispose,
  };
}

export function useVideoFrameStrip(
  requestInput: VideoFrameRequest,
  sampler?: VideoFrameSampler,
): VideoFrameSample[] {
  const request = useMemo<VideoFrameRequest>(() => ({
    assetId: requestInput.assetId,
    mediaUrl: requestInput.mediaUrl,
    previewUrl: requestInput.previewUrl,
    sourceStart: requestInput.sourceStart,
    sourceEnd: requestInput.sourceEnd,
    renderedWidth: requestInput.renderedWidth,
    active: requestInput.active,
  }), [
    requestInput.assetId,
    requestInput.mediaUrl,
    requestInput.previewUrl,
    requestInput.sourceStart,
    requestInput.sourceEnd,
    requestInput.renderedWidth,
    requestInput.active,
  ]);
  const key = requestKey(request);
  const epochRef = useRef(0);
  const [state, setState] = useState<StripState>(() => ({ key, samples: fallbackSamples(request) }));
  const visibleSamples = state.key === key ? state.samples : fallbackSamples(request);

  useEffect(() => {
    const epoch = ++epochRef.current;
    let disposed = false;
    let currentRun: SamplingRun | null = null;
    const leases = new Map<string, FrameLease>();
    const isCurrent = () => !disposed && epochRef.current === epoch;

    const releaseLeases = () => {
      leases.forEach((lease) => lease.release());
      leases.clear();
    };

    const stopRun = (run: SamplingRun) => {
      run.stopped = true;
      run.controller.abort();
      if (run.sessionOperations === 0) run.session?.dispose();
    };

    const replaceSample = (index: number, sample: VideoFrameSample) => {
      if (!isCurrent()) return;
      setState((current) => {
        if (current.key !== key) return current;
        const samples = current.samples.slice();
        samples[index] = sample;
        return { key, samples };
      });
    };

    const schedule = async () => {
      if (!isCurrent() || document.hidden || currentRun) return;
      const run: SamplingRun = {
        controller: new AbortController(),
        session: null,
        sessionOperations: 0,
        stopped: false,
      };
      currentRun = run;

      try {
        const sourceTimes = frameTimesFor(request);
        const samples = sourceTimes.map((sourceSeconds) => {
          const cacheKey = frameCacheKey(
            request.assetId,
            sourceSeconds,
            TARGET_FRAME_WIDTH,
            TARGET_FRAME_HEIGHT,
          );
          let lease = leases.get(cacheKey);
          if (!lease) {
            lease = cacheLease(cacheKey) ?? undefined;
            if (lease) leases.set(cacheKey, lease);
          }
          return {
            sourceSeconds,
            url: lease?.url ?? request.previewUrl,
            sampled: Boolean(lease),
          };
        });
        if (!isCurrent() || run.stopped) return;
        setState({ key, samples });

        if (!request.active || !request.mediaUrl) return;
        for (let index = 0; index < samples.length; index += 1) {
          if (!isCurrent() || run.stopped || document.hidden) return;
          const sourceSeconds = samples[index]!.sourceSeconds;
          const cacheKey = frameCacheKey(
            request.assetId,
            sourceSeconds,
            TARGET_FRAME_WIDTH,
            TARGET_FRAME_HEIGHT,
          );
          if (leases.has(cacheKey)) continue;

          let entry: CacheEntry;
          try {
            entry = await sharedFrame(cacheKey, run.controller.signal, (signal) => {
              if (sampler) return sampler(request.mediaUrl!, sourceSeconds, signal);
              run.session ??= createVideoFrameSampler(request.mediaUrl!);
              run.sessionOperations += 1;
              return run.session.sample(request.mediaUrl!, sourceSeconds, signal).finally(() => {
                run.sessionOperations -= 1;
                if (run.stopped && run.sessionOperations === 0) run.session?.dispose();
              });
            });
          } catch (error) {
            if (error instanceof Error && error.name === "AbortError") return;
            continue;
          }
          if (!isCurrent() || run.stopped) return;
          const lease = retainCacheEntry(entry);
          leases.set(cacheKey, lease);
          replaceSample(index, { sourceSeconds, url: lease.url, sampled: true });
        }
      } catch (error) {
        if (!(error instanceof Error) || error.name !== "AbortError") {
          // Preview-backed samples intentionally remain visible when decoding fails.
        }
      } finally {
        if (currentRun === run) currentRun = null;
        if (run.sessionOperations === 0) run.session?.dispose();
      }
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (currentRun) stopRun(currentRun);
        return;
      }
      void schedule();
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    void schedule();
    return () => {
      disposed = true;
      if (currentRun) stopRun(currentRun);
      releaseLeases();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [key, request, sampler]);

  return visibleSamples;
}
