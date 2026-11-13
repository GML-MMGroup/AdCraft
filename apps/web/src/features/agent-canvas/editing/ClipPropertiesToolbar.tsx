import type { ReactNode } from "react";
import { useEditingText } from "./editingMessages.ts";
import { ChevronDownIcon, ChevronUpIcon } from "../../../icons.tsx";
import type { EditingVideoEntryV2 } from "../../../types-v2.ts";
import type { EditingBoundInput } from "./editingModel.ts";

interface ClipPropertiesToolbarProps {
  children?: ReactNode;
  compact?: boolean;
  disabled: boolean;
  index: number;
  input: EditingBoundInput<EditingVideoEntryV2>;
  onMove: (offset: -1 | 1) => void;
  onUpdate: (patch: Partial<EditingVideoEntryV2>) => void;
  total: number;
}

function numberValue(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function ClipPropertiesToolbar({
  children,
  compact = false,
  disabled,
  index,
  input,
  onMove,
  onUpdate,
  total,
}: ClipPropertiesToolbarProps) {
  const t = useEditingText();
  const label = input.node?.title || input.asset?.display_name || `Shot ${index + 1}`;

  return (
    <div className="agent-editing-clip-properties" role="toolbar" aria-label="Clip properties">
      <div className="agent-editing-clip-properties__identity">
        <span>{t("Selected clip")}</span>
        <strong className="agent-editing-clip-properties__name" title={label}>{label}</strong>
      </div>
      {children}
      <label className="agent-editing-clip-properties__volume">
        <span>{t("Volume")}</span>
        <input type="range" min="0" max="1" step="0.05" aria-label={t("Volume")} value={input.entry.volume} disabled={disabled} onChange={(event) => onUpdate({ volume: Number(event.currentTarget.value) })} />
      </label>
      <label className="agent-editing-track__toggle">
        <input type="checkbox" checked={input.entry.preserve_native_audio} disabled={disabled} onChange={(event) => onUpdate({ preserve_native_audio: event.currentTarget.checked })} />
        <span>{t("Source audio")}</span>
      </label>
      <details className="editing-properties-advanced" open={compact ? undefined : true}>
        <summary>{t("Advanced")}</summary>
      <div className="agent-editing-track__order">
        <button type="button" aria-label={`Move ${label} earlier`} title="Move earlier" disabled={disabled || index === 0} onClick={() => onMove(-1)}>
          <ChevronUpIcon />
        </button>
        <button type="button" aria-label={`Move ${label} later`} title="Move later" disabled={disabled || index === total - 1} onClick={() => onMove(1)}>
          <ChevronDownIcon />
        </button>
      </div>
      <label className="agent-editing-track__toggle">
        <input type="checkbox" checked={input.entry.enabled} disabled={disabled} onChange={(event) => onUpdate({ enabled: event.currentTarget.checked })} />
        <span>{t("Enabled")}</span>
      </label>

      <label>
        <span>{t("Transition")}</span>
        <select value={input.entry.transition} disabled={disabled} onChange={(event) => {
          const transition = event.currentTarget.value as "cut" | "fade";
          onUpdate({ transition, ...(transition === "cut" ? { transition_duration_seconds: 0 } : {}) });
        }}>
          <option value="cut">{t("Cut")}</option>
          <option value="fade">{t("Fade")}</option>
        </select>
      </label>
      <label>
        <span>{t("Transition duration")}</span>
        <input
          type="number"
          min="0"
          max="5"
          step="0.1"
          value={input.entry.transition_duration_seconds}
          disabled={disabled || input.entry.transition === "cut"}
          onChange={(event) => onUpdate({ transition_duration_seconds: Math.min(5, Math.max(0, numberValue(event.currentTarget.value))) })}
        />
      </label>
      <label>
        <span>{t("Fit")}</span>
        <select value={input.entry.fit_mode} disabled={disabled} onChange={(event) => onUpdate({ fit_mode: event.currentTarget.value as "fit" | "fill" })}>
          <option value="fill">{t("Fill")}</option>
          <option value="fit">{t("Fit")}</option>
        </select>
      </label>
      </details>
    </div>
  );
}
