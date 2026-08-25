import { useEffect, useMemo, useRef, useState } from "react";

import { VideoIcon } from "../../../icons.tsx";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import {
  buildTimelineSegments,
  mapTimelineTimeToSource,
} from "./editingTimelineMath.ts";
import type { EditingInputs } from "./editingModel.ts";

const MEDIA_SYNC_TOLERANCE_SECONDS = 0.2;
const TIMELINE_END_TOLERANCE_SECONDS = 0.01;

type PreviewView = "draft" | "export";

export interface EditingPreviewStageProps {
  inputs: EditingInputs;
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

function segmentInputs(inputs: EditingInputs) {
  return inputs.videos.map((input) => ({
    referenceId: input.referenceId,
    sourceDuration: input.asset?.duration_seconds
      ?? input.entry.trim_end_seconds
      ?? input.entry.trim_start_seconds + 0.5,
    trimStart: input.entry.trim_start_seconds,
    trimEnd: input.entry.trim_end_seconds,
  }));
}

function currentSourceMatches(media: HTMLMediaElement, expectedUrl: string): boolean {
  const currentSource = media.currentSrc;
  if (!currentSource) return true;
  try {
    return currentSource === new URL(expectedUrl, document.baseURI).href;
  } catch {
    return false;
  }
}

function seekWithinTolerance(media: HTMLMediaElement, seconds: number) {
  if (Math.abs(media.currentTime - seconds) <= MEDIA_SYNC_TOLERANCE_SECONDS) return;
  try {
    media.currentTime = seconds;
  } catch {
    // Metadata may not be available yet; loadedmetadata retries the seek.
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
}: EditingPreviewStageProps) {
  const [view, setView] = useState<PreviewView>("draft");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const playAttemptRef = useRef(0);
  const playingRef = useRef(playing);
  const onPlayingChangeRef = useRef(onPlayingChange);
  playingRef.current = playing;
  onPlayingChangeRef.current = onPlayingChange;

  const segments = useMemo(() => buildTimelineSegments(segmentInputs(inputs)), [inputs]);
  const sequenceDuration = segments.at(-1)?.timelineEnd ?? 0;
  const mapping = mapTimelineTimeToSource(segments, playheadSeconds);
  const activeInput = mapping
    ? inputs.videos.find((input) => input.referenceId === mapping.referenceId) ?? null
    : null;
  const activeMediaUrl = activeInput?.entry.enabled ? activeInput.asset?.media_url ?? null : null;
  const exportedMediaUrl = exportedAsset?.status === "ready" ? exportedAsset.media_url : null;
  const ratio = parseAspectRatio(outputAspectRatio)
    ?? parseResolution(outputResolution)
    ?? assetRatio(exportedAsset)
    ?? assetRatio(activeInput?.asset ?? null)
    ?? [16, 9];
  const bgm = inputs.bgm;
  const bgmUrl = bgm?.asset?.status === "ready" ? bgm.asset.media_url : null;
  const atTimelineEnd = sequenceDuration > 0
    && playheadSeconds >= sequenceDuration - TIMELINE_END_TOLERANCE_SECONDS;

  useEffect(() => {
    if (!exportedMediaUrl && view === "export") setView("draft");
  }, [exportedMediaUrl, view]);

  useEffect(() => {
    if (sequenceDuration <= 0 || playheadSeconds <= sequenceDuration) return;
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

    if (view === "draft" && bgm.entry.enabled && withinTrim) {
      seekWithinTolerance(audio, bgmSeconds);
    }

    if (
      view !== "draft"
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
  }, [atTimelineEnd, bgm, bgmUrl, muted, playheadSeconds, playing, view]);

  const syncActiveVideo = (video: HTMLVideoElement) => {
    if (
      video !== videoRef.current
      || !mapping
      || !activeMediaUrl
      || video.getAttribute("src") !== activeMediaUrl
      || !currentSourceMatches(video, activeMediaUrl)
    ) return;
    seekWithinTolerance(video, mapping.sourceSeconds);
  };

  const handleTimeUpdate = (video: HTMLVideoElement) => {
    if (
      video !== videoRef.current
      || !mapping
      || !activeMediaUrl
      || video.getAttribute("src") !== activeMediaUrl
      || !currentSourceMatches(video, activeMediaUrl)
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
      video !== videoRef.current
      || !mapping
      || !activeMediaUrl
      || video.getAttribute("src") !== activeMediaUrl
      || !currentSourceMatches(video, activeMediaUrl)
    ) return;
    onPlayheadChange(mapping.timelineEnd);
    if (mapping.timelineEnd >= sequenceDuration - TIMELINE_END_TOLERANCE_SECONDS) {
      onPlayingChange(false);
    }
  };

  const showDraft = () => {
    setView("draft");
    onPlayingChange(false);
  };
  const showExport = () => {
    pauseMedia(videoRef.current);
    pauseMedia(bgmRef.current);
    onPlayingChange(false);
    setView("export");
  };

  return (
    <div
      className="agent-editing-preview"
      style={{ display: "flex", width: "100%", height: "100%", minHeight: 0, flexDirection: "column" }}
    >
      {exportedMediaUrl ? (
        <div className="agent-editing-preview__views" role="tablist" aria-label="Preview source">
          <button type="button" role="tab" aria-selected={view === "draft"} onClick={showDraft}>Draft preview</button>
          <button type="button" role="tab" aria-selected={view === "export"} onClick={showExport}>Exported output</button>
        </div>
      ) : <span className="agent-editing-preview__label">Draft preview</span>}
      <div
        className="agent-editing-preview__canvas"
        style={{ display: "grid", width: "100%", minHeight: 0, flex: 1, overflow: "hidden", placeItems: "center" }}
      >
        <div
          className="agent-editing-preview__frame"
          data-testid="editing-preview-frame"
          style={{ aspectRatio: `${ratio[0]} / ${ratio[1]}`, width: "100%", maxWidth: "100%", maxHeight: "100%" }}
        >
          {view === "export" && exportedMediaUrl ? (
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
          ) : activeMediaUrl ? (
            <video
              ref={videoRef}
              className="agent-editing-preview__video agent-editing-preview__video--contain"
              data-testid="editing-preview-video"
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
