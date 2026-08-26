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
    <div className="agent-editing-timeline__audio-controls" role="region" aria-label="Audio track controls">
      <label>
        <input
          type="checkbox"
          aria-label="Enabled"
          checked={enabled}
          disabled={disabled}
          onChange={(event) => onSetBgm({ enabled: event.currentTarget.checked })}
        />
        <span>Enabled</span>
      </label>
      <label>
        <span>Volume</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          aria-label="BGM volume"
          value={volume}
          disabled={disabled}
          onChange={(event) => onSetBgmVolume(Number(event.currentTarget.value))}
        />
      </label>
    </div>
  );
}
