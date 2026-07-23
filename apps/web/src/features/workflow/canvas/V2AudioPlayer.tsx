import { useEffect, useRef, useState } from "react";

import { MuteIcon, PauseIcon, PlayIcon, UnmuteIcon } from "../../../icons.tsx";

export interface V2AudioPlayerProps {
  src: string | null;
  label: string;
  durationSeconds?: number | null;
  playbackGroup: string;
  compact?: boolean;
}

const activeAudioByGroup = new Map<string, HTMLAudioElement>();

function claimPlayback(group: string, audio: HTMLAudioElement) {
  const active = activeAudioByGroup.get(group);
  if (active && active !== audio) active.pause();
  activeAudioByGroup.set(group, audio);
}

function releasePlayback(group: string, audio: HTMLAudioElement) {
  if (activeAudioByGroup.get(group) === audio) activeAudioByGroup.delete(group);
}

function boundedSeconds(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function formatTime(seconds: number) {
  const wholeSeconds = Math.floor(Math.max(0, seconds));
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

export function V2AudioPlayer({ src, label, durationSeconds, playbackGroup, compact = false }: V2AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [knownDuration, setKnownDuration] = useState(() => boundedSeconds(durationSeconds));
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [mediaUnavailable, setMediaUnavailable] = useState(false);
  const [playbackError, setPlaybackError] = useState<string | null>(null);

  const hasSource = Boolean(src);
  const controlsDisabled = !hasSource || mediaUnavailable;
  const totalSeconds = knownDuration || boundedSeconds(durationSeconds);
  const seekSeconds = totalSeconds > 0 ? Math.min(elapsedSeconds, totalSeconds) : elapsedSeconds;

  useEffect(() => {
    setElapsedSeconds(0);
    setKnownDuration(boundedSeconds(durationSeconds));
    setIsPlaying(false);
    setMediaUnavailable(false);
    setPlaybackError(null);
  }, [src, durationSeconds]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;

    const syncDuration = () => setKnownDuration(boundedSeconds(audio.duration) || boundedSeconds(durationSeconds));
    const syncElapsed = () => setElapsedSeconds(boundedSeconds(audio.currentTime));
    const onPlay = () => {
      setIsPlaying(true);
      setPlaybackError(null);
    };
    const onPause = () => {
      setIsPlaying(false);
      releasePlayback(playbackGroup, audio);
    };
    const onEnded = () => {
      setElapsedSeconds(0);
      setIsPlaying(false);
      releasePlayback(playbackGroup, audio);
    };
    const onError = () => {
      setIsPlaying(false);
      setMediaUnavailable(true);
      setPlaybackError(null);
      releasePlayback(playbackGroup, audio);
    };

    audio.addEventListener("loadedmetadata", syncDuration);
    audio.addEventListener("durationchange", syncDuration);
    audio.addEventListener("timeupdate", syncElapsed);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);

    return () => {
      audio.removeEventListener("loadedmetadata", syncDuration);
      audio.removeEventListener("durationchange", syncDuration);
      audio.removeEventListener("timeupdate", syncElapsed);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      releasePlayback(playbackGroup, audio);
    };
  }, [durationSeconds, playbackGroup]);

  function stopCanvasPropagation(event: { stopPropagation: () => void }) {
    event.stopPropagation();
  }

  function handleTogglePlayback() {
    const audio = audioRef.current;
    if (!audio || controlsDisabled) return;

    if (isPlaying) {
      audio.pause();
      return;
    }

    claimPlayback(playbackGroup, audio);
    const playResult = audio.play();
    if (playResult) {
      void playResult.catch(() => {
        releasePlayback(playbackGroup, audio);
        setIsPlaying(false);
        setPlaybackError("Playback unavailable.");
      });
    }
  }

  function handleSeek(value: string) {
    const audio = audioRef.current;
    if (!audio || controlsDisabled) return;

    const nextSeconds = Math.max(0, Math.min(Number(value) || 0, totalSeconds || Number(value) || 0));
    audio.currentTime = nextSeconds;
    setElapsedSeconds(nextSeconds);
  }

  function handleMute() {
    const audio = audioRef.current;
    if (!audio || controlsDisabled) return;

    const nextMuted = !audio.muted;
    audio.muted = nextMuted;
    setIsMuted(nextMuted);
  }

  const playLabel = `${isPlaying ? "Pause" : "Play"} ${label}`;
  const muteLabel = `${isMuted ? "Unmute" : "Mute"} ${label}`;

  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events -- The player contains native controls and must prevent their interactions from bubbling to its canvas card.
    <section
      className={`v2-audio-player nodrag nopan${compact ? " is-compact" : ""}${controlsDisabled ? " is-unavailable" : ""}`}
      aria-label={`${label} audio player`}
      onPointerDown={stopCanvasPropagation}
      onClick={stopCanvasPropagation}
    >
      <audio ref={audioRef} src={src ?? undefined} preload="metadata" />
      <div className="v2-audio-player-controls">
        <button className="v2-audio-player-icon" type="button" aria-label={playLabel} title={playLabel} onClick={handleTogglePlayback} disabled={controlsDisabled}>
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>
        <div className="v2-audio-player-seek-wrap">
          <input
            className="v2-audio-player-seek"
            type="range"
            min="0"
            max={totalSeconds}
            step="0.01"
            value={seekSeconds}
            aria-label={`Seek ${label}`}
            aria-valuetext={`${formatTime(seekSeconds)} of ${formatTime(totalSeconds)}`}
            onChange={(event) => handleSeek(event.currentTarget.value)}
            disabled={controlsDisabled}
          />
          <output className="v2-audio-player-time">{formatTime(seekSeconds)} / {formatTime(totalSeconds)}</output>
        </div>
        <button className="v2-audio-player-icon" type="button" aria-label={muteLabel} title={muteLabel} onClick={handleMute} disabled={controlsDisabled}>
          {isMuted ? <MuteIcon /> : <UnmuteIcon />}
        </button>
      </div>
      {!hasSource ? <span className="v2-audio-player-status">Audio unavailable.</span> : null}
      {mediaUnavailable ? <span className="v2-audio-player-status" role="alert">Audio unavailable.</span> : null}
      {playbackError ? <span className="v2-audio-player-status" role="alert">{playbackError}</span> : null}
    </section>
  );
}
