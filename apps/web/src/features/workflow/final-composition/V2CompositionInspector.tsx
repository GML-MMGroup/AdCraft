/* eslint-disable react-refresh/only-export-components */
import { useEffect, useRef, useState } from "react";
import { TrashIcon } from "../../../icons.tsx";
import type { V2FinalTimelineClip } from "../../../types-v2.ts";

type TimingField = "start" | "in" | "out" | "duration";

type InspectorTimingCommands = {
  moveClip: (
    clipId: string,
    trackIdOrStartTime: string | number,
    startTime?: number,
  ) => unknown;
  trimClip: (clipId: string, edge: "left" | "right", sourceTime: number) => unknown;
  finalizeGesture: () => void;
};

export function commitInspectorTimingEdit(
  clip: Pick<V2FinalTimelineClip, "clip_id" | "track_id" | "clip_type" | "trim_in" | "duration">,
  field: TimingField,
  value: number,
  commands: InspectorTimingCommands,
) {
  const next = Math.max(0, Number.isFinite(value) ? value : 0);
  if (field === "start") {
    if (clip.clip_type === "audio") commands.moveClip(clip.clip_id, clip.track_id, next);
    else commands.moveClip(clip.clip_id, next);
  } else if (field === "in") {
    commands.trimClip(clip.clip_id, "left", next);
  } else if (field === "out") {
    commands.trimClip(clip.clip_id, "right", next);
  } else {
    commands.trimClip(clip.clip_id, "right", clip.trim_in + Math.max(0.01, next));
  }
  commands.finalizeGesture();
}

export function V2CompositionInspector({
  clip,
  onMoveClip,
  onTrimClip,
  onFinalizeGesture,
  onUpdateClip,
  onSetAudio,
  onSetColor,
  onSplitAtPlayhead,
  onRemove,
}: {
  clip: V2FinalTimelineClip | null;
  onMoveClip: InspectorTimingCommands["moveClip"];
  onTrimClip: InspectorTimingCommands["trimClip"];
  onFinalizeGesture: () => void;
  onUpdateClip: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => void;
  onSetAudio: (clipId: string, update: Record<string, number | boolean>) => void;
  onSetColor: (clipId: string, update: Record<string, number | string>) => void;
  onSplitAtPlayhead: (clipId?: string) => unknown;
  onRemove: (clipId: string) => void;
}) {
  const timingCommands: InspectorTimingCommands = {
    moveClip: onMoveClip,
    trimClip: onTrimClip,
    finalizeGesture: onFinalizeGesture,
  };
  const commitTiming = (field: TimingField, value: number) => {
    if (clip) commitInspectorTimingEdit(clip, field, value, timingCommands);
  };

  return (
    <aside className="v2-composition-inspector" aria-label="Clip inspector">
      <div className="v2-composition-panel-heading">
        <strong>Inspector</strong>
        {clip ? <span>{clip.clip_type === "audio" ? "BGM" : "Shot"}</span> : null}
      </div>
      {!clip ? (
        <p className="v2-composition-empty">Select a clip to edit timing, color, audio, and transforms.</p>
      ) : (
        <div className="v2-composition-inspector-fields">
          <fieldset className="v2-composition-fieldset v2-composition-timing-fields">
            <legend>Timing</legend>
            <CanonicalNumericField label="Start" value={clip.start_time} min={0} onCommit={(value) => commitTiming("start", value)} />
            <CanonicalNumericField label="In point" value={clip.trim_in} min={0} onCommit={(value) => commitTiming("in", value)} />
            <CanonicalNumericField label="Out point" value={clip.trim_out ?? clip.trim_in + clip.duration} min={0.01} onCommit={(value) => commitTiming("out", value)} />
            <CanonicalNumericField label="Duration" value={clip.duration} min={0.01} onCommit={(value) => commitTiming("duration", value)} />
          </fieldset>
          {clip.clip_type === "video" ? <ColorFields clip={clip} onSetColor={onSetColor} /> : null}
          <AudioFields clip={clip} onSetAudio={onSetAudio} />
          {clip.clip_type === "video" ? <TransformFields clip={clip} onUpdate={onUpdateClip} /> : null}
          <div className="v2-composition-inspector-actions">
            {clip.clip_type === "video" ? (
              <IconButton label="Split selected clip at playhead" onClick={() => onSplitAtPlayhead(clip.clip_id)}>
                <span aria-hidden="true">B</span>
              </IconButton>
            ) : null}
            <IconButton label="Delete selected clip" onClick={() => onRemove(clip.clip_id)}>
              <TrashIcon />
            </IconButton>
          </div>
        </div>
      )}
    </aside>
  );
}

function ColorFields({
  clip,
  onSetColor,
}: {
  clip: V2FinalTimelineClip;
  onSetColor: (clipId: string, update: Record<string, number | string>) => void;
}) {
  const color = clip.color;
  return (
    <fieldset className="v2-composition-fieldset">
      <legend>Color</legend>
      <select aria-label="Color preset" value={color.preset_id} onChange={(event) => onSetColor(clip.clip_id, { preset_id: event.target.value })}>
        <option value="none">Neutral</option>
        <option value="warm">Warm</option>
        <option value="cool">Cool</option>
        <option value="high_contrast">High contrast</option>
        <option value="muted">Muted</option>
      </select>
      <RangeField label="Brightness" value={color.brightness} min={-1} max={1} step={0.05} onChange={(value) => onSetColor(clip.clip_id, { brightness: value })} />
      <RangeField label="Contrast" value={color.contrast} min={0} max={3} step={0.05} onChange={(value) => onSetColor(clip.clip_id, { contrast: value })} />
      <RangeField label="Saturation" value={color.saturation} min={0} max={3} step={0.05} onChange={(value) => onSetColor(clip.clip_id, { saturation: value })} />
      <RangeField label="Exposure" value={color.exposure} min={-4} max={4} step={0.1} onChange={(value) => onSetColor(clip.clip_id, { exposure: value })} />
      <RangeField label="Temperature" value={color.temperature} min={-100} max={100} step={1} onChange={(value) => onSetColor(clip.clip_id, { temperature: value })} />
      <RangeField label="Tint" value={color.tint} min={-100} max={100} step={1} onChange={(value) => onSetColor(clip.clip_id, { tint: value })} />
      <RangeField label="Hue" value={color.hue} min={-180} max={180} step={1} onChange={(value) => onSetColor(clip.clip_id, { hue: value })} />
    </fieldset>
  );
}

function AudioFields({
  clip,
  onSetAudio,
}: {
  clip: V2FinalTimelineClip;
  onSetAudio: (clipId: string, update: Record<string, number | boolean>) => void;
}) {
  const audio = clip.audio;
  return (
    <fieldset className="v2-composition-fieldset">
      <legend>Audio</legend>
      <RangeField label="Volume" value={audio.volume} min={0} max={4} step={0.05} onChange={(value) => onSetAudio(clip.clip_id, { volume: value })} />
      <label className="v2-composition-checkbox">
        <input type="checkbox" checked={audio.muted} onChange={(event) => onSetAudio(clip.clip_id, { muted: event.target.checked })} /> Mute
      </label>
      <CanonicalNumericField label="Fade in" value={audio.fade_in_seconds} min={0} onCommit={(value) => onSetAudio(clip.clip_id, { fade_in_seconds: value })} />
      <CanonicalNumericField label="Fade out" value={audio.fade_out_seconds} min={0} onCommit={(value) => onSetAudio(clip.clip_id, { fade_out_seconds: value })} />
    </fieldset>
  );
}

function TransformFields({
  clip,
  onUpdate,
}: {
  clip: V2FinalTimelineClip;
  onUpdate: (clipId: string, updater: (clip: V2FinalTimelineClip) => V2FinalTimelineClip) => void;
}) {
  const transform = clip.transform;
  const update = (patch: Partial<typeof transform>) => onUpdate(clip.clip_id, (current) => ({
    ...current,
    transform: { ...current.transform, ...patch },
  }));
  return (
    <fieldset className="v2-composition-fieldset">
      <legend>Transform</legend>
      <RangeField label="Scale" value={transform.scale_x} min={0.1} max={4} step={0.05} onChange={(value) => update({ scale_x: value, scale_y: value })} />
      <RangeField label="X" value={transform.x} min={-1} max={1} step={0.05} onChange={(value) => update({ x: value })} />
      <RangeField label="Y" value={transform.y} min={-1} max={1} step={0.05} onChange={(value) => update({ y: value })} />
      <RangeField label="Rotation" value={transform.rotation_degrees} min={-360} max={360} step={1} onChange={(value) => update({ rotation_degrees: value })} />
      <RangeField label="Opacity" value={transform.opacity} min={0} max={1} step={0.05} onChange={(value) => update({ opacity: value })} />
      <select aria-label="Media fit" value={transform.fit} onChange={(event) => update({ fit: event.target.value === "cover" ? "cover" : "contain" })}>
        <option value="contain">Contain</option>
        <option value="cover">Cover</option>
      </select>
    </fieldset>
  );
}

function CanonicalNumericField({
  label,
  value,
  min,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(formatNumericValue(value));
  const cancelNumericCommitRef = useRef(false);
  useEffect(() => setDraft(formatNumericValue(value)), [value]);
  const commit = () => {
    if (cancelNumericCommitRef.current) {
      cancelNumericCommitRef.current = false;
      setDraft(formatNumericValue(value));
      return;
    }
    const parsed = Number(draft);
    const next = Math.max(min, Number.isFinite(parsed) ? parsed : value);
    setDraft(formatNumericValue(next));
    if (Math.abs(next - value) > 1e-9) onCommit(next);
  };
  return (
    <label className="v2-composition-number-field">
      <span>{label}</span>
      <input
        type="number"
        min={min}
        step="0.01"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            cancelNumericCommitRef.current = true;
            setDraft(formatNumericValue(value));
            event.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}

function RangeField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="v2-composition-range-field">
      <span>{label}<b>{value.toFixed(2)}</b></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button className="v2-composition-icon-button" type="button" aria-label={label} title={label} onClick={onClick}>
      {children}
    </button>
  );
}

function formatNumericValue(value: number) {
  return Number.isFinite(value) ? String(Number(value.toFixed(4))) : "0";
}
