import { useEffect, useMemo, useRef, useState } from "react";

const TARGET_FRAME_WIDTH = 80;
const TARGET_FRAME_HEIGHT = 45;
const MAX_FRAME_SAMPLES = 12;
const MAX_CACHED_FRAME_URLS = 120;

export interface VideoFrameSample {
  sourceSeconds: number;
  url: string;
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

export type VideoFrameSampler = (mediaUrl: string, sourceSeconds: number) => Promise<string>;

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

interface ManagedVideoFrameSampler {
  sample: VideoFrameSampler;
  dispose: () => void;
}

const frameUrlCache = new Map<string, string>();

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function fallbackUrl(request: VideoFrameRequest): string {
  return request.previewUrl ?? "";
}

function revokeBlobUrl(url: string): void {
  if (url.startsWith("blob:")) URL.revokeObjectURL(url);
}

function cacheFrameUrl(key: string, url: string): void {
  const existing = frameUrlCache.get(key);
  if (existing && existing !== url) revokeBlobUrl(existing);
  frameUrlCache.delete(key);
  frameUrlCache.set(key, url);

  while (frameUrlCache.size > MAX_CACHED_FRAME_URLS) {
    const oldest = frameUrlCache.entries().next().value as [string, string] | undefined;
    if (!oldest) return;
    frameUrlCache.delete(oldest[0]);
    revokeBlobUrl(oldest[1]);
  }
}

function cachedFrameUrl(key: string): string | null {
  const url = frameUrlCache.get(key);
  if (!url) return null;
  frameUrlCache.delete(key);
  frameUrlCache.set(key, url);
  return url;
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

function buildSamples(request: VideoFrameRequest): VideoFrameSample[] {
  return frameSampleTimes({
    start: request.sourceStart,
    end: request.sourceEnd,
    renderedWidth: request.renderedWidth,
    targetFrameWidth: TARGET_FRAME_WIDTH,
  }).map((sourceSeconds) => {
    const url = cachedFrameUrl(frameCacheKey(
      request.assetId,
      sourceSeconds,
      TARGET_FRAME_WIDTH,
      TARGET_FRAME_HEIGHT,
    ));
    return {
      sourceSeconds,
      url: url ?? fallbackUrl(request),
      sampled: url !== null,
    };
  });
}

function waitForEvent(target: HTMLVideoElement, type: "loadedmetadata" | "seeked"): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      target.removeEventListener(type, onSuccess);
      target.removeEventListener("error", onError);
    };
    const onSuccess = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error(`Video ${type} failed`));
    };
    target.addEventListener(type, onSuccess, { once: true });
    target.addEventListener("error", onError, { once: true });
  });
}

function canvasBlobUrl(canvas: HTMLCanvasElement): Promise<string> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("Video frame canvas was empty"));
        return;
      }
      resolve(URL.createObjectURL(blob));
    }, "image/jpeg", 0.82);
  });
}

function createVideoFrameSampler(mediaUrl: string): ManagedVideoFrameSampler {
  const video = document.createElement("video");
  const canvas = document.createElement("canvas");
  let disposed = false;

  video.muted = true;
  video.preload = "metadata";
  video.playsInline = true;
  video.hidden = true;
  video.style.display = "none";
  document.body.append(video);

  const metadata = waitForEvent(video, "loadedmetadata");
  video.src = mediaUrl;
  video.load();

  return {
    sample: async (_requestedUrl, sourceSeconds) => {
      await metadata;
      if (disposed) throw new Error("Video frame sampler was disposed");

      const duration = Number.isFinite(video.duration) ? video.duration : sourceSeconds;
      const safeTime = Math.max(0, Math.min(sourceSeconds, Math.max(0, duration - 0.001)));
      video.currentTime = safeTime;
      await waitForEvent(video, "seeked");
      if (disposed) throw new Error("Video frame sampler was disposed");

      canvas.width = TARGET_FRAME_WIDTH;
      canvas.height = TARGET_FRAME_HEIGHT;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Video frame canvas is unavailable");
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvasBlobUrl(canvas);
    },
    dispose: () => {
      disposed = true;
      video.pause();
      video.removeAttribute("src");
      video.load();
      video.remove();
    },
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
  const [state, setState] = useState<StripState>(() => ({
    key,
    samples: buildSamples(request),
  }));
  const visibleSamples = state.key === key ? state.samples : buildSamples(request);

  useEffect(() => {
    const epoch = ++epochRef.current;
    let cancelled = false;
    let running = false;
    const isCurrent = () => !cancelled && epochRef.current === epoch;

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
      if (running || !isCurrent() || document.hidden) return;
      running = true;
      let managedSampler: ManagedVideoFrameSampler | null = null;

      try {
        const samples = buildSamples(request);
        if (!isCurrent()) return;
        setState({ key, samples });

        if (!request.active || !request.mediaUrl) return;
        let sampleFrame = sampler;

        for (let index = 0; index < samples.length; index += 1) {
          if (!isCurrent() || document.hidden) return;
          const sourceSeconds = samples[index]!.sourceSeconds;
          const cacheKey = frameCacheKey(
            request.assetId,
            sourceSeconds,
            TARGET_FRAME_WIDTH,
            TARGET_FRAME_HEIGHT,
          );
          const cached = cachedFrameUrl(cacheKey);
          if (cached) {
            replaceSample(index, { sourceSeconds, url: cached, sampled: true });
            continue;
          }

          try {
            if (!sampleFrame) {
              managedSampler = createVideoFrameSampler(request.mediaUrl);
              sampleFrame = managedSampler.sample;
            }
            const url = await sampleFrame(request.mediaUrl, sourceSeconds);
            if (!isCurrent()) {
              revokeBlobUrl(url);
              return;
            }
            cacheFrameUrl(cacheKey, url);
            replaceSample(index, { sourceSeconds, url, sampled: true });
          } catch {
            // Preview-backed samples are intentionally retained when decoding fails.
          }
        }
      } finally {
        managedSampler?.dispose();
        running = false;
      }
    };

    const onVisibilityChange = () => {
      if (!document.hidden) void schedule();
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    void schedule();
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [key, request, sampler]);

  return visibleSamples;
}
