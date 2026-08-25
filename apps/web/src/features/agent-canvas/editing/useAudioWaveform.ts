import { useEffect, useMemo, useState } from "react";

const MAX_BASE_PEAKS = 512;
const FALLBACK_PATTERN = [0.24, 0.41, 0.32, 0.56, 0.38, 0.68, 0.45, 0.3] as const;

export type AudioWaveformState =
  | { status: "loading"; peaks: number[] }
  | { status: "ready"; peaks: number[] }
  | { status: "fallback"; peaks: number[] };

export interface AudioWaveformRequest {
  audioUrl: string | null;
  renderedWidth: number;
}

interface DecodedAudioBuffer {
  length: number;
  numberOfChannels: number;
  getChannelData(channel: number): Float32Array;
}

interface PendingAudioDecode {
  consumers: number;
  controller: AbortController;
  promise: Promise<number[]>;
}

interface SharedAudioPeaks {
  promise: Promise<number[]>;
  release: () => void;
}

interface BaseWaveformState {
  audioUrl: string | null;
  basePeaks: number[] | null;
  status: AudioWaveformState["status"];
}

const basePeakCache = new Map<string, number[]>();
const pendingAudioDecodes = new Map<string, PendingAudioDecode>();

function removePendingAudioDecode(audioUrl: string, pending: PendingAudioDecode): void {
  if (pendingAudioDecodes.get(audioUrl) === pending) pendingAudioDecodes.delete(audioUrl);
}

export function pendingAudioDecodeCount(): number {
  return pendingAudioDecodes.size;
}

function bucketCount(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

function abortError(): Error {
  const error = new Error("Audio waveform decode was aborted");
  error.name = "AbortError";
  return error;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function clampPeak(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, Math.abs(value))) : 0;
}

function peakBuckets(values: ArrayLike<number>, requestedCount: number): number[] {
  const count = bucketCount(requestedCount);
  if (count === 0) return [];
  if (values.length === 0) return Array.from({ length: count }, () => 0);
  if (count >= values.length) {
    return Array.from({ length: count }, (_, bucketIndex) => (
      clampPeak(values[Math.min(values.length - 1, Math.floor((bucketIndex * values.length) / count))] ?? 0)
    ));
  }

  return Array.from({ length: count }, (_, bucketIndex) => {
    const start = Math.floor((bucketIndex * values.length) / count);
    const end = Math.floor(((bucketIndex + 1) * values.length) / count);
    let peak = 0;
    for (let index = start; index < end; index += 1) {
      peak = Math.max(peak, clampPeak(values[index] ?? 0));
    }
    return peak;
  });
}

export function reduceAudioPeaks(samples: Float32Array, requestedCount: number): number[] {
  return peakBuckets(samples, requestedCount);
}

export function normalizePeakCount(peaks: readonly number[], requestedCount: number): number[] {
  return peakBuckets(peaks, requestedCount);
}

export function combineAudioChannelPeaks(channels: readonly Float32Array[], requestedCount: number): number[] {
  const count = bucketCount(requestedCount);
  const peaks = Array.from({ length: count }, () => 0);
  for (const channel of channels) {
    const channelPeaks = reduceAudioPeaks(channel, count);
    for (let index = 0; index < count; index += 1) {
      peaks[index] = Math.max(peaks[index]!, channelPeaks[index]!);
    }
  }
  return peaks;
}

export function fallbackAudioPeaks(requestedCount: number): number[] {
  const count = bucketCount(requestedCount);
  return Array.from({ length: count }, (_, index) => FALLBACK_PATTERN[index % FALLBACK_PATTERN.length]!);
}

export function canonicalAudioUrl(audioUrl: string): string {
  try {
    return new URL(audioUrl, window.location.href).href;
  } catch {
    return audioUrl;
  }
}

function decodedBufferPeaks(buffer: DecodedAudioBuffer): number[] {
  const sourceLength = bucketCount(buffer.length);
  const count = Math.min(MAX_BASE_PEAKS, sourceLength);
  const channels = Array.from({ length: Math.max(0, buffer.numberOfChannels) }, (_, index) => buffer.getChannelData(index));
  return combineAudioChannelPeaks(channels, count);
}

async function decodeAudioPeaks(audioUrl: string, signal: AbortSignal): Promise<number[]> {
  const response = await fetch(audioUrl, { signal });
  if (!response.ok) throw new Error(`Audio waveform fetch failed: ${response.status}`);
  const audioData = await response.arrayBuffer();
  if (signal.aborted) throw abortError();

  let context: AudioContext | null = null;
  let closed = false;
  const closeContext = async () => {
    if (!context || closed) return;
    closed = true;
    await context.close().catch(() => undefined);
  };
  const onAbort = () => {
    void closeContext();
  };
  try {
    context = new AudioContext();
    signal.addEventListener("abort", onAbort, { once: true });
    const decoded = await context.decodeAudioData(audioData);
    if (signal.aborted) throw abortError();
    return decodedBufferPeaks(decoded);
  } finally {
    signal.removeEventListener("abort", onAbort);
    await closeContext();
  }
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

function sharedAudioPeaks(audioUrl: string, signal: AbortSignal): SharedAudioPeaks {
  let pending = pendingAudioDecodes.get(audioUrl);
  if (pending?.controller.signal.aborted) {
    removePendingAudioDecode(audioUrl, pending);
    pending = undefined;
  }
  if (!pending) {
    const controller = new AbortController();
    const promise = decodeAudioPeaks(audioUrl, controller.signal).then((peaks) => {
      basePeakCache.set(audioUrl, peaks);
      return peaks;
    });
    const created: PendingAudioDecode = { consumers: 0, controller, promise };
    pending = created;
    pendingAudioDecodes.set(audioUrl, created);
    void promise.finally(() => {
      removePendingAudioDecode(audioUrl, created);
    }).catch(() => undefined);
  }

  pending.consumers += 1;
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    pending!.consumers -= 1;
    if (pending!.consumers === 0) {
      removePendingAudioDecode(audioUrl, pending!);
      if (!pending!.controller.signal.aborted) pending!.controller.abort();
    }
  };
  return {
    promise: awaitWithAbort(pending.promise, signal).finally(release),
    release,
  };
}

export function useAudioWaveform(requestInput: AudioWaveformRequest): AudioWaveformState {
  const request = useMemo(() => ({
    audioUrl: requestInput.audioUrl ? canonicalAudioUrl(requestInput.audioUrl) : null,
    renderedWidth: bucketCount(requestInput.renderedWidth),
  }), [requestInput.audioUrl, requestInput.renderedWidth]);
  const [baseState, setBaseState] = useState<BaseWaveformState>({
    audioUrl: request.audioUrl,
    basePeaks: null,
    status: request.audioUrl ? "loading" : "fallback",
  });

  useEffect(() => {
    const audioUrl = request.audioUrl;
    if (!audioUrl) {
      setBaseState({ audioUrl: null, basePeaks: null, status: "fallback" });
      return undefined;
    }

    const cached = basePeakCache.get(audioUrl);
    if (cached) {
      setBaseState({ audioUrl, basePeaks: cached, status: "ready" });
      return undefined;
    }

    const controller = new AbortController();
    let disposed = false;
    setBaseState({ audioUrl, basePeaks: null, status: "loading" });
    const shared = sharedAudioPeaks(audioUrl, controller.signal);
    void shared.promise.then(
      (basePeaks) => {
        if (!disposed) setBaseState({ audioUrl, basePeaks, status: "ready" });
      },
      (error: unknown) => {
        if (!disposed && !isAbortError(error)) setBaseState({ audioUrl, basePeaks: null, status: "fallback" });
      },
    );
    return () => {
      disposed = true;
      shared.release();
      controller.abort();
    };
  }, [request.audioUrl]);

  if (baseState.audioUrl !== request.audioUrl) {
    return { status: request.audioUrl ? "loading" : "fallback", peaks: fallbackAudioPeaks(request.renderedWidth) };
  }
  if (baseState.status === "ready" && baseState.basePeaks) {
    return { status: "ready", peaks: normalizePeakCount(baseState.basePeaks, request.renderedWidth) };
  }
  if (baseState.status === "fallback") {
    return { status: "fallback", peaks: fallbackAudioPeaks(request.renderedWidth) };
  }
  return { status: "loading", peaks: fallbackAudioPeaks(request.renderedWidth) };
}
