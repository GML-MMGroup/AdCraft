import { useEffect, useMemo, useRef, useState } from "react";
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineSource,
} from "../../../types-v2.ts";
import { versionedMediaPath } from "../../../workflow/mediaPreview.ts";
import { ensureVideoPoster } from "../../../workflow/videoPosterCache.ts";

const DEFAULT_WAVEFORM_BARS = 48;
const MEDIA_DRIFT_SECONDS = 0.12;

type ClipSourcePin = Pick<V2FinalTimelineClip, "source_asset_id" | "source_version_id">;
type PreviewMediaClip = Pick<
  V2FinalTimelineClip,
  "clip_id" | "clip_type" | "source_asset_id" | "source_version_id"
>;
type LocalTimeClip = Pick<V2FinalTimelineClip, "start_time" | "duration" | "trim_in" | "trim_out">;
type FadeClip = Pick<V2FinalTimelineClip, "start_time" | "duration" | "audio">;
type MediaUrlMapper = (path?: string | null) => string;

export type TrackedMediaPlayRequest = {
  attempt: number;
  token: symbol;
};

export type PreviewMediaStatus = {
  key: string;
  source: V2FinalTimelineSource | null;
  status: "ready" | "missing" | "failed";
};

export type TimelineMediaVisuals = {
  posterUrls: ReadonlyMap<string, string>;
  waveforms: ReadonlyMap<string, number[]>;
};

export function timelineSourceKey(source: Pick<V2FinalTimelineSource, "asset_id" | "version_id">) {
  return `${source.asset_id}:${source.version_id}`;
}

export function findTimelineSource(
  sources: V2FinalTimelineSource[],
  clip: ClipSourcePin,
) {
  return sources.find((source) => source.asset_id === clip.source_asset_id
    && source.version_id === clip.source_version_id) ?? null;
}

export function timelineSourceUrls(source: V2FinalTimelineSource, mediaUrl: MediaUrlMapper = (path) => path ?? "") {
  return {
    original: source.public_url ? mediaUrl(versionedMediaPath(source.public_url, source)) : "",
    thumbnail: source.thumbnail_url ? mediaUrl(versionedMediaPath(source.thumbnail_url, source)) : "",
  };
}

export function requestTrackedMediaPlay<T extends { play: () => Promise<void> }>(
  requests: Map<T, TrackedMediaPlayRequest>,
  element: T,
  attempt: number,
  onRejected: (attempt: number) => void,
) {
  const request: TrackedMediaPlayRequest = { attempt, token: Symbol("media-play-request") };
  requests.set(element, request);
  const settle = () => {
    if (requests.get(element) !== request) return false;
    requests.delete(element);
    return true;
  };
  try {
    void element.play().then(
      () => settle(),
      () => {
        if (settle()) onRejected(attempt);
      },
    );
  } catch {
    if (settle()) onRejected(attempt);
  }
  return request;
}

export function previewMediaStatus(
  sources: V2FinalTimelineSource[],
  clip: PreviewMediaClip,
  failedKeys: ReadonlySet<string>,
): PreviewMediaStatus {
  const source = findTimelineSource(sources, clip);
  const key = [
    clip.clip_id,
    clip.clip_type,
    clip.source_asset_id ?? "",
    clip.source_version_id ?? "",
    source?.public_url ?? "",
  ].join("\u0000");
  const expectedMediaType = clip.clip_type === "video" || clip.clip_type === "audio" || clip.clip_type === "image"
    ? clip.clip_type
    : null;
  if (!source || !source.public_url || !expectedMediaType || source.media_type !== expectedMediaType) {
    return { key, source, status: "missing" };
  }
  return { key, source, status: failedKeys.has(key) ? "failed" : "ready" };
}

export function pruneMediaRefCallbacks<T>(callbacks: Map<string, T>, activeKeys: ReadonlySet<string>) {
  callbacks.forEach((_callback, key) => {
    if (!activeKeys.has(key)) callbacks.delete(key);
  });
}

export function activeCompositionClips(timeline: V2FinalCompositionTimeline, time: number) {
  const tracks = new Map(timeline.tracks.map((track) => [track.track_id, track]));
  return timeline.clips
    .filter((clip) => {
      const track = tracks.get(clip.track_id);
      return (clip.clip_type === "video" || clip.clip_type === "image")
        && clip.enabled
        && track?.enabled === true
        && time >= clip.start_time
        && time < clip.start_time + clip.duration;
    })
    .sort((left, right) => {
      const leftTrack = tracks.get(left.track_id);
      const rightTrack = tracks.get(right.track_id);
      return (leftTrack?.order ?? 0) - (rightTrack?.order ?? 0)
        || left.track_id.localeCompare(right.track_id)
        || left.start_time - right.start_time
        || left.clip_id.localeCompare(right.clip_id);
    });
}

export function activeAudioClips(timeline: V2FinalCompositionTimeline, time: number) {
  const tracks = new Map(timeline.tracks.map((track) => [track.track_id, track]));
  return timeline.clips
    .filter((clip) => clip.clip_type === "audio"
      && clip.enabled
      && tracks.get(clip.track_id)?.enabled === true
      && time >= clip.start_time
      && time < clip.start_time + clip.duration)
    .sort((left, right) => left.start_time - right.start_time || left.clip_id.localeCompare(right.clip_id));
}

export function activeSubtitleClips(timeline: V2FinalCompositionTimeline, time: number) {
  const tracks = new Map(timeline.tracks.map((track) => [track.track_id, track]));
  return timeline.clips
    .filter((clip) => clip.clip_type === "subtitle"
      && clip.enabled
      && tracks.get(clip.track_id)?.enabled === true
      && time >= clip.start_time
      && time < clip.start_time + clip.duration)
    .sort((left, right) => (tracks.get(left.track_id)?.order ?? 0) - (tracks.get(right.track_id)?.order ?? 0)
      || left.track_id.localeCompare(right.track_id)
      || left.clip_id.localeCompare(right.clip_id));
}

export function boundedClipLocalTime(
  clip: LocalTimeClip,
  playheadSeconds: number,
  mediaDuration = Number.POSITIVE_INFINITY,
) {
  const trimStart = Math.max(0, finiteOr(clip.trim_in, 0));
  const durationEnd = trimStart + Math.max(0, finiteOr(clip.duration, 0));
  const trimEnd = clip.trim_out === null
    ? durationEnd
    : Math.max(trimStart, finiteOr(clip.trim_out, durationEnd));
  const mediaEnd = Number.isFinite(mediaDuration) && mediaDuration >= 0 ? mediaDuration : trimEnd;
  const upper = Math.max(trimStart, Math.min(trimEnd, durationEnd, mediaEnd));
  const target = finiteOr(playheadSeconds, 0) - finiteOr(clip.start_time, 0) + trimStart;
  return Math.min(upper, Math.max(trimStart, target));
}

export function shouldCorrectMediaDrift(currentTime: number, targetTime: number) {
  return !Number.isFinite(currentTime)
    || !Number.isFinite(targetTime)
    || Math.abs(currentTime - targetTime) - MEDIA_DRIFT_SECONDS > 1e-9;
}

export function clipFadeGain(clip: FadeClip, playheadSeconds: number) {
  const duration = Math.max(0, finiteOr(clip.duration, 0));
  if (duration <= 0) return 0;
  const elapsed = Math.min(duration, Math.max(0, playheadSeconds - finiteOr(clip.start_time, 0)));
  const remaining = Math.max(0, duration - elapsed);
  const fadeIn = Math.min(duration, Math.max(0, finiteOr(clip.audio.fade_in_seconds, 0)));
  const fadeOut = Math.min(duration, Math.max(0, finiteOr(clip.audio.fade_out_seconds, 0)));
  const fadeInGain = fadeIn > 0 ? Math.min(1, elapsed / fadeIn) : 1;
  const fadeOutGain = fadeOut > 0 ? Math.min(1, remaining / fadeOut) : 1;
  return Math.min(1, Math.max(0, fadeInGain), Math.max(0, fadeOutGain));
}

export function mediaCleanupDecision(active: boolean) {
  return active
    ? { pause: false, resetTime: false, silence: false }
    : { pause: true, resetTime: true, silence: true };
}

export function deterministicWaveformFallback(key: string, count = DEFAULT_WAVEFORM_BARS) {
  const size = Math.max(1, Math.floor(count));
  let state = hashString(key || "timeline-audio");
  return Array.from({ length: size }, (_, index) => {
    state = (Math.imul(state ^ (index + 1), 1664525) + 1013904223) >>> 0;
    const normalized = state / 0xffffffff;
    return Number((0.18 + normalized * 0.82).toFixed(4));
  });
}

export function useTimelineMediaVisuals({
  workflowId,
  timeline,
  sources,
  selectedClipIds,
  playheadSeconds,
  mediaUrl,
}: {
  workflowId: string;
  timeline: V2FinalCompositionTimeline;
  sources: V2FinalTimelineSource[];
  selectedClipIds: string[];
  playheadSeconds: number;
  mediaUrl: MediaUrlMapper;
}): TimelineMediaVisuals {
  const objectUrlsRef = useRef(new Map<string, string>());
  const workflowRef = useRef(workflowId);
  const [generatedPosters, setGeneratedPosters] = useState<Map<string, string>>(() => new Map());
  const [decodedWaveforms, setDecodedWaveforms] = useState<Map<string, number[]>>(() => new Map());
  const interestedClipIds = useMemo(
    () => timelineMediaInterestClipIds(timeline, selectedClipIds, playheadSeconds),
    [playheadSeconds, selectedClipIds, timeline],
  );
  const sourcesByKey = useMemo(
    () => new Map(sources.map((source) => [timelineSourceKey(source), source])),
    [sources],
  );
  const interestedSourceSignature = useMemo(() => {
    const keys = new Set<string>();
    timeline.clips.forEach((clip) => {
      if (!interestedClipIds.has(clip.clip_id)) return;
      const source = findTimelineSource(sources, clip);
      if (source) keys.add(timelineSourceKey(source));
    });
    return [...keys].sort().join("\u0000");
  }, [interestedClipIds, sources, timeline.clips]);

  useEffect(() => {
    if (workflowRef.current === workflowId) return;
    workflowRef.current = workflowId;
    objectUrlsRef.current.forEach((objectUrl) => URL.revokeObjectURL(objectUrl));
    objectUrlsRef.current.clear();
    setGeneratedPosters(new Map());
    setDecodedWaveforms(new Map());
  }, [workflowId]);

  useEffect(() => {
    let disposed = false;
    const wantedKeys = new Set(interestedSourceSignature ? interestedSourceSignature.split("\u0000") : []);
    const interestedSources = [...wantedKeys]
      .map((key) => sourcesByKey.get(key))
      .filter((source): source is V2FinalTimelineSource => Boolean(source));
    let removedPoster = false;
    objectUrlsRef.current.forEach((objectUrl, key) => {
      if (wantedKeys.has(key)) return;
      URL.revokeObjectURL(objectUrl);
      objectUrlsRef.current.delete(key);
      removedPoster = true;
    });
    if (removedPoster) {
      setGeneratedPosters((current) => new Map([...current].filter(([key]) => wantedKeys.has(key))));
    }

    interestedSources.forEach((source) => {
      if (source.media_type !== "video" || source.thumbnail_url || !source.public_url) return;
      const key = timelineSourceKey(source);
      if (objectUrlsRef.current.has(key)) return;
      const sourceUrl = timelineSourceUrls(source, mediaUrl).original;
      const posterAsset = {
        asset_id: source.asset_id,
        public_url: source.public_url,
        thumbnail_url: source.thumbnail_url ?? undefined,
        asset_type: "video" as const,
        version: source.version_id,
      };
      void ensureVideoPoster({
        projectId: workflowId,
        workflowId,
        asset: posterAsset,
        videoUrl: sourceUrl,
      }).then((record) => {
        if (!record) return;
        const objectUrl = URL.createObjectURL(record.poster_blob);
        if (disposed || !wantedKeys.has(key)) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        objectUrlsRef.current.set(key, objectUrl);
        setGeneratedPosters((current) => new Map(current).set(key, objectUrl));
      });
    });

    return () => {
      disposed = true;
    };
  }, [interestedSourceSignature, mediaUrl, sourcesByKey, workflowId]);

  useEffect(() => {
    const controllers: AbortController[] = [];
    const interestedSources = (interestedSourceSignature ? interestedSourceSignature.split("\u0000") : [])
      .map((key) => sourcesByKey.get(key))
      .filter((source): source is V2FinalTimelineSource => Boolean(source));
    interestedSources.forEach((source) => {
      if (source.media_type !== "audio") return;
      const key = timelineSourceKey(source);
      if (decodedWaveforms.has(key) || !source.public_url) return;
      const controller = new AbortController();
      controllers.push(controller);
      void decodeWaveform(timelineSourceUrls(source, mediaUrl).original, controller.signal)
        .then((waveform) => {
          if (!waveform || controller.signal.aborted) return;
          setDecodedWaveforms((current) => new Map(current).set(key, waveform));
        })
        .catch(() => undefined);
    });
    return () => controllers.forEach((controller) => controller.abort());
  }, [decodedWaveforms, interestedSourceSignature, mediaUrl, sourcesByKey]);

  useEffect(() => () => {
    objectUrlsRef.current.forEach((objectUrl) => URL.revokeObjectURL(objectUrl));
    objectUrlsRef.current.clear();
  }, []);

  const posterUrls = useMemo(() => {
    const next = new Map(generatedPosters);
    sources.forEach((source) => {
      const backend = timelineSourceUrls(source, mediaUrl).thumbnail;
      if (backend) next.set(timelineSourceKey(source), backend);
    });
    return next;
  }, [generatedPosters, mediaUrl, sources]);

  const waveforms = useMemo(() => {
    const next = new Map<string, number[]>();
    sources.filter((source) => source.media_type === "audio").forEach((source) => {
      const key = timelineSourceKey(source);
      next.set(key, decodedWaveforms.get(key) ?? deterministicWaveformFallback(key));
    });
    return next;
  }, [decodedWaveforms, sources]);

  return { posterUrls, waveforms };
}

function timelineMediaInterestClipIds(
  timeline: V2FinalCompositionTimeline,
  selectedClipIds: string[],
  playheadSeconds: number,
) {
  const interested = new Set(selectedClipIds);
  const enabledMedia = timeline.clips
    .filter((clip) => clip.enabled && (clip.clip_type === "video" || clip.clip_type === "audio"))
    .sort((left, right) => left.start_time - right.start_time || left.clip_id.localeCompare(right.clip_id));
  enabledMedia.forEach((clip, index) => {
    if (playheadSeconds >= clip.start_time && playheadSeconds < clip.start_time + clip.duration) {
      interested.add(clip.clip_id);
      if (enabledMedia[index - 1]) interested.add(enabledMedia[index - 1].clip_id);
      if (enabledMedia[index + 1]) interested.add(enabledMedia[index + 1].clip_id);
    }
  });
  if (!interested.size && enabledMedia.length) {
    const nextIndex = enabledMedia.findIndex((clip) => clip.start_time >= playheadSeconds);
    const index = nextIndex < 0 ? enabledMedia.length - 1 : nextIndex;
    interested.add(enabledMedia[index].clip_id);
    if (enabledMedia[index - 1]) interested.add(enabledMedia[index - 1].clip_id);
  }
  return interested;
}

async function decodeWaveform(url: string, signal: AbortSignal) {
  const AudioContextConstructor = typeof window !== "undefined"
    ? window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    : undefined;
  if (!AudioContextConstructor || !url) return null;
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Waveform source failed with ${response.status}.`);
  const buffer = await response.arrayBuffer();
  if (signal.aborted) return null;
  const context = new AudioContextConstructor();
  try {
    const decoded = await context.decodeAudioData(buffer.slice(0));
    if (signal.aborted) return null;
    return normalizeWaveform(decoded, DEFAULT_WAVEFORM_BARS);
  } finally {
    void context.close();
  }
}

function normalizeWaveform(buffer: AudioBuffer, count: number) {
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, index) => buffer.getChannelData(index));
  const blockSize = Math.max(1, Math.floor(buffer.length / count));
  const values = Array.from({ length: count }, (_, index) => {
    const start = index * blockSize;
    const end = Math.min(buffer.length, start + blockSize);
    let peak = 0;
    for (let sample = start; sample < end; sample += 1) {
      for (const channel of channels) peak = Math.max(peak, Math.abs(channel[sample] ?? 0));
    }
    return peak;
  });
  const max = Math.max(...values, Number.EPSILON);
  return values.map((value) => Number(Math.max(0.04, value / max).toFixed(4)));
}

function finiteOr(value: number, fallback: number) {
  return Number.isFinite(value) ? value : fallback;
}

function hashString(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
