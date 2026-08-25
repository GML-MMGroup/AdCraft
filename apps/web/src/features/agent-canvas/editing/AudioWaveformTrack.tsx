import { useRef } from "react";

import { MuteIcon, UnmuteIcon } from "../../../icons.tsx";
import type { EditingBgmEntryV2 } from "../../../types-v2.ts";
import { trimAudioPeaks, useAudioWaveform } from "./useAudioWaveform.ts";

export interface AudioWaveformTrackProps {
  audioUrl: string | null;
  durationSeconds: number;
  enabled: boolean;
  name: string;
  onSetBgm: (patch: Partial<EditingBgmEntryV2>) => void;
  onSetBgmVolume: (volume: number) => void;
  renderedWidth: number;
  trimEndSeconds: number | null;
  trimStartSeconds: number;
  volume: number;
  disabled?: boolean;
  fadeInSeconds?: number;
  fadeOutSeconds?: number;
  playheadSeconds?: number;
}

function numberValue(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

export function AudioWaveformTrack({
  audioUrl,
  disabled = false,
  durationSeconds,
  enabled,
  fadeInSeconds = 0,
  fadeOutSeconds = 0,
  name,
  onSetBgm,
  onSetBgmVolume,
  playheadSeconds = 0,
  renderedWidth,
  trimEndSeconds,
  trimStartSeconds,
  volume,
}: AudioWaveformTrackProps) {
  const waveform = useAudioWaveform({ audioUrl, renderedWidth });
  const lastAudibleVolume = useRef(volume > 0 ? volume : 1);
  if (volume > 0) lastAudibleVolume.current = volume;

  const muted = volume <= 0;
  const playableDuration = Math.max(0, (trimEndSeconds ?? durationSeconds) - trimStartSeconds);
  const playedRatio = playableDuration === 0 ? 0 : clamp(playheadSeconds / playableDuration, 0, 1);
  const visiblePeaks = trimAudioPeaks(
    waveform.peaks,
    durationSeconds,
    trimStartSeconds,
    trimEndSeconds,
    renderedWidth,
  );

  return (
    <section className="audio-waveform-track" aria-label="BGM track">
      <div className="audio-waveform-track__header">
        <strong title={name}>{name}</strong>
        <button
          type="button"
          className="audio-waveform-track__mute"
          aria-label={muted ? "Unmute BGM" : "Mute BGM"}
          title={muted ? "Unmute BGM" : "Mute BGM"}
          disabled={disabled}
          onClick={() => onSetBgmVolume(muted ? lastAudibleVolume.current : 0)}
        >
          {muted ? <MuteIcon aria-hidden="true" /> : <UnmuteIcon aria-hidden="true" />}
        </button>
      </div>
      <div className="audio-waveform-track__lane" role="img" aria-label={`Audio waveform, ${waveform.status}`}>
        {visiblePeaks.map((peak, index) => (
          <i
            key={index}
            aria-hidden="true"
            className={index / Math.max(1, visiblePeaks.length) < playedRatio
              ? "audio-waveform-track__bar audio-waveform-track__bar--played"
              : "audio-waveform-track__bar"}
            style={{ height: `${Math.max(8, Math.round(peak * 100))}%` }}
          />
        ))}
      </div>
      <div className="audio-waveform-track__controls">
        <label>
          <input type="checkbox" checked={enabled} disabled={disabled} onChange={(event) => onSetBgm({ enabled: event.currentTarget.checked })} />
          <span>Enabled</span>
        </label>
        <label>
          <span>Volume</span>
          <input type="range" min="0" max="1" step="0.05" aria-label="BGM volume" value={volume} disabled={disabled} onChange={(event) => onSetBgmVolume(Number(event.currentTarget.value))} />
        </label>
        <label>
          <span>Trim start</span>
          <input type="number" min="0" step="0.1" value={trimStartSeconds} disabled={disabled} onChange={(event) => onSetBgm({ trim_start_seconds: Math.max(0, numberValue(event.currentTarget.value) ?? 0) })} />
        </label>
        <label>
          <span>Trim end</span>
          <input type="number" min="0.01" step="0.1" value={trimEndSeconds ?? ""} placeholder="Source" disabled={disabled} onChange={(event) => onSetBgm({ trim_end_seconds: numberValue(event.currentTarget.value) })} />
        </label>
        <label>
          <span>Fade in</span>
          <input type="number" min="0" max="30" step="0.1" value={fadeInSeconds} disabled={disabled} onChange={(event) => onSetBgm({ fade_in_seconds: clamp(numberValue(event.currentTarget.value) ?? 0, 0, 30) })} />
        </label>
        <label>
          <span>Fade out</span>
          <input type="number" min="0" max="30" step="0.1" value={fadeOutSeconds} disabled={disabled} onChange={(event) => onSetBgm({ fade_out_seconds: clamp(numberValue(event.currentTarget.value) ?? 0, 0, 30) })} />
        </label>
      </div>
    </section>
  );
}
