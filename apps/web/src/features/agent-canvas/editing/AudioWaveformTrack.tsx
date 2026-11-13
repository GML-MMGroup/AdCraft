import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

import { useEditingText } from "./editingMessages.ts";
import type { EditingBgmEntryV2 } from "../../../types-v2.ts";
import {
  bgmPlayedRatioForTimeline,
  clampTrimRange,
  MIN_EDITED_CLIP_SECONDS,
} from "./editingTimelineMath.ts";
import { normalizePeakCount, trimAudioPeaks, useAudioWaveform } from "./useAudioWaveform.ts";

export interface AudioWaveformTrackProps {
  audioUrl: string | null;
  durationSeconds: number;
  name: string;
  displayName?: string;
  enabled?: boolean;
  selected?: boolean;
  onSelect?: () => void;
  onSetBgm: (patch: Partial<EditingBgmEntryV2>) => void;
  renderedWidth: number;
  trimEndSeconds: number | null;
  trimStartSeconds: number;
  disabled?: boolean;
  playheadSeconds?: number;
  timelineDuration?: number;
}

interface TrimRange {
  start: number;
  end: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function roundTrim(value: number): number {
  return Math.round(value * 1_000) / 1_000;
}

function initialTrimRange(durationSeconds: number, start: number, end: number | null): TrimRange {
  const duration = Math.max(0, Number.isFinite(durationSeconds) ? durationSeconds : 0);
  const normalized = clampTrimRange({
    sourceDuration: duration,
    start,
    end: end ?? duration,
    edge: "end",
  });
  return { start: roundTrim(normalized.start), end: roundTrim(normalized.end) };
}

export function AudioWaveformTrack({
  audioUrl,
  disabled = false,
  durationSeconds,
  name,
  displayName,
  enabled = true,
  selected = false,
  onSelect,
  onSetBgm,
  playheadSeconds = 0,
  renderedWidth,
  timelineDuration,
  trimEndSeconds,
  trimStartSeconds,
}: AudioWaveformTrackProps) {
  const t = useEditingText();
  const barCount = Math.max(1, Math.min(1024, Math.round(renderedWidth / 6)));
  const waveform = useAudioWaveform({ audioUrl, renderedWidth: barCount });
  const laneRef = useRef<HTMLDivElement>(null);
  const dragCancelRef = useRef<(() => void) | null>(null);
  const duration = Math.max(0, Number.isFinite(durationSeconds) ? durationSeconds : 0);
  const [trimRange, setTrimRange] = useState<TrimRange>(() => initialTrimRange(duration, trimStartSeconds, trimEndSeconds));

  useEffect(() => {
    setTrimRange(initialTrimRange(duration, trimStartSeconds, trimEndSeconds));
  }, [duration, trimEndSeconds, trimStartSeconds]);

  useEffect(() => () => dragCancelRef.current?.(), []);

  const playableDuration = Math.max(0, trimRange.end - trimRange.start);
  const playedRatio = bgmPlayedRatioForTimeline({
    playheadSeconds,
    timelineDuration: timelineDuration ?? 0,
    sourceDuration: duration,
    trimStart: trimRange.start,
    trimEnd: trimRange.end,
  });
  const trimRatio = duration === 0 ? 0 : clamp(playableDuration / duration, 0, 1);
  const trimStartRatio = duration === 0 ? 0 : clamp(trimRange.start / duration, 0, 1);
  const trimEndRatio = duration === 0 ? 0 : clamp(trimRange.end / duration, 0, 1);
  const visiblePeaks = trimAudioPeaks(
    waveform.peaks,
    duration,
    trimRange.start,
    trimRange.end,
    Math.max(1, Math.round(barCount * trimRatio)),
  );
  // Compress only the display's dynamic range so quiet passages remain legible.
  const peakScale = Math.max(.001, ...waveform.peaks);
  const peakHeight = (peak: number) => `${Math.max(8, Math.round(Math.sqrt(peak / peakScale) * 88))}%`;
  const sourcePeaks = normalizePeakCount(waveform.peaks, barCount);

  const persistTrim = (edge: "start" | "end", range: TrimRange) => {
    onSetBgm(edge === "start"
      ? { trim_start_seconds: range.start }
      : { trim_end_seconds: range.end });
  };

  const startDrag = (edge: "start" | "end", event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || !duration || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.currentTarget;
    const pointerId = event.pointerId;
    const initial = { ...trimRange };
    const startClientX = event.clientX;
    let last = initial;
    let changed = false;
    let finished = false;
    target.setPointerCapture?.(pointerId);

    const rangeFromClientX = (clientX: number): TrimRange => {
      const lane = laneRef.current;
      const bounds = lane?.getBoundingClientRect();
      const width = Math.max(1, bounds?.width || renderedWidth);
      const deltaSeconds = (clientX - startClientX) / width * duration;
      const next = clampTrimRange({
        sourceDuration: duration,
        start: edge === "start" ? initial.start + deltaSeconds : initial.start,
        end: edge === "end" ? initial.end + deltaSeconds : initial.end,
        edge,
      });
      return { start: roundTrim(next.start), end: roundTrim(next.end) };
    };
    const stage = (clientX: number) => {
      const next = rangeFromClientX(clientX);
      if (next.start === last.start && next.end === last.end) return;
      last = next;
      changed = next.start !== initial.start || next.end !== initial.end;
      setTrimRange(next);
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      if (target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
      if (dragCancelRef.current === cancel) dragCancelRef.current = null;
    };
    const finish = (commit: boolean) => {
      if (finished) return;
      finished = true;
      cleanup();
      if (commit && changed) persistTrim(edge, last);
      if (!commit) setTrimRange(initial);
    };
    const onPointerMove = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === pointerId && !finished) stage(pointerEvent.clientX);
    };
    const onPointerUp = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== pointerId) return;
      stage(pointerEvent.clientX);
      finish(true);
    };
    const onPointerCancel = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === pointerId) finish(false);
    };
    function cancel() {
      finish(false);
    }

    dragCancelRef.current?.();
    dragCancelRef.current = cancel;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
  };

  const onHandleKeyDown = (edge: "start" | "end", event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    event.stopPropagation();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const delta = direction * (event.shiftKey ? 1 : 0.1);
    const next = clampTrimRange({
      sourceDuration: duration,
      start: edge === "start" ? trimRange.start + delta : trimRange.start,
      end: edge === "end" ? trimRange.end + delta : trimRange.end,
      edge,
    });
    const range = { start: roundTrim(next.start), end: roundTrim(next.end) };
    if (range.start === trimRange.start && range.end === trimRange.end) return;
    setTrimRange(range);
    persistTrim(edge, range);
  };

  const renderHandle = (edge: "start" | "end") => (
    <div
      className={`audio-waveform-track__trim audio-waveform-track__trim--${edge}`}
      role="slider"
      tabIndex={disabled || !duration ? -1 : 0}
      style={{ left: `${(edge === "start" ? trimStartRatio : trimEndRatio) * 100}%` }}
      aria-label={`Trim ${edge} ${name}`}
      aria-valuemin={edge === "start" ? 0 : roundTrim(Math.min(duration, trimRange.start + MIN_EDITED_CLIP_SECONDS))}
      aria-valuemax={edge === "start" ? roundTrim(Math.max(0, trimRange.end - MIN_EDITED_CLIP_SECONDS)) : duration}
      aria-valuenow={edge === "start" ? trimRange.start : trimRange.end}
      aria-disabled={disabled}
      onKeyDown={(event) => onHandleKeyDown(edge, event)}
      onPointerDown={(event) => startDrag(edge, event)}
    >
      <span aria-hidden="true" />
    </div>
  );

  const sourceTime = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, "0")}.${Math.floor(value * 10) % 10}`;
  const header = <>
    <span className="editing-audio-clip-icon" aria-hidden="true"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 8v4m3-7v10m4-13v16m4-13v10m3-7v4"/></svg></span>
    <strong title={displayName || name}>{displayName || name}</strong>
    <span className="editing-audio-clip-kind">{t(!enabled ? "Disabled" : waveform.status === "loading" ? "Loading waveform" : waveform.status === "fallback" ? "Waveform unavailable" : "Background music")}</span>
    <span className="editing-audio-clip-duration">{playableDuration.toFixed(1)}s</span>
  </>;

  return (
    <section className={`audio-waveform-track${selected ? " is-selected" : ""}${!enabled ? " is-muted" : ""}`} aria-label="BGM track">
      {onSelect ? <button type="button" className="editing-audio-clip-header" onClick={onSelect} aria-pressed={selected}>{header}</button> : <div className="editing-audio-clip-header">{header}</div>}

      <div ref={laneRef} className="audio-waveform-track__lane" role="group" aria-label={`Audio waveform, ${waveform.status}`}>
        <div className="audio-waveform-track__source" aria-hidden="true">
          {sourcePeaks.map((peak, index) => (
            <i
              key={`source-${index}`}
              className="audio-waveform-track__bar audio-waveform-track__bar--source"
              style={{ height: peakHeight(peak) }}
            />
          ))}
        </div>
        <div
          className="audio-waveform-track__selection"
          style={{ left: `${trimStartRatio * 100}%`, width: `${trimRatio * 100}%` }}
          aria-hidden="true"
        >
          {visiblePeaks.map((peak, index) => (
            <i
              key={`selected-${index}`}
              className={index / Math.max(1, visiblePeaks.length) < playedRatio
                ? "audio-waveform-track__bar audio-waveform-track__bar--played"
                : "audio-waveform-track__bar"}
              style={{ height: peakHeight(peak) }}
            />
          ))}
        </div>
        {duration ? renderHandle("start") : null}
        {duration ? renderHandle("end") : null}
      </div>
      <div className="editing-audio-clip-footer" aria-hidden="true"><span>{t("Source range")} {sourceTime(trimRange.start)} → {sourceTime(trimRange.end)}</span><span>{t(trimEndSeconds === null ? "Loop" : "Trimmed audio")}</span></div>
    </section>
  );
}
