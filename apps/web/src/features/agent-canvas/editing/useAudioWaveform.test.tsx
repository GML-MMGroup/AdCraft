import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  combineAudioChannelPeaks,
  fallbackAudioPeaks,
  normalizePeakCount,
  reduceAudioPeaks,
  useAudioWaveform,
} from "./useAudioWaveform.ts";
import { AudioWaveformTrack } from "./AudioWaveformTrack.tsx";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function mockAudioContext(options: {
  channels?: Float32Array[];
  decodeError?: Error;
}) {
  const close = vi.fn().mockResolvedValue(undefined);
  const decodeAudioData = vi.fn(async () => {
    if (options.decodeError) throw options.decodeError;
    const channels = options.channels ?? [new Float32Array([0, 0.5, -1, 0.25])];
    return {
      length: channels[0]?.length ?? 0,
      numberOfChannels: channels.length,
      getChannelData: (index: number) => channels[index]!,
    } as AudioBuffer;
  });
  const AudioContext = vi.fn(function AudioContextMock() {
    return { close, decodeAudioData };
  });
  vi.stubGlobal("AudioContext", AudioContext);
  return { AudioContext, close, decodeAudioData };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useAudioWaveform", () => {
  it("reduces each sample bucket to its largest magnitude", () => {
    expect(reduceAudioPeaks(new Float32Array([0, -1, 0.5, 0.25]), 2)).toEqual([1, 0.5]);
  });

  it("returns silent buckets for empty peak data", () => {
    expect(normalizePeakCount([], 4)).toEqual([0, 0, 0, 0]);
  });

  it("keeps the strongest magnitude from every decoded channel", () => {
    expect(combineAudioChannelPeaks([
      new Float32Array([0.125, 0.75, 0.25, 0.5]),
      new Float32Array([0.5, 0.25, -1, 0.125]),
    ], 2)).toEqual([0.75, 1]);
  });

  it("shows a stable fallback waveform when decodeAudioData rejects", async () => {
    const { close } = mockAudioContext({ decodeError: new Error("decode failed") });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) })));

    const { result } = renderHook(() => useAudioWaveform({
      audioUrl: "https://cdn.example.test/fallback.mp3",
      renderedWidth: 4,
    }));

    await waitFor(() => expect(result.current.status).toBe("fallback"));
    expect(result.current.peaks).toEqual(fallbackAudioPeaks(4));
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("shows the deterministic fallback when fetching the audio asset fails", async () => {
    const { decodeAudioData } = mockAudioContext({});
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network failed"); }));

    const { result } = renderHook(() => useAudioWaveform({
      audioUrl: "https://cdn.example.test/fetch-failure.mp3",
      renderedWidth: 4,
    }));

    await waitFor(() => expect(result.current).toEqual({ status: "fallback", peaks: fallbackAudioPeaks(4) }));
    expect(decodeAudioData).not.toHaveBeenCalled();
  });

  it("keeps an empty decoded buffer renderable as zero peaks", async () => {
    mockAudioContext({ channels: [] });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) })));

    const empty = renderHook(() => useAudioWaveform({
      audioUrl: "https://cdn.example.test/empty.mp3",
      renderedWidth: 4,
    }));
    await waitFor(() => expect(empty.result.current).toEqual({ status: "ready", peaks: [0, 0, 0, 0] }));
  });

  it("keeps silent decoded samples renderable as zero peaks", async () => {
    mockAudioContext({ channels: [new Float32Array(4)] });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) })));
    const silent = renderHook(() => useAudioWaveform({
      audioUrl: "https://cdn.example.test/silent.mp3",
      renderedWidth: 4,
    }));
    await waitFor(() => expect(silent.result.current).toEqual({ status: "ready", peaks: [0, 0, 0, 0] }));
  });

  it("resamples cached decoded peaks when the rendered width changes", async () => {
    const { decodeAudioData } = mockAudioContext({
      channels: [new Float32Array([0, 1, 0.5, 0.25])],
    });
    const fetch = vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) }));
    vi.stubGlobal("fetch", fetch);

    const hook = renderHook(
      ({ renderedWidth }) => useAudioWaveform({
        audioUrl: "https://cdn.example.test/cached.mp3",
        renderedWidth,
      }),
      { initialProps: { renderedWidth: 2 } },
    );

    await waitFor(() => expect(hook.result.current).toEqual({ status: "ready", peaks: [1, 0.5] }));
    hook.rerender({ renderedWidth: 4 });
    await waitFor(() => expect(hook.result.current).toEqual({ status: "ready", peaks: [0, 1, 0.5, 0.25] }));

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(decodeAudioData).toHaveBeenCalledTimes(1);
  });

  it("does not allow a replaced request to overwrite its newer waveform", async () => {
    const first = deferred<ArrayBuffer>();
    const { decodeAudioData } = mockAudioContext({
      channels: [new Float32Array([0.25, 0.75])],
    });
    const fetch = vi.fn((url: string) => {
      if (url.endsWith("first.mp3")) return Promise.resolve({ ok: true, arrayBuffer: () => first.promise });
      return Promise.resolve({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) });
    });
    vi.stubGlobal("fetch", fetch);

    const hook = renderHook(
      ({ audioUrl }) => useAudioWaveform({ audioUrl, renderedWidth: 2 }),
      { initialProps: { audioUrl: "https://cdn.example.test/first.mp3" } },
    );

    hook.rerender({ audioUrl: "https://cdn.example.test/second.mp3" });
    await waitFor(() => expect(hook.result.current).toEqual({ status: "ready", peaks: [0.25, 0.75] }));

    first.resolve(new ArrayBuffer(8));
    await Promise.resolve();
    expect(hook.result.current).toEqual({ status: "ready", peaks: [0.25, 0.75] });
    expect(decodeAudioData).toHaveBeenCalledTimes(1);
  });

  it("aborts an in-flight fetch after unmounting", async () => {
    const abortObserved = vi.fn();
    const fetch = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        abortObserved();
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }));
    mockAudioContext({});
    vi.stubGlobal("fetch", fetch);

    const hook = renderHook(() => useAudioWaveform({
      audioUrl: "https://cdn.example.test/unmount.mp3",
      renderedWidth: 4,
    }));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    hook.unmount();
    await waitFor(() => expect(abortObserved).toHaveBeenCalledTimes(1));
  });

  it("closes an active audio context when unmounted during decoding", async () => {
    const decoded = deferred<AudioBuffer>();
    const close = vi.fn().mockResolvedValue(undefined);
    const decodeAudioData = vi.fn(() => decoded.promise);
    const AudioContext = vi.fn(function AudioContextMock() {
      return { close, decodeAudioData };
    });
    vi.stubGlobal("AudioContext", AudioContext);
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) })));

    const hook = renderHook(() => useAudioWaveform({
      audioUrl: "https://cdn.example.test/close-on-unmount.mp3",
      renderedWidth: 4,
    }));

    await waitFor(() => expect(decodeAudioData).toHaveBeenCalledTimes(1));
    hook.unmount();
    await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  });

  it("forwards BGM volume changes from the compact waveform controls", () => {
    const onSetBgm = vi.fn();
    const onSetBgmVolume = vi.fn();
    render(
      <AudioWaveformTrack
        audioUrl={null}
        durationSeconds={12}
        enabled
        name="Campaign BGM"
        onSetBgm={onSetBgm}
        onSetBgmVolume={onSetBgmVolume}
        renderedWidth={4}
        trimEndSeconds={10}
        trimStartSeconds={2}
        volume={0.5}
      />,
    );

    fireEvent.change(screen.getByRole("slider", { name: "BGM volume" }), { target: { value: "0.7" } });

    expect(onSetBgmVolume).toHaveBeenCalledWith(0.7);
    expect(onSetBgm).not.toHaveBeenCalled();
  });
});
