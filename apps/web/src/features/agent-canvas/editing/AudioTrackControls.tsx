import type { CSSProperties } from "react";
import type { EditingBgmEntryV2 } from "../../../types-v2.ts";

export interface AudioTrackControlsProps {
  disabled: boolean;
  enabled: boolean;
  onSetBgm: (patch: Partial<EditingBgmEntryV2>) => void;
  onSetBgmVolume: (volume: number) => void;
  volume: number;
}

export function AudioTrackControls({
  disabled,
  enabled,
  onSetBgm,
  onSetBgmVolume,
  volume,
}: AudioTrackControlsProps) {
  return (
    <div className="agent-editing-timeline__audio-controls agent-editing-timeline__audio-controls--under-label" role="region" aria-label="Audio track controls">
      <label className="agent-editing-timeline__audio-enabled">
        <input
          type="checkbox"
          aria-label="Enabled"
          checked={enabled}
          disabled={disabled}
          onChange={(event) => onSetBgm({ enabled: event.currentTarget.checked })}
        />
        <span>Enabled</span>
      </label>
      <label className="agent-editing-timeline__audio-volume">
        <span>Volume</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          aria-label="BGM volume"
          value={volume}
          disabled={disabled}
          style={{ "--audio-volume": `${volume * 100}%` } as CSSProperties}
          onChange={(event) => onSetBgmVolume(Number(event.currentTarget.value))}
        />
      </label>
    </div>
  );
}
