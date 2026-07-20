import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { mediaUrl } from "../../../api/client.ts";
import { PlayIcon } from "../../../icons.tsx";
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineSource,
} from "../../../types-v2.ts";
import { v2TimelineDuration } from "./v2TimelineModel.ts";
import {
  activeAudioClips,
  activeCompositionClips,
  activeSubtitleClips,
  boundedClipLocalTime,
  clipFadeGain,
  mediaCleanupDecision,
  previewMediaStatus,
  pruneMediaRefCallbacks,
  requestTrackedMediaPlay,
  shouldCorrectMediaDrift,
  timelineSourceUrls,
  type TrackedMediaPlayRequest,
} from "./useTimelineMediaVisuals.ts";

export type V2CompositionPreviewHandle = {
  play: () => void;
  pause: () => void;
  togglePlayback: () => void;
};

type PreviewProps = {
  timeline: V2FinalCompositionTimeline;
  sources: V2FinalTimelineSource[];
  playheadSeconds: number;
  playing: boolean;
  onPlayingChange: (playing: boolean) => void;
  onPlayheadChange: (value: number) => void;
  selectedClipId: string | null;
  onSelectClip: (value: string | null) => void;
};

type MediaElement = HTMLVideoElement | HTMLAudioElement;
const EMPTY_MEDIA_FAILURES = new Set<string>();

export const V2CompositionPreview = forwardRef<V2CompositionPreviewHandle, PreviewProps>(function V2CompositionPreview({
  timeline,
  sources,
  playheadSeconds,
  playing,
  onPlayingChange,
  onPlayheadChange,
  selectedClipId,
  onSelectClip,
}, ref) {
  const mediaElements = useRef(new Map<string, MediaElement>());
  const mediaRefCallbacks = useRef(new Map<string, (element: MediaElement | null) => void>());
  const timelineRef = useRef(timeline);
  const sourcesRef = useRef(sources);
  const playheadRef = useRef(playheadSeconds);
  const playRequestsRef = useRef(new Map<MediaElement, TrackedMediaPlayRequest>());
  const [failedMediaKeys, setFailedMediaKeys] = useState<Set<string>>(() => new Set());
  const failedMediaKeysRef = useRef(failedMediaKeys);
  const playingRef = useRef(false);
  const clockStartedAtMsRef = useRef(0);
  const playheadAtStartRef = useRef(0);
  const rafIdRef = useRef<number | null>(null);
  const playbackAttemptRef = useRef(0);
  const mountedRef = useRef(true);
  const callbacksRef = useRef({ onPlayingChange, onPlayheadChange });
  const duration = Math.max(0, v2TimelineDuration(timeline));
  const activeVisuals = useMemo(
    () => activeCompositionClips(timeline, playheadSeconds),
    [playheadSeconds, timeline],
  );
  const activeSubtitles = useMemo(
    () => activeSubtitleClips(timeline, playheadSeconds),
    [playheadSeconds, timeline],
  );
  const topVideo = [...activeVisuals].reverse().find((clip) => clip.clip_type === "video") ?? null;
  const videos = useMemo(
    () => timeline.clips.filter((clip) => clip.clip_type === "video"),
    [timeline.clips],
  );
  const audioClips = useMemo(
    () => timeline.clips.filter((clip) => clip.clip_type === "audio"),
    [timeline.clips],
  );
  const mediaClips = useMemo(
    () => timeline.clips.filter((clip) => clip.clip_type === "video"
      || clip.clip_type === "audio"
      || clip.clip_type === "image"),
    [timeline.clips],
  );
  const mediaIdentityKeys = useMemo(
    () => new Set(mediaClips.map((clip) => previewMediaStatus(sources, clip, EMPTY_MEDIA_FAILURES).key)),
    [mediaClips, sources],
  );
  const mediaCallbackKeys = useMemo(
    () => new Set([...videos, ...audioClips]
      .map((clip) => previewMediaStatus(sources, clip, EMPTY_MEDIA_FAILURES))
      .filter((status) => status.status !== "missing")
      .map((status) => status.key)),
    [audioClips, sources, videos],
  );
  const mediaCallbackSignature = useMemo(() => [...mediaCallbackKeys].sort().join("\u0000"), [mediaCallbackKeys]);

  useLayoutEffect(() => {
    timelineRef.current = timeline;
    sourcesRef.current = sources;
    playheadRef.current = playheadSeconds;
    callbacksRef.current = { onPlayingChange, onPlayheadChange };
  });

  useEffect(() => {
    pruneMediaRefCallbacks(mediaRefCallbacks.current, mediaCallbackKeys);
  }, [mediaCallbackKeys, mediaCallbackSignature]);

  useEffect(() => {
    setFailedMediaKeys((current) => {
      const next = new Set([...current].filter((key) => mediaIdentityKeys.has(key)));
      if (next.size === current.size) return current;
      failedMediaKeysRef.current = next;
      return next;
    });
  }, [mediaIdentityKeys]);

  const pauseAllMedia = useCallback((reset: boolean) => {
    playRequestsRef.current.clear();
    mediaElements.current.forEach((element) => {
      element.pause();
      element.muted = true;
      element.volume = 0;
      if (reset) safelySetCurrentTime(element, 0);
    });
  }, []);

  const synchronizeMedia = useCallback((time: number, shouldPlay: boolean) => {
    const currentTimeline = timelineRef.current;
    const activeIds = new Set([
      ...activeCompositionClips(currentTimeline, time)
        .filter((clip) => clip.clip_type === "video")
        .map((clip) => clip.clip_id),
      ...activeAudioClips(currentTimeline, time).map((clip) => clip.clip_id),
    ]);
    const clips = new Map(currentTimeline.clips.map((clip) => [clip.clip_id, clip]));
    const tracks = new Map(currentTimeline.tracks.map((track) => [track.track_id, track]));
    const activeElements: MediaElement[] = [];

    mediaElements.current.forEach((element, clipId) => {
      const clip = clips.get(clipId);
      const track = clip ? tracks.get(clip.track_id) : null;
      const playable = clip
        ? previewMediaStatus(sourcesRef.current, clip, failedMediaKeysRef.current).status === "ready"
        : false;
      const isActive = Boolean(clip && playable && clip.enabled && track?.enabled && activeIds.has(clipId));
      const cleanup = mediaCleanupDecision(isActive);
      if (!clip || cleanup.pause) {
        playRequestsRef.current.delete(element);
        element.pause();
        if (cleanup.silence) {
          element.muted = true;
          element.volume = 0;
        }
        if (cleanup.resetTime) safelySetCurrentTime(element, 0);
        return;
      }

      const target = boundedClipLocalTime(clip, time, element.duration);
      if (shouldCorrectMediaDrift(element.currentTime, target)) safelySeek(element, target);
      const audioMuted = clip.audio.muted || clip.muted;
      const hasFade = clip.audio.fade_in_seconds > 0 || clip.audio.fade_out_seconds > 0;
      const fadeGain = hasFade ? clipFadeGain(clip, time) : 1;
      element.muted = audioMuted;
      element.volume = audioMuted ? 0 : clamp01(clip.audio.volume) * fadeGain;
      if (!shouldPlay) element.pause();
      else activeElements.push(element);
    });
    return activeElements;
  }, []);

  const stopPlayback = useCallback((resetMedia = false) => {
    playbackAttemptRef.current += 1;
    playingRef.current = false;
    if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
    rafIdRef.current = null;
    pauseAllMedia(resetMedia);
    callbacksRef.current.onPlayingChange(false);
  }, [pauseAllMedia]);

  const scheduleFrame = useCallback(function scheduleFrame() {
    if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
    rafIdRef.current = requestAnimationFrame((now) => {
      if (!playingRef.current) return;
      const currentDuration = Math.max(0, v2TimelineDuration(timelineRef.current));
      const next = Math.min(
        currentDuration,
        Math.max(0, playheadAtStartRef.current + (now - clockStartedAtMsRef.current) / 1000),
      );
      playheadRef.current = next;
      callbacksRef.current.onPlayheadChange(next);
      const newlyActive = synchronizeMedia(next, true);
      newlyActive.forEach((element) => {
        if (!playingRef.current) return;
        if (!element.paused || playRequestsRef.current.has(element)) return;
        const attempt = playbackAttemptRef.current;
        requestTrackedMediaPlay(playRequestsRef.current, element, attempt, (settledAttempt) => {
          if (!mountedRef.current || playbackAttemptRef.current !== settledAttempt) return;
          if (playingRef.current) stopPlayback(false);
        });
      });
      if (next >= currentDuration) {
        stopPlayback(false);
        return;
      }
      scheduleFrame();
    });
  }, [stopPlayback, synchronizeMedia]);

  const play = useCallback(() => {
    if (playingRef.current) return;
    const currentDuration = Math.max(0, v2TimelineDuration(timelineRef.current));
    if (currentDuration <= 0) return;
    const previousPlayhead = playheadRef.current;
    const startPlayhead = previousPlayhead >= currentDuration ? 0 : Math.max(0, previousPlayhead);
    const attempt = ++playbackAttemptRef.current;
    playheadRef.current = startPlayhead;
    if (startPlayhead !== previousPlayhead) callbacksRef.current.onPlayheadChange(startPlayhead);
    playheadAtStartRef.current = startPlayhead;
    clockStartedAtMsRef.current = performance.now();

    playingRef.current = true;
    callbacksRef.current.onPlayingChange(true);
    const activeElements = synchronizeMedia(startPlayhead, true);
    activeElements.forEach((element) => {
      if (!playingRef.current || playbackAttemptRef.current !== attempt) return;
      requestTrackedMediaPlay(playRequestsRef.current, element, attempt, (settledAttempt) => {
        if (!mountedRef.current || playbackAttemptRef.current !== settledAttempt) return;
        stopPlayback(false);
        playheadRef.current = previousPlayhead;
        callbacksRef.current.onPlayheadChange(previousPlayhead);
        synchronizeMedia(previousPlayhead, false);
      });
    });
    if (playingRef.current && playbackAttemptRef.current === attempt) scheduleFrame();
  }, [scheduleFrame, stopPlayback, synchronizeMedia]);

  const pause = useCallback(() => stopPlayback(false), [stopPlayback]);
  const togglePlayback = useCallback(() => {
    if (playingRef.current) pause();
    else play();
  }, [pause, play]);

  useImperativeHandle(ref, () => ({ play, pause, togglePlayback }), [pause, play, togglePlayback]);

  useEffect(() => {
    if (!playing && playingRef.current) pause();
    else if (playing && !playingRef.current) play();
  }, [pause, play, playing]);

  useEffect(() => {
    if (!playingRef.current) synchronizeMedia(playheadSeconds, false);
  }, [playheadSeconds, synchronizeMedia, timeline]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "hidden" && playingRef.current) pause();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [pause]);

  useEffect(() => {
    stopPlayback(true);
  }, [timeline.timeline_id, stopPlayback]);

  useEffect(() => {
    const refCallbacks = mediaRefCallbacks.current;
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      playbackAttemptRef.current += 1;
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
      pauseAllMedia(true);
      refCallbacks.clear();
    };
  }, [pauseAllMedia]);

  const markMediaFailed = useCallback((clipId: string, mediaKey: string) => {
    const next = new Set(failedMediaKeysRef.current).add(mediaKey);
    failedMediaKeysRef.current = next;
    setFailedMediaKeys(next);
    const element = mediaElements.current.get(clipId);
    if (!element) return;
    playRequestsRef.current.delete(element);
    element.pause();
    element.muted = true;
    element.volume = 0;
  }, []);

  const clearMediaFailure = useCallback((mediaKey: string) => {
    if (!failedMediaKeysRef.current.has(mediaKey)) return;
    const next = new Set(failedMediaKeysRef.current);
    next.delete(mediaKey);
    failedMediaKeysRef.current = next;
    setFailedMediaKeys(next);
  }, []);

  const updateMediaRef = useCallback((clipId: string, element: MediaElement | null) => {
    if (!element) {
      const previous = mediaElements.current.get(clipId);
      if (previous) {
        playRequestsRef.current.delete(previous);
        previous.pause();
        previous.muted = true;
        previous.volume = 0;
      }
      mediaElements.current.delete(clipId);
      return;
    }
    mediaElements.current.set(clipId, element);
    const activeElements = synchronizeMedia(playheadRef.current, playingRef.current);
    if (playingRef.current && activeElements.includes(element) && !playRequestsRef.current.has(element)) {
      const attempt = playbackAttemptRef.current;
      requestTrackedMediaPlay(playRequestsRef.current, element, attempt, (settledAttempt) => {
        if (!mountedRef.current || playbackAttemptRef.current !== settledAttempt) return;
        if (playingRef.current) stopPlayback(false);
      });
    }
  }, [stopPlayback, synchronizeMedia]);

  const mediaRefCallback = (clipId: string, mediaKey: string) => {
    const existing = mediaRefCallbacks.current.get(mediaKey);
    if (existing) return existing;
    const callback = (element: MediaElement | null) => updateMediaRef(clipId, element);
    mediaRefCallbacks.current.set(mediaKey, callback);
    return callback;
  };

  return (
    <section className="v2-composition-preview" aria-label="Composition preview">
      <div
        className="v2-composition-preview-stage"
        style={{ aspectRatio: timeline.aspect_ratio.replace(":", " / ") }}
      >
        {videos.map((clip) => {
          const mediaStatus = previewMediaStatus(sources, clip, failedMediaKeys);
          const source = mediaStatus.source;
          if (mediaStatus.status === "missing" || !source) return null;
          const urls = timelineSourceUrls(source, mediaUrl);
          const activeIndex = activeVisuals.findIndex((active) => active.clip_id === clip.clip_id);
          const active = activeIndex >= 0;
          return (
            <video
              key={mediaStatus.key}
              ref={mediaRefCallback(clip.clip_id, mediaStatus.key)}
              className={`v2-composition-preview-media is-video ${active && mediaStatus.status === "ready" ? "is-active" : "is-inactive"}`}
              data-source-in={clip.trim_in}
              data-source-out={clip.trim_out ?? clip.trim_in + clip.duration}
              src={urls.original}
              poster={urls.thumbnail || undefined}
              muted={clip.audio.muted || clip.muted}
              playsInline
              preload={shouldPreloadClip(clip, playheadSeconds, selectedClipId) ? "metadata" : "none"}
              style={{
                ...styleForVisualClip(clip),
                display: active && mediaStatus.status === "ready" ? "block" : "none",
                zIndex: activeIndex + 1,
              }}
              onError={() => markMediaFailed(clip.clip_id, mediaStatus.key)}
              onLoadedData={() => clearMediaFailure(mediaStatus.key)}
              onCanPlay={() => clearMediaFailure(mediaStatus.key)}
              onClick={() => onSelectClip(clip.clip_id)}
            />
          );
        })}
        {activeVisuals.filter((clip) => clip.clip_type === "image").map((clip) => {
          const mediaStatus = previewMediaStatus(sources, clip, failedMediaKeys);
          const source = mediaStatus.source;
          if (mediaStatus.status === "missing" || !source) return null;
          return (
            // Media lifecycle events are not user interaction handlers.
            // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
            <img
              key={mediaStatus.key}
              className="v2-composition-preview-media is-image is-active"
              src={timelineSourceUrls(source, mediaUrl).original}
              alt={source.display_name}
              style={{
                ...styleForVisualClip(clip),
                display: mediaStatus.status === "ready" ? "block" : "none",
                zIndex: activeVisuals.findIndex((active) => active.clip_id === clip.clip_id) + 1,
              }}
              onError={() => markMediaFailed(clip.clip_id, mediaStatus.key)}
              onLoad={() => clearMediaFailure(mediaStatus.key)}
            />
          );
        })}
        {audioClips.map((clip) => {
          const mediaStatus = previewMediaStatus(sources, clip, failedMediaKeys);
          const source = mediaStatus.source;
          if (mediaStatus.status === "missing" || !source) return null;
          return (
            <audio
              key={mediaStatus.key}
              ref={mediaRefCallback(clip.clip_id, mediaStatus.key)}
              src={timelineSourceUrls(source, mediaUrl).original}
              preload={shouldPreloadClip(clip, playheadSeconds, selectedClipId) ? "metadata" : "none"}
              onError={() => markMediaFailed(clip.clip_id, mediaStatus.key)}
              onLoadedData={() => clearMediaFailure(mediaStatus.key)}
              onCanPlay={() => clearMediaFailure(mediaStatus.key)}
            />
          );
        })}
        {activeVisuals.map((clip, activeIndex) => {
          const mediaStatus = previewMediaStatus(sources, clip, failedMediaKeys);
          if (mediaStatus.status === "ready") return null;
          return (
            <span
              key={`${mediaStatus.key}-fallback`}
              className={`v2-composition-preview-media-fallback is-${mediaStatus.status}`}
              role="img"
              aria-label={`${clip.clip_type === "image" ? "Image" : "Video"} media unavailable`}
              style={{ ...styleForVisualClip(clip), zIndex: activeIndex + 1 }}
            >
              <span>Media unavailable</span>
            </span>
          );
        })}
        {!activeVisuals.length && !activeSubtitles.length ? (
          <span className="v2-composition-preview-empty">Place a video on the timeline to preview it.</span>
        ) : null}
        {activeSubtitles.map((clip) => (
          <span className="v2-composition-subtitle" key={clip.clip_id}>{clip.text}</span>
        ))}
        <button
          className="v2-composition-preview-play"
          type="button"
          aria-label={playing ? "Pause preview" : "Play preview"}
          title={playing ? "Pause preview" : "Play preview"}
          onClick={() => {
            togglePlayback();
            onSelectClip(topVideo?.clip_id ?? selectedClipId);
          }}
        >
          {playing ? <span aria-hidden="true">II</span> : <PlayIcon />}
        </button>
      </div>
      <div className="v2-composition-transport">
        <input
          aria-label="Preview playhead"
          type="range"
          min="0"
          max={Math.max(duration, 0.01)}
          step={1 / Math.max(1, timeline.fps)}
          value={Math.min(playheadSeconds, Math.max(duration, 0.01))}
          onChange={(event) => {
            if (playingRef.current) pause();
            onPlayheadChange(Number(event.target.value));
          }}
        />
        <span>{formatTime(playheadSeconds)} / {formatTime(duration)}</span>
      </div>
    </section>
  );
});

function styleForVisualClip(clip: V2FinalTimelineClip): CSSProperties {
  const color = clip.color;
  const transform = clip.transform;
  const preset = presetColorAdjustments(color.preset_id);
  const brightness = Math.max(0, 1 + color.brightness + color.exposure / 4 + preset.brightness);
  const contrast = Math.max(0, color.contrast * preset.contrast);
  const saturation = Math.max(0, color.saturation * preset.saturation);
  const hue = color.hue + color.temperature * 0.12 + color.tint * 0.08 + preset.hue;
  return {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    filter: `brightness(${brightness}) contrast(${contrast}) saturate(${saturation}) hue-rotate(${hue}deg)`,
    opacity: transform.opacity,
    objectFit: transform.fit,
    transform: `translate(${transform.x * 50}%, ${transform.y * 50}%) scale(${transform.scale_x}, ${transform.scale_y}) rotate(${transform.rotation_degrees}deg)`,
    transformOrigin: "center",
  };
}

function presetColorAdjustments(preset: V2FinalTimelineClip["color"]["preset_id"]) {
  if (preset === "warm") return { brightness: 0.03, contrast: 1, saturation: 1.08, hue: 8 };
  if (preset === "cool") return { brightness: 0, contrast: 1, saturation: 1.04, hue: -10 };
  if (preset === "high_contrast") return { brightness: 0, contrast: 1.2, saturation: 1.08, hue: 0 };
  if (preset === "muted") return { brightness: 0.02, contrast: 0.92, saturation: 0.72, hue: 0 };
  return { brightness: 0, contrast: 1, saturation: 1, hue: 0 };
}

function shouldPreloadClip(clip: V2FinalTimelineClip, playheadSeconds: number, selectedClipId: string | null) {
  if (clip.clip_id === selectedClipId) return true;
  return playheadSeconds >= clip.start_time - 4 && playheadSeconds <= clip.start_time + clip.duration + 4;
}

function safelySeek(element: MediaElement, target: number) {
  try {
    if (typeof element.fastSeek === "function") element.fastSeek(target);
    else element.currentTime = target;
  } catch {
    safelySetCurrentTime(element, target);
  }
}

function safelySetCurrentTime(element: MediaElement, target: number) {
  try {
    element.currentTime = target;
  } catch {
    // Metadata may not be loaded yet; the next synchronization pass will retry.
  }
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 1));
}

function formatTime(value: number) {
  const minutes = Math.floor(Math.max(0, value) / 60);
  const seconds = Math.floor(Math.max(0, value) % 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
