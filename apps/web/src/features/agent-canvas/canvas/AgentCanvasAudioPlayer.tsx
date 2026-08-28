import { useEffect, useState, type CSSProperties } from "react";

import { formatAudioTime, useAudioPlayback } from "../../../components/audio/useAudioPlayback.ts";
import {
  FastForwardIcon,
  PauseIcon,
  PlayIcon,
  RewindIcon,
  StarIcon,
} from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";

const AUDIO_TITLE_LIMIT = 58;
const AUDIO_SKIP_SECONDS = 5;

function promptExcerpt(node: CanvasNodeV2, asset?: ProjectAssetSummaryV2 | null) {
  const prompt = (node.generation_prompt ?? node.summary_prompt ?? asset?.display_name ?? "Generated audio")
    .replace(/\s+/g, " ")
    .trim();
  if (prompt.length <= AUDIO_TITLE_LIMIT) return prompt;
  return `${prompt.slice(0, AUDIO_TITLE_LIMIT - 3).trimEnd()}...`;
}

function playerTitle(
  node: CanvasNodeV2,
  status: CanvasNodeStatusV2,
  asset?: ProjectAssetSummaryV2 | null,
) {
  if (status === "draft") return "No audio yet";
  if (status === "working") return "Generating...";
  if (status === "failed") return "Generation failed";
  return promptExcerpt(node, asset);
}

function stopCanvasInteraction(event: { stopPropagation: () => void }) {
  event.stopPropagation();
}

export function AgentCanvasAudioPlayer({
  node,
  status,
  asset,
}: {
  node: CanvasNodeV2;
  status: CanvasNodeStatusV2;
  asset?: ProjectAssetSummaryV2 | null;
}) {
  const playable = status === "ready" && asset?.status === "ready";
  const src = playable ? asset?.media_url ?? null : null;
  const [favorite, setFavorite] = useState(false);
  const playback = useAudioPlayback({
    src,
    durationSeconds: playable ? asset?.duration_seconds : null,
    playbackGroup: `agent-canvas:${node.workflow_id}`,
  });

  useEffect(() => setFavorite(false), [asset?.asset_id]);

  const progress = playback.totalSeconds > 0
    ? Math.min(100, (playback.elapsedSeconds / playback.totalSeconds) * 100)
    : 0;
  const remainingSeconds = Math.max(0, playback.totalSeconds - playback.elapsedSeconds);
  const progressStyle = { "--audio-progress": `${progress}%` } as CSSProperties;
  const controlsDisabled = !playable || playback.controlsDisabled;
  const title = playback.mediaUnavailable
    ? "Audio unavailable"
    : playback.playbackError ?? playerTitle(node, status, asset);

  return (
    <section
      className={`agent-canvas-audio-player agent-canvas-audio-player--${status}`}
      aria-label="Audio player"
    >
      <audio ref={playback.audioRef} src={src ?? undefined} preload="none" />

      <div
        className="agent-canvas-audio-player__title"
        role={playback.mediaUnavailable || playback.playbackError ? "alert" : undefined}
      >
        {title}
      </div>

      {status === "working" ? (
        <div
          className="agent-canvas-audio-player__waveform"
          role="status"
          aria-label="Generating audio waveform"
        >
          {Array.from({ length: 28 }, (_, index) => (
            <i key={index} style={{ "--wave-index": index } as CSSProperties} />
          ))}
        </div>
      ) : (
        <div
          className="agent-canvas-audio-player__timeline nodrag nopan nowheel"
        >
          <input
            className="agent-canvas-audio-player__seek"
            type="range"
            min="0"
            max={playback.totalSeconds || 1}
            step="0.01"
            value={playback.elapsedSeconds}
            style={progressStyle}
            aria-label="Seek audio"
            aria-valuetext={`${formatAudioTime(playback.elapsedSeconds)} of ${formatAudioTime(playback.totalSeconds)}`}
            disabled={controlsDisabled}
            onPointerDown={stopCanvasInteraction}
            onClick={stopCanvasInteraction}
            onChange={(event) => playback.seekTo(Number(event.currentTarget.value))}
          />
          <span>{formatAudioTime(playback.elapsedSeconds)}</span>
          <span>-{formatAudioTime(remainingSeconds)}</span>
        </div>
      )}

      <div
        className="agent-canvas-audio-player__footer nodrag nopan nowheel"
      >
        <button
          className={`agent-canvas-audio-player__control agent-canvas-audio-player__favorite${favorite ? " is-active" : ""}`}
          type="button"
          aria-label={favorite ? "Remove audio from favorites" : "Add audio to favorites"}
          aria-pressed={favorite}
          disabled={controlsDisabled}
          onPointerDown={stopCanvasInteraction}
          onClick={(event) => {
            stopCanvasInteraction(event);
            setFavorite((current) => !current);
          }}
        >
          <StarIcon />
        </button>

        <div className="agent-canvas-audio-player__transport">
          <button
            className="agent-canvas-audio-player__control"
            type="button"
            aria-label={`Rewind audio ${AUDIO_SKIP_SECONDS} seconds`}
            disabled={controlsDisabled}
            onPointerDown={stopCanvasInteraction}
            onClick={(event) => {
              stopCanvasInteraction(event);
              playback.skipBy(-AUDIO_SKIP_SECONDS);
            }}
          >
            <RewindIcon />
          </button>
          <button
            className="agent-canvas-audio-player__control agent-canvas-audio-player__control--primary"
            type="button"
            aria-label={playback.isPlaying ? "Pause audio" : "Play audio"}
            disabled={controlsDisabled}
            onPointerDown={stopCanvasInteraction}
            onClick={(event) => {
              stopCanvasInteraction(event);
              playback.togglePlayback();
            }}
          >
            {playback.isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>
          <button
            className="agent-canvas-audio-player__control"
            type="button"
            aria-label={`Fast-forward audio ${AUDIO_SKIP_SECONDS} seconds`}
            disabled={controlsDisabled}
            onPointerDown={stopCanvasInteraction}
            onClick={(event) => {
              stopCanvasInteraction(event);
              playback.skipBy(AUDIO_SKIP_SECONDS);
            }}
          >
            <FastForwardIcon />
          </button>
        </div>

        <span aria-hidden="true" />
      </div>
    </section>
  );
}
