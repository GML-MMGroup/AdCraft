import { MuteIcon, PauseIcon, PlayIcon, UnmuteIcon } from "../../../icons.tsx";
import { formatAudioTime, useAudioPlayback } from "../../../components/audio/useAudioPlayback.ts";

export interface V2AudioPlayerProps {
  src: string | null;
  label: string;
  durationSeconds?: number | null;
  playbackGroup: string;
  compact?: boolean;
}

export function V2AudioPlayer({ src, label, durationSeconds, playbackGroup, compact = false }: V2AudioPlayerProps) {
  const {
    audioRef,
    controlsDisabled,
    elapsedSeconds,
    hasSource,
    isLoading,
    isMuted,
    isPlaying,
    mediaUnavailable,
    playbackError,
    seekTo,
    toggleMute,
    togglePlayback,
    totalSeconds,
  } = useAudioPlayback({ src, durationSeconds, playbackGroup });

  function stopCanvasPropagation(event: { stopPropagation: () => void }) {
    event.stopPropagation();
  }

  function handleSeek(value: string) {
    seekTo(Number(value));
  }

  const playLabel = `${isPlaying ? "Pause" : "Play"} ${label}`;
  const muteLabel = `${isMuted ? "Unmute" : "Mute"} ${label}`;

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events -- The player contains native controls and must prevent their interactions from bubbling to its canvas card.
    <section
      className={`v2-audio-player nodrag nopan${compact ? " is-compact" : ""}${controlsDisabled ? " is-unavailable" : ""}`}
      aria-label={`${label} audio player`}
      onPointerDown={stopCanvasPropagation}
      onClick={stopCanvasPropagation}
    >
      <audio ref={audioRef} src={src ?? undefined} preload="metadata" />
      <div className="v2-audio-player-controls">
        <button className="v2-audio-player-icon" type="button" aria-label={playLabel} title={playLabel} onClick={togglePlayback} disabled={controlsDisabled}>
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>
        <div className="v2-audio-player-seek-wrap">
          <input
            className="v2-audio-player-seek"
            type="range"
            min="0"
            max={totalSeconds}
            step="0.01"
            value={elapsedSeconds}
            aria-label={`Seek ${label}`}
            aria-valuetext={`${formatAudioTime(elapsedSeconds)} of ${formatAudioTime(totalSeconds)}`}
            onChange={(event) => handleSeek(event.currentTarget.value)}
            disabled={controlsDisabled}
          />
          <span className="v2-audio-player-time">{formatAudioTime(elapsedSeconds)} / {formatAudioTime(totalSeconds)}</span>
        </div>
        <button className="v2-audio-player-icon" type="button" aria-label={muteLabel} title={muteLabel} onClick={toggleMute} disabled={controlsDisabled}>
          {isMuted ? <MuteIcon /> : <UnmuteIcon />}
        </button>
      </div>
      {!hasSource ? <span className="v2-audio-player-status">Audio unavailable.</span> : null}
      {isLoading ? <span className="v2-audio-player-status" role="status">Loading {label} audio.</span> : null}
      {mediaUnavailable ? <span className="v2-audio-player-status" role="alert">Audio unavailable.</span> : null}
      {playbackError ? <span className="v2-audio-player-status" role="alert">{playbackError}</span> : null}
    </section>
  );
}
