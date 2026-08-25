import type { ReactNode } from "react";

import {
  ChevronDownIcon,
  ChevronUpIcon,
  FastForwardIcon,
  MuteIcon,
  UnmuteIcon,
  VideoIcon,
} from "../../../icons.tsx";
import type {
  CanvasNodeStatusV2,
  EditingBgmEntryV2,
  EditingVideoEntryV2,
} from "../../../types-v2.ts";
import type { EditingBoundInput, EditingInputs } from "./editingModel.ts";

interface EditingTimelineProps {
  inputs: EditingInputs;
  timelineDuration: number;
  playheadSeconds: number;
  selectedReferenceId: string | null;
  exportRunning: boolean;
  onPlayheadChange: (seconds: number) => void;
  onSelectReference: (referenceId: string) => void;
  onMoveVideo: (referenceId: string, offset: -1 | 1) => void;
  onUpdateVideo: (referenceId: string, patch: Partial<EditingVideoEntryV2>) => void;
  onSetBgm: (patch: Partial<EditingBgmEntryV2>) => void;
  onSetBgmVolume: (volume: number) => void;
}

function seconds(value: number | null | undefined): string {
  if (!value || value < 0) return "--";
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function numericValue(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clipDuration(input: EditingBoundInput<EditingVideoEntryV2>): number {
  const sourceDuration = input.asset?.duration_seconds ?? 1;
  const start = Math.max(0, input.entry.trim_start_seconds);
  const end = input.entry.trim_end_seconds ?? sourceDuration;
  return Math.max(0.5, end > start ? end - start : sourceDuration);
}

function statusOf(input: EditingBoundInput<EditingVideoEntryV2>): CanvasNodeStatusV2 | "unavailable" {
  return input.node?.status ?? input.asset?.status ?? "unavailable";
}

function waveformHeight(index: number): number {
  return 18 + Math.round(Math.abs(Math.sin(index * 1.47)) * 56 + Math.abs(Math.sin(index * 0.31)) * 20);
}

function TimelineRuler({ duration }: { duration: number }) {
  const ticks = Array.from({ length: 9 }, (_, index) => index / 8);
  return (
    <div className="agent-editing-timeline__ruler" aria-hidden="true">
      {ticks.map((position) => (
        <span key={position} style={{ left: `${position * 100}%` }}>
          {seconds(duration * position)}
        </span>
      ))}
    </div>
  );
}

function VideoClip({
  input,
  index,
  left,
  width,
  selected,
  onSelect,
}: {
  input: EditingBoundInput<EditingVideoEntryV2>;
  index: number;
  left: number;
  width: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const label = input.node?.title || input.asset?.display_name || `Shot ${index + 1}`;
  const status = statusOf(input);
  return (
    <button
      type="button"
      className={`agent-editing-timeline__clip agent-editing-timeline__clip--${status}${selected ? " is-selected" : ""}`}
      aria-label={`Select ${label}`}
      aria-pressed={selected}
      style={{ left: `${left}%`, width: `${Math.max(7, width)}%` }}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
    >
      {input.asset?.preview_url ? <img src={input.asset.preview_url} alt="" /> : <VideoIcon aria-hidden="true" />}
      <span className="agent-editing-timeline__clip-scrim" />
      <span className="agent-editing-timeline__clip-copy">
        <strong>{String(index + 1).padStart(2, "0")}</strong>
        <small>{seconds(clipDuration(input))}</small>
      </span>
    </button>
  );
}

function TrackLabel({ children, count, icon }: { children: string; count?: number; icon: ReactNode }) {
  return (
    <div className="agent-editing-timeline__track-label">
      <span className="agent-editing-timeline__track-icon">{icon}</span>
      <strong>{children}</strong>
      {count === undefined ? null : <small>{count}</small>}
    </div>
  );
}

function VideoInspector({
  input,
  index,
  total,
  disabled,
  onMove,
  onUpdate,
}: {
  input: EditingBoundInput<EditingVideoEntryV2>;
  index: number;
  total: number;
  disabled: boolean;
  onMove: (offset: -1 | 1) => void;
  onUpdate: (patch: Partial<EditingVideoEntryV2>) => void;
}) {
  const label = input.node?.title || input.asset?.display_name || `Shot ${index + 1}`;
  return (
    <section className="agent-editing-timeline__inspector" aria-label="Selected clip">
      <div className="agent-editing-timeline__inspector-heading">
        <div>
          <span>Selected clip</span>
          <strong>{label}</strong>
        </div>
        <div className="agent-editing-track__order">
          <button type="button" aria-label={`Move ${label} earlier`} title="Move earlier" disabled={disabled || index === 0} onClick={() => onMove(-1)}>
            <ChevronUpIcon />
          </button>
          <button type="button" aria-label={`Move ${label} later`} title="Move later" disabled={disabled || index === total - 1} onClick={() => onMove(1)}>
            <ChevronDownIcon />
          </button>
        </div>
      </div>
      <div className="agent-editing-timeline__inspector-grid">
        <label className="agent-editing-track__toggle">
          <input type="checkbox" checked={input.entry.enabled} disabled={disabled} onChange={(event) => onUpdate({ enabled: event.currentTarget.checked })} />
          <span>Enabled</span>
        </label>
        <label>
          <span>Trim start</span>
          <input type="number" min="0" step="0.1" value={input.entry.trim_start_seconds} disabled={disabled} onChange={(event) => onUpdate({ trim_start_seconds: Math.max(0, numericValue(event.currentTarget.value) ?? 0) })} />
        </label>
        <label>
          <span>Trim end</span>
          <input type="number" min="0.01" step="0.1" value={input.entry.trim_end_seconds ?? ""} placeholder="Source" disabled={disabled} onChange={(event) => onUpdate({ trim_end_seconds: numericValue(event.currentTarget.value) })} />
        </label>
        <label>
          <span>Volume</span>
          <input type="range" min="0" max="1" step="0.05" aria-label="Volume" value={input.entry.volume} disabled={disabled} onChange={(event) => onUpdate({ volume: Number(event.currentTarget.value) })} />
        </label>
        <label className="agent-editing-track__toggle">
          <input type="checkbox" checked={input.entry.preserve_native_audio} disabled={disabled} onChange={(event) => onUpdate({ preserve_native_audio: event.currentTarget.checked })} />
          <span>Source audio</span>
        </label>
        <label>
          <span>Transition</span>
          <select value={input.entry.transition} disabled={disabled} onChange={(event) => {
            const transition = event.currentTarget.value as "cut" | "fade";
            onUpdate({ transition, ...(transition === "cut" ? { transition_duration_seconds: 0 } : {}) });
          }}>
            <option value="cut">Cut</option>
            <option value="fade">Fade</option>
          </select>
        </label>
        <label>
          <span>Transition duration</span>
          <input type="number" min="0" max="5" step="0.1" value={input.entry.transition_duration_seconds} disabled={disabled || input.entry.transition === "cut"} onChange={(event) => onUpdate({ transition_duration_seconds: Math.min(5, Math.max(0, numericValue(event.currentTarget.value) ?? 0)) })} />
        </label>
        <label>
          <span>Fit</span>
          <select value={input.entry.fit_mode} disabled={disabled} onChange={(event) => onUpdate({ fit_mode: event.currentTarget.value as "fit" | "fill" })}>
            <option value="fill">Fill</option>
            <option value="fit">Fit</option>
          </select>
        </label>
      </div>
    </section>
  );
}

function BgmInspector({
  input,
  disabled,
  onSetBgm,
  onSetBgmVolume,
}: {
  input: EditingBoundInput<EditingBgmEntryV2>;
  disabled: boolean;
  onSetBgm: (patch: Partial<EditingBgmEntryV2>) => void;
  onSetBgmVolume: (volume: number) => void;
}) {
  return (
    <section className="agent-editing-timeline__inspector" aria-label="Selected audio">
      <div className="agent-editing-timeline__inspector-heading">
        <div>
          <span>Selected audio</span>
          <strong>{input.node?.title || input.asset?.display_name || "Campaign BGM"}</strong>
        </div>
        <MuteIcon />
      </div>
      <div className="agent-editing-timeline__inspector-grid agent-editing-timeline__inspector-grid--audio">
        <label className="agent-editing-track__toggle">
          <input type="checkbox" checked={input.entry.enabled} disabled={disabled} onChange={(event) => onSetBgm({ enabled: event.currentTarget.checked })} />
          <span>Enabled</span>
        </label>
        <label>
          <span>Trim start</span>
          <input type="number" min="0" step="0.1" value={input.entry.trim_start_seconds} disabled={disabled} onChange={(event) => onSetBgm({ trim_start_seconds: Math.max(0, numericValue(event.currentTarget.value) ?? 0) })} />
        </label>
        <label>
          <span>Trim end</span>
          <input type="number" min="0.01" step="0.1" value={input.entry.trim_end_seconds ?? ""} placeholder="Source" disabled={disabled} onChange={(event) => onSetBgm({ trim_end_seconds: numericValue(event.currentTarget.value) })} />
        </label>
        <label className="agent-editing-track__volume">
          <span>Volume {Math.round(input.entry.volume * 100)}%</span>
          <input type="range" min="0" max="1" step="0.05" aria-label="BGM volume" value={input.entry.volume} disabled={disabled} onChange={(event) => onSetBgmVolume(Number(event.currentTarget.value))} />
        </label>
        <label>
          <span>Fade in</span>
          <input type="number" min="0" max="30" step="0.1" value={input.entry.fade_in_seconds} disabled={disabled} onChange={(event) => onSetBgm({ fade_in_seconds: Math.min(30, Math.max(0, numericValue(event.currentTarget.value) ?? 0)) })} />
        </label>
        <label>
          <span>Fade out</span>
          <input type="number" min="0" max="30" step="0.1" value={input.entry.fade_out_seconds} disabled={disabled} onChange={(event) => onSetBgm({ fade_out_seconds: Math.min(30, Math.max(0, numericValue(event.currentTarget.value) ?? 0)) })} />
        </label>
      </div>
    </section>
  );
}

export function EditingTimeline({
  inputs,
  timelineDuration,
  playheadSeconds,
  selectedReferenceId,
  exportRunning,
  onPlayheadChange,
  onSelectReference,
  onMoveVideo,
  onUpdateVideo,
  onSetBgm,
  onSetBgmVolume,
}: EditingTimelineProps) {
  const selectedVideoIndex = inputs.videos.findIndex((input) => input.referenceId === selectedReferenceId);
  const selectedVideo = selectedVideoIndex >= 0 ? inputs.videos[selectedVideoIndex] : null;
  const selectedBgm = inputs.bgm?.referenceId === selectedReferenceId ? inputs.bgm : null;
  let elapsed = 0;

  return (
    <div className="agent-editing-timeline">
      <TimelineRuler duration={timelineDuration} />
      <div className="agent-editing-timeline__lanes">
        <div
          className="agent-editing-timeline__playhead"
          style={{ left: `calc(124px + (100% - 124px) * ${(playheadSeconds / timelineDuration).toFixed(4)})` }}
          aria-hidden="true"
        />
        <section className="agent-editing-timeline__track" aria-label="Video track" role="group">
          <TrackLabel icon={<VideoIcon />} count={inputs.videos.length}>Video Track</TrackLabel>
          <div
            className="agent-editing-timeline__lane"
            role="slider"
            tabIndex={0}
            aria-label="Seek video track"
            aria-valuemin={0}
            aria-valuemax={timelineDuration}
            aria-valuenow={playheadSeconds}
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              onPlayheadChange(Math.max(0, Math.min(timelineDuration, ((event.clientX - rect.left) / rect.width) * timelineDuration)));
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") onPlayheadChange(Math.max(0, playheadSeconds - 1));
              if (event.key === "ArrowRight") onPlayheadChange(Math.min(timelineDuration, playheadSeconds + 1));
            }}
          >
            {inputs.videos.length === 0 ? <span className="agent-editing-timeline__empty">Connect ready Video nodes to build the sequence.</span> : inputs.videos.map((input, index) => {
              const duration = clipDuration(input);
              const left = (elapsed / timelineDuration) * 100;
              const width = (duration / timelineDuration) * 100;
              elapsed += duration;
              return <VideoClip key={input.referenceId} input={input} index={index} left={left} width={width} selected={input.referenceId === selectedReferenceId} onSelect={() => onSelectReference(input.referenceId)} />;
            })}
          </div>
        </section>
        <section className="agent-editing-timeline__track" aria-label="Audio track" role="group">
          <TrackLabel icon={inputs.bgm ? <UnmuteIcon /> : <MuteIcon />}>Audio Track</TrackLabel>
          <div
            className="agent-editing-timeline__lane agent-editing-timeline__lane--audio"
            role="slider"
            tabIndex={0}
            aria-label="Seek audio track"
            aria-valuemin={0}
            aria-valuemax={timelineDuration}
            aria-valuenow={playheadSeconds}
            onClick={(event) => {
              if (inputs.bgm) onSelectReference(inputs.bgm.referenceId);
              const rect = event.currentTarget.getBoundingClientRect();
              onPlayheadChange(Math.max(0, Math.min(timelineDuration, ((event.clientX - rect.left) / rect.width) * timelineDuration)));
            }}
            onKeyDown={(event) => {
              if (inputs.bgm && (event.key === "Enter" || event.key === " ")) onSelectReference(inputs.bgm.referenceId);
              if (event.key === "ArrowLeft") onPlayheadChange(Math.max(0, playheadSeconds - 1));
              if (event.key === "ArrowRight") onPlayheadChange(Math.min(timelineDuration, playheadSeconds + 1));
            }}
          >
            {inputs.bgm ? (
              <button type="button" className={`agent-editing-timeline__audio-clip${selectedBgm ? " is-selected" : ""}`} aria-label="Select BGM" aria-pressed={Boolean(selectedBgm)}>
                <span>{inputs.bgm.node?.title || inputs.bgm.asset?.display_name || "Campaign BGM"}</span>
                <span className="agent-editing-timeline__waveform" aria-hidden="true">
                  {Array.from({ length: 96 }, (_, index) => <i key={index} style={{ height: `${waveformHeight(index)}%` }} />)}
                </span>
              </button>
            ) : <span className="agent-editing-timeline__empty">Optional BGM input</span>}
          </div>
        </section>
      </div>
      <input
        className="agent-editing-timeline__scrubber"
        type="range"
        min="0"
        max={timelineDuration}
        step="0.01"
        value={Math.min(timelineDuration, Math.max(0, playheadSeconds))}
        aria-label="Timeline playhead"
        onChange={(event) => onPlayheadChange(Number(event.currentTarget.value))}
      />
      {selectedVideo ? (
        <>
          <VideoInspector input={selectedVideo} index={selectedVideoIndex} total={inputs.videos.length} disabled={exportRunning} onMove={(offset) => onMoveVideo(selectedVideo.referenceId, offset)} onUpdate={(patch) => onUpdateVideo(selectedVideo.referenceId, patch)} />
          {inputs.bgm ? <BgmInspector input={inputs.bgm} disabled={exportRunning} onSetBgm={onSetBgm} onSetBgmVolume={onSetBgmVolume} /> : null}
        </>
      ) : selectedBgm ? (
        <BgmInspector input={selectedBgm} disabled={exportRunning} onSetBgm={onSetBgm} onSetBgmVolume={onSetBgmVolume} />
      ) : (
        <div className="agent-editing-timeline__no-selection">Select a clip or audio track to edit its settings.</div>
      )}
    </div>
  );
}
