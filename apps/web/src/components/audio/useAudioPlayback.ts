import { useEffect, useRef, useState } from "react";

const activeAudioByGroup = new Map<string, HTMLAudioElement>();

function claimPlayback(group: string, audio: HTMLAudioElement) {
  const active = activeAudioByGroup.get(group);
  if (active && active !== audio) active.pause();
  activeAudioByGroup.set(group, audio);
}

function releasePlayback(group: string, audio: HTMLAudioElement) {
  if (activeAudioByGroup.get(group) === audio) activeAudioByGroup.delete(group);
}

export function boundedAudioSeconds(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

export function formatAudioTime(seconds: number) {
  const wholeSeconds = Math.floor(Math.max(0, seconds));
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

export function useAudioPlayback({
  src,
  durationSeconds,
  playbackGroup,
}: {
  src: string | null;
  durationSeconds?: number | null;
  playbackGroup: string;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const durationSecondsRef = useRef(durationSeconds);
  const previousPlaybackGroupRef = useRef(playbackGroup);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [knownDuration, setKnownDuration] = useState(() => boundedAudioSeconds(durationSeconds));
  const [hasDuration, setHasDuration] = useState(() => boundedAudioSeconds(durationSeconds) > 0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [mediaUnavailable, setMediaUnavailable] = useState(false);
  const [playbackError, setPlaybackError] = useState<string | null>(null);

  const hasSource = Boolean(src);
  const isLoading = hasSource && !hasDuration && !mediaUnavailable;
  const controlsDisabled = !hasSource || isLoading || mediaUnavailable;
  const totalSeconds = knownDuration || boundedAudioSeconds(durationSeconds);
  const seekSeconds = totalSeconds > 0 ? Math.min(elapsedSeconds, totalSeconds) : elapsedSeconds;

  durationSecondsRef.current = durationSeconds;

  useEffect(() => {
    const audio = audioRef.current;
    const sourceDuration = boundedAudioSeconds(durationSecondsRef.current);
    if (audio) releasePlayback(previousPlaybackGroupRef.current, audio);
    setElapsedSeconds(0);
    setKnownDuration(sourceDuration);
    setHasDuration(sourceDuration > 0);
    setIsPlaying(false);
    setMediaUnavailable(false);
    setPlaybackError(null);
  }, [src]);

  useEffect(() => {
    const propDuration = boundedAudioSeconds(durationSeconds);
    if (propDuration > 0) {
      setKnownDuration(propDuration);
      setHasDuration(true);
      return;
    }

    const mediaDuration = boundedAudioSeconds(audioRef.current?.duration);
    if (mediaDuration > 0) {
      setKnownDuration(mediaDuration);
      setHasDuration(true);
    }
  }, [durationSeconds]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;

    const syncDuration = () => {
      const nextDuration = boundedAudioSeconds(audio.duration)
        || boundedAudioSeconds(durationSecondsRef.current);
      setKnownDuration(nextDuration);
      setHasDuration(nextDuration > 0);
    };
    const syncElapsed = () => setElapsedSeconds(boundedAudioSeconds(audio.currentTime));
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
  }, [playbackGroup]);

  useEffect(() => {
    const audio = audioRef.current;
    const previousGroup = previousPlaybackGroupRef.current;
    if (!audio || previousGroup === playbackGroup) return;

    releasePlayback(previousGroup, audio);
    previousPlaybackGroupRef.current = playbackGroup;
    if (isPlaying) claimPlayback(playbackGroup, audio);
  }, [isPlaying, playbackGroup]);

  function togglePlayback() {
    const audio = audioRef.current;
    if (!audio || controlsDisabled) return;
    if (isPlaying) {
      audio.pause();
      return;
    }

    claimPlayback(playbackGroup, audio);
    const result = audio.play();
    if (result) {
      void result.catch(() => {
        releasePlayback(playbackGroup, audio);
        setIsPlaying(false);
        setPlaybackError("Playback unavailable.");
      });
    }
  }

  function seekTo(nextSeconds: number) {
    const audio = audioRef.current;
    if (!audio || controlsDisabled) return;
    const bounded = Math.max(0, Math.min(nextSeconds || 0, totalSeconds || nextSeconds || 0));
    audio.currentTime = bounded;
    setElapsedSeconds(bounded);
  }

  function skipBy(deltaSeconds: number) {
    seekTo((audioRef.current?.currentTime ?? seekSeconds) + deltaSeconds);
  }

  function toggleMute() {
    const audio = audioRef.current;
    if (!audio || controlsDisabled) return;
    const nextMuted = !audio.muted;
    audio.muted = nextMuted;
    setIsMuted(nextMuted);
  }

  return {
    audioRef,
    controlsDisabled,
    elapsedSeconds: seekSeconds,
    hasSource,
    isLoading,
    isMuted,
    isPlaying,
    mediaUnavailable,
    playbackError,
    seekTo,
    skipBy,
    toggleMute,
    togglePlayback,
    totalSeconds,
  };
}
