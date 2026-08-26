import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { VideoIcon } from "../../../icons.tsx";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mapTimelineTimeToSource } from "./editingTimelineMath.ts";
import type { EditingInputs } from "./editingModel.ts";
import {
  buildPlayableEditingSequence,
  type PlayableEditingSequence,
} from "./editingPlayableSequence.ts";
import { fitContainedFrame } from "./editingPreviewSizing.ts";

const MEDIA_SYNC_TOLERANCE_SECONDS = 0.2;
const TIMELINE_END_TOLERANCE_SECONDS = 0.01;

type PreviewView = "draft" | "export";

export interface EditingPreviewStageProps {
  inputs: EditingInputs;
  sequence?: PlayableEditingSequence;
  outputAspectRatio: string | null;
  outputResolution: string | null;
  exportedAsset: ProjectAssetSummaryV2 | null;
  playheadSeconds: number;
  playing: boolean;
  muted: boolean;
  onPlayheadChange: (seconds: number) => void;
  onPlayingChange: (playing: boolean) => void;
}

function positivePair(first: number | null, second: number | null): [number, number] | null {
  return first !== null
    && second !== null
    && Number.isFinite(first)
    && Number.isFinite(second)
    && first > 0
    && second > 0
    ? [first, second]
    : null;
}

function parseAspectRatio(value: string | null): [number, number] | null {
  if (!value) return null;
  const match = value.trim().match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/);
  return match ? positivePair(Number(match[1]), Number(match[2])) : null;
}

function parseResolution(value: string | null): [number, number] | null {
  if (!value) return null;
  const match = value.trim().match(/^(\d+)\s*[xX]\s*(\d+)$/);
  return match ? positivePair(Number(match[1]), Number(match[2])) : null;
}

function assetRatio(asset: ProjectAssetSummaryV2 | null): [number, number] | null {
  return positivePair(asset?.width ?? null, asset?.height ?? null);
}

function seekWithinTolerance(media: HTMLMediaElement, seconds: number) {
  if (Math.abs(media.currentTime - seconds) <= MEDIA_SYNC_TOLERANCE_SECONDS) return;
  try {
    media.currentTime = seconds;
  } catch {
    // Metadata may not be available yet; loadedmetadata retries the seek.
  }
}

function seekExactly(media: HTMLMediaElement, seconds: number) {
  if (media.currentTime === seconds) return;
  try {
    media.currentTime = seconds;
  } catch {
    // Media metadata can still be loading; the next controlled update retries.
  }
}

function pauseMedia(media: HTMLMediaElement | null) {
  if (media) media.pause();
}

export function EditingPreviewStage({
  exportedAsset,
  inputs,
  muted,
  onPlayheadChange,
  onPlayingChange,
  outputAspectRatio,
  outputResolution,
  playheadSeconds,
  playing,
  sequence,
}: EditingPreviewStageProps) {
  const [view, setView] = useState<PreviewView>("draft");
  const previewId = useId();
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const draftTabRef = useRef<HTMLButtonElement | null>(null);
  const exportTabRef = useRef<HTMLButtonElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const playAttemptRef = useRef(0);
  const loadGenerationRef = useRef<{
    generation: number;
    identity: string | null;
    token: string | null;
  }>({ generation: 0, identity: null, token: null });
  const activeLoadTokenRef = useRef<string | null>(null);
  const playingRef = useRef(playing);
  const onPlayingChangeRef = useRef(onPlayingChange);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  playingRef.current = playing;
  onPlayingChangeRef.current = onPlayingChange;

  const activeSequence = useMemo(
    () => sequence ?? buildPlayableEditingSequence(inputs.videos),
    [inputs.videos, sequence],
  );
  const sequenceDuration = activeSequence.duration;
  const mapping = mapTimelineTimeToSource(activeSequence.segments, playheadSeconds);
  const activeInput = mapping
    ? activeSequence.videos.find((input) => input.referenceId === mapping.referenceId) ?? null
    : null;
  const activeMediaUrl = activeInput?.asset?.media_url ?? null;
  const loadIdentity = activeInput && activeMediaUrl
    ? JSON.stringify([activeInput.referenceId, activeMediaUrl])
    : null;
  if (loadGenerationRef.current.identity !== loadIdentity) {
    const generation = loadGenerationRef.current.generation + 1;
    loadGenerationRef.current = {
      generation,
      identity: loadIdentity,
      token: loadIdentity
        ? JSON.stringify([generation, activeInput?.referenceId, activeMediaUrl])
        : null,
    };
  }
  const loadToken = loadGenerationRef.current.token;
  const exportedMediaUrl = exportedAsset?.status === "ready" ? exportedAsset.media_url : null;
  const ratio = parseAspectRatio(outputAspectRatio)
    ?? parseResolution(outputResolution)
    ?? assetRatio(exportedAsset)
    ?? assetRatio(activeInput?.asset ?? null)
    ?? [16, 9];
  const ratioValue = ratio[0] / ratio[1];
  const frameSize = fitContainedFrame(canvasSize.width, canvasSize.height, ratioValue);
  const bgm = inputs.bgm;
  const bgmUrl = bgm?.asset?.status === "ready" ? bgm.asset.media_url : null;
  const atTimelineEnd = sequenceDuration > 0
    && playheadSeconds >= sequenceDuration - TIMELINE_END_TOLERANCE_SECONDS;

  useLayoutEffect(() => {
    activeLoadTokenRef.current = loadToken;
    return () => {
      if (activeLoadTokenRef.current === loadToken) activeLoadTokenRef.current = null;
    };
  }, [loadToken]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const measure = () => {
      const bounds = canvas.getBoundingClientRect();
      const next = {
        width: Math.max(0, bounds.width),
        height: Math.max(0, bounds.height),
      };
      setCanvasSize((current) => (
        current.width === next.width && current.height === next.height ? current : next
      ));
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(canvas);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  useEffect(() => {
    if (!exportedMediaUrl && view === "export") setView("draft");
  }, [exportedMediaUrl, view]);

  useEffect(() => {
    if (sequenceDuration <= 0) {
      if (playheadSeconds > 0) onPlayheadChange(0);
      if (playing) onPlayingChange(false);
      return;
    }
    if (playheadSeconds <= sequenceDuration) return;
    onPlayheadChange(sequenceDuration);
    if (playing) onPlayingChange(false);
  }, [onPlayheadChange, onPlayingChange, playheadSeconds, playing, sequenceDuration]);

  useEffect(() => {
    const video = videoRef.current;
    const attempt = ++playAttemptRef.current;
    if (
      view !== "draft"
      || !video
      || !mapping
      || !activeInput
      || !activeMediaUrl
      || !loadToken
      || video.dataset.loadToken !== loadToken
      || video.getAttribute("src") !== activeMediaUrl
    ) {
      pauseMedia(video);
      if (playing && (view !== "draft" || !mapping || !activeMediaUrl)) {
        onPlayingChangeRef.current(false);
      }
      return;
    }

    video.muted = muted || !activeInput.entry.preserve_native_audio;
    video.volume = Math.min(1, Math.max(0, activeInput.entry.volume));
    seekWithinTolerance(video, mapping.sourceSeconds);

    if (!playing || atTimelineEnd) {
      pauseMedia(video);
      if (playing && atTimelineEnd) onPlayingChangeRef.current(false);
      return;
    }

    if (video.paused) {
      try {
        void video.play().catch(() => {
          if (playAttemptRef.current === attempt && playingRef.current) {
            onPlayingChangeRef.current(false);
          }
        });
      } catch {
        if (playAttemptRef.current === attempt && playingRef.current) {
          onPlayingChangeRef.current(false);
        }
      }
    }
  }, [
    activeInput,
    activeMediaUrl,
    atTimelineEnd,
    mapping,
    muted,
    playing,
    loadToken,
    view,
  ]);

  useEffect(() => {
    const audio = bgmRef.current;
    if (!audio || !bgm || !bgmUrl || audio.getAttribute("src") !== bgmUrl) {
      pauseMedia(audio);
      return;
    }

    const bgmTimelineSeconds = bgm.entry.trim_start_seconds + playheadSeconds;
    const bgmDuration = bgm.asset?.duration_seconds ?? 0;
    const bgmSeconds = bgm.entry.trim_end_seconds === null && bgmDuration > 0
      ? bgmTimelineSeconds % bgmDuration
      : bgmTimelineSeconds;
    const withinTrim = bgm.entry.trim_end_seconds === null
      || bgmTimelineSeconds < bgm.entry.trim_end_seconds;
    audio.muted = muted;
    audio.volume = Math.min(1, Math.max(0, bgm.entry.volume));

    if (view === "draft" && sequenceDuration > 0 && bgm.entry.enabled && withinTrim) {
      seekExactly(audio, bgmSeconds);
    }

    if (
      view !== "draft"
      || sequenceDuration <= 0
      || !bgm.entry.enabled
      || !withinTrim
      || !playing
      || atTimelineEnd
    ) {
      pauseMedia(audio);
      return;
    }

    if (audio.paused) {
      try {
        void audio.play().catch(() => undefined);
      } catch {
        // Draft playback remains usable when browser autoplay policy blocks BGM.
      }
    }
  }, [atTimelineEnd, bgm, bgmUrl, muted, playheadSeconds, playing, sequenceDuration, view]);

  const isActiveLoadEvent = (video: HTMLVideoElement): boolean => (
    loadToken !== null
    && video.dataset.loadToken === loadToken
    && activeLoadTokenRef.current === loadToken
  );

  const syncActiveVideo = (video: HTMLVideoElement) => {
    if (
      !isActiveLoadEvent(video)
      || !mapping
      || !activeMediaUrl
    ) return;
    seekWithinTolerance(video, mapping.sourceSeconds);
  };

  const handleTimeUpdate = (video: HTMLVideoElement) => {
    if (
      !isActiveLoadEvent(video)
      || !mapping
      || !activeMediaUrl
    ) return;

    const reachedSegmentEnd = video.currentTime
      >= mapping.sourceEnd - TIMELINE_END_TOLERANCE_SECONDS;
    const next = reachedSegmentEnd
      ? mapping.timelineEnd
      : Math.min(
          mapping.timelineEnd,
          mapping.timelineStart + Math.max(0, video.currentTime - mapping.sourceStart),
        );
    onPlayheadChange(next);
    if (next >= sequenceDuration - TIMELINE_END_TOLERANCE_SECONDS) {
      pauseMedia(video);
      pauseMedia(bgmRef.current);
      onPlayingChange(false);
    }
  };

  const handleEnded = (video: HTMLVideoElement) => {
    if (
      !isActiveLoadEvent(video)
      || !mapping
      || !activeMediaUrl
    ) return;
    onPlayheadChange(mapping.timelineEnd);
    if (mapping.timelineEnd >= sequenceDuration - TIMELINE_END_TOLERANCE_SECONDS) {
      onPlayingChange(false);
    }
  };

  const selectView = (next: PreviewView) => {
    pauseMedia(videoRef.current);
    pauseMedia(bgmRef.current);
    onPlayingChange(false);
    setView(next);
  };
  const handleTabKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    current: PreviewView,
  ) => {
    let next: PreviewView | null = null;
    if (event.key === "Home") next = "draft";
    if (event.key === "End") next = "export";
    if (event.key === "ArrowRight") next = current === "draft" ? "export" : "draft";
    if (event.key === "ArrowLeft") next = current === "draft" ? "export" : "draft";
    if (!next) return;
    event.preventDefault();
    selectView(next);
    (next === "draft" ? draftTabRef.current : exportTabRef.current)?.focus();
  };

  const draftTabId = `${previewId}-draft-tab`;
  const exportTabId = `${previewId}-export-tab`;
  const draftPanelId = `${previewId}-draft-panel`;
  const exportPanelId = `${previewId}-export-panel`;
  const frameStyle = {
    aspectRatio: `${ratio[0]} / ${ratio[1]}`,
    width: frameSize.width,
    height: frameSize.height,
    maxWidth: "100%",
    maxHeight: "100%",
  };

  return (
    <div
      className="agent-editing-preview"
      style={{ display: "flex", width: "100%", height: "100%", minHeight: 0, flexDirection: "column" }}
    >
      {exportedMediaUrl ? (
        <div className="agent-editing-preview__views" role="tablist" aria-label="Preview source">
          <button
            ref={draftTabRef}
            id={draftTabId}
            type="button"
            role="tab"
            tabIndex={view === "draft" ? 0 : -1}
            aria-selected={view === "draft"}
            aria-controls={draftPanelId}
            onKeyDown={(event) => handleTabKeyDown(event, "draft")}
            onClick={() => selectView("draft")}
          >Draft preview</button>
          <button
            ref={exportTabRef}
            id={exportTabId}
            type="button"
            role="tab"
            tabIndex={view === "export" ? 0 : -1}
            aria-selected={view === "export"}
            aria-controls={exportPanelId}
            onKeyDown={(event) => handleTabKeyDown(event, "export")}
            onClick={() => selectView("export")}
          >Exported output</button>
        </div>
      ) : <span className="agent-editing-preview__label">Draft preview</span>}
      <div
        ref={canvasRef}
        className="agent-editing-preview__canvas"
        style={{ display: "grid", width: "100%", minHeight: 0, flex: 1, overflow: "hidden", placeItems: "center" }}
      >
        <div
          id={exportedMediaUrl ? draftPanelId : undefined}
          role={exportedMediaUrl ? "tabpanel" : undefined}
          aria-labelledby={exportedMediaUrl ? draftTabId : undefined}
          hidden={Boolean(exportedMediaUrl) && view !== "draft"}
          className="agent-editing-preview__frame"
          data-testid={view === "draft" ? "editing-preview-frame" : undefined}
          style={frameStyle}
        >
          {activeMediaUrl ? (
            <video
              key={loadToken}
              ref={videoRef}
              className="agent-editing-preview__video agent-editing-preview__video--contain"
              data-testid="editing-preview-video"
              data-load-token={loadToken ?? undefined}
              src={activeMediaUrl}
              poster={activeInput?.asset?.preview_url ?? undefined}
              aria-label="Draft timeline preview"
              playsInline
              preload="auto"
              onLoadedMetadata={(event) => syncActiveVideo(event.currentTarget)}
              onTimeUpdate={(event) => handleTimeUpdate(event.currentTarget)}
              onEnded={(event) => handleEnded(event.currentTarget)}
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          ) : (
            <div className="agent-editing-panel__preview-empty">
              <VideoIcon aria-hidden="true" />
              <span>No playable source at playhead</span>
            </div>
          )}
        </div>
        {exportedMediaUrl ? (
          <div
            id={exportPanelId}
            role="tabpanel"
            aria-labelledby={exportTabId}
            hidden={view !== "export"}
            className="agent-editing-preview__frame"
            data-testid={view === "export" ? "editing-preview-frame" : undefined}
            style={frameStyle}
          >
            <video
              className="agent-editing-preview__video agent-editing-preview__video--contain"
              data-testid="editing-preview-export"
              src={exportedMediaUrl}
              poster={exportedAsset?.preview_url ?? undefined}
              controls
              playsInline
              preload="metadata"
              muted={muted}
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          </div>
        ) : null}
      </div>
      {bgmUrl ? (
        <audio
          ref={bgmRef}
          data-testid="editing-preview-bgm"
          src={bgmUrl}
          preload="auto"
          loop={bgm?.entry.trim_end_seconds === null}
          aria-hidden="true"
        />
      ) : null}
    </div>
  );
}
