import { useMemo, type ReactNode } from "react";

import { VideoIcon } from "../../../icons.tsx";
import type { EditingBgmEntryV2, EditingVideoEntryV2 } from "../../../types-v2.ts";
import { AudioWaveformTrack } from "./AudioWaveformTrack.tsx";
import { AudioTrackControls } from "./AudioTrackControls.tsx";
import { ClipPropertiesToolbar } from "./ClipPropertiesToolbar.tsx";
import { EditingTimelineViewport } from "./EditingTimelineViewport.tsx";
import { frameStripActiveIndices } from "./editingTimelineVisibility.ts";
import type { EditingInputs } from "./editingModel.ts";
import {
  buildPlayableEditingSequence,
  type PlayableEditingSequence,
} from "./editingPlayableSequence.ts";
import { VideoTimelineClip } from "./VideoTimelineClip.tsx";

export interface EditingTimelineProps {
  inputs: EditingInputs;
  sequence?: PlayableEditingSequence;
  playheadSeconds: number;
  selectedReferenceId: string | null;
  exportRunning: boolean;
  onPlayheadChange: (seconds: number) => void;
  onSelectReference: (referenceId: string) => void;
  onMoveVideo: (referenceId: string, offset: -1 | 1) => void;
  onUpdateVideo: (referenceId: string, patch: Partial<EditingVideoEntryV2>) => void;
  onStageVideo: (referenceId: string, patch: Partial<EditingVideoEntryV2>) => void;
  onCommitStagedManifest: () => void | Promise<unknown>;
  onDiscardStagedManifest: () => void;
  onSetBgm: (patch: Partial<EditingBgmEntryV2>) => void;
  onSetBgmVolume: (volume: number) => void;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function inputLabel(input: EditingInputs["videos"][number], index: number): string {
  return input.node?.title || input.asset?.display_name || `Shot ${index + 1}`;
}

function inactiveStatus(input: EditingInputs["videos"][number]): string {
  if (!input.entry.enabled) return "Disabled";
  if (input.node && input.node.status !== "ready") return `Source ${input.node.status}`;
  if (!input.asset) return "Asset unavailable";
  if (input.asset.status !== "ready") return `Asset ${input.asset.status}`;
  if (!input.asset.media_url) return "Media unavailable";
  return "Inactive";
}

function TrackLabel({
  children,
  count,
  icon,
  onSelect,
  details,
}: {
  children: string;
  count?: number;
  icon: ReactNode;
  onSelect?: () => void;
  details?: ReactNode;
}) {
  return (
    <div className={`agent-editing-timeline__track-label${details ? " agent-editing-timeline__track-label--stacked" : ""}`}>
      {onSelect ? (
        <button type="button" className="agent-editing-timeline__track-label-action" aria-label={`Select ${children}`} onClick={onSelect}>
          <span className="agent-editing-timeline__track-icon">{icon}</span>
          <strong>{children}</strong>
        </button>
      ) : (
        <>
          <span className="agent-editing-timeline__track-icon">{icon}</span>
          <strong>{children}</strong>
        </>
      )}
      {count === undefined ? null : <small>{count}</small>}
      {details}
    </div>
  );
}

export function EditingTimeline({
  exportRunning,
  inputs,
  onCommitStagedManifest,
  onDiscardStagedManifest,
  onMoveVideo,
  onPlayheadChange,
  onSelectReference,
  onSetBgm,
  onSetBgmVolume,
  onStageVideo,
  onUpdateVideo,
  playheadSeconds,
  selectedReferenceId,
  sequence,
}: EditingTimelineProps) {
  const activeSequence = useMemo(
    () => sequence ?? buildPlayableEditingSequence(inputs.videos),
    [inputs.videos, sequence],
  );
  const { segments } = activeSequence;
  const sequenceDuration = activeSequence.duration;
  const selectedVideoIndex = inputs.videos.findIndex((input) => input.referenceId === selectedReferenceId);
  const selectedVideo = selectedVideoIndex >= 0 ? inputs.videos[selectedVideoIndex] : null;
  const selectedBgm = inputs.bgm?.referenceId === selectedReferenceId ? inputs.bgm : null;

  return (
    <div className="agent-editing-timeline">
      <EditingTimelineViewport
        duration={sequenceDuration}
        playheadSeconds={playheadSeconds}
        onPlayheadChange={onPlayheadChange}
      >
        {(viewport) => {
          const activeFrames = frameStripActiveIndices(
            segments,
            viewport.visibleStartSeconds,
            viewport.visibleEndSeconds,
          );
          return (
            <div className="agent-editing-timeline__lanes">
              <section className="agent-editing-timeline__track" aria-label="Video track" role="group">
                <TrackLabel icon={<VideoIcon />} count={activeSequence.videos.length}>Video Track</TrackLabel>
                <div
                  className="agent-editing-timeline__lane"
                  style={{ width: viewport.contentWidth }}
                  role="slider"
                  tabIndex={0}
                  aria-label="Seek video track"
                  aria-valuemin={0}
                  aria-valuemax={sequenceDuration}
                  aria-valuenow={playheadSeconds}
                  onClick={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    onPlayheadChange(clamp((event.clientX - rect.left) / viewport.pixelsPerSecond, 0, sequenceDuration));
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowLeft") onPlayheadChange(Math.max(0, playheadSeconds - 1));
                    if (event.key === "ArrowRight") onPlayheadChange(Math.min(sequenceDuration, playheadSeconds + 1));
                  }}
                >
                  {activeSequence.videos.length === 0 ? (
                    <span className="agent-editing-timeline__empty">Connect ready Video nodes to build the sequence.</span>
                  ) : activeSequence.videos.map((input, index) => {
                    const manifestIndex = inputs.videos.indexOf(input);
                    return (
                    <VideoTimelineClip
                      key={input.referenceId}
                      active={activeFrames.has(index)}
                      disabled={exportRunning}
                      index={manifestIndex}
                      input={input}
                      onCommitStagedManifest={onCommitStagedManifest}
                      onDiscardStagedManifest={onDiscardStagedManifest}
                      onSelect={() => onSelectReference(input.referenceId)}
                      onStageVideo={onStageVideo}
                      pixelsPerSecond={viewport.pixelsPerSecond}
                      segment={segments[index]!}
                      selected={input.referenceId === selectedReferenceId}
                    />
                    );
                  })}
                </div>
              </section>

              <section
                className="agent-editing-timeline__track agent-editing-timeline__track--audio"
                aria-label="Audio track"
                role="group"
              >
                <TrackLabel
                  icon={(
                    <img
                      src="/icon/arcticons--ambient-music-mod.svg"
                      alt=""
                      aria-hidden="true"
                    />
                  )}
                  onSelect={inputs.bgm ? () => onSelectReference(inputs.bgm!.referenceId) : undefined}
                  details={inputs.bgm ? (
                    <AudioTrackControls
                      disabled={exportRunning}
                      enabled={inputs.bgm.entry.enabled}
                      onSetBgm={onSetBgm}
                      onSetBgmVolume={onSetBgmVolume}
                      volume={inputs.bgm.entry.volume}
                    />
                  ) : null}
                >Audio Track</TrackLabel>
                <div className="agent-editing-timeline__lane agent-editing-timeline__lane--audio" style={{ width: viewport.contentWidth }}>
                  {inputs.bgm ? (
                    <AudioWaveformTrack
                      audioUrl={inputs.bgm.asset?.media_url ?? null}
                      disabled={exportRunning}
                      durationSeconds={inputs.bgm.asset?.duration_seconds ?? sequenceDuration}
                      name="BGM"
                      onSetBgm={onSetBgm}
                      playheadSeconds={playheadSeconds}
                      renderedWidth={Math.max(1, Math.min(512, Math.ceil(viewport.contentWidth / 3)))}
                      timelineDuration={sequenceDuration}
                      trimEndSeconds={inputs.bgm.entry.trim_end_seconds}
                      trimStartSeconds={inputs.bgm.entry.trim_start_seconds}
                    />
                  ) : <span className="agent-editing-timeline__empty">Optional BGM input</span>}
                </div>
              </section>
            </div>
          );
        }}
      </EditingTimelineViewport>

      {activeSequence.inactiveVideos.length ? (
        <section className="agent-editing-timeline__inactive" role="region" aria-label="Inactive sources">
          <header>
            <strong>Inactive sources</strong>
            <span>{activeSequence.inactiveVideos.length}</span>
          </header>
          <ul>
            {activeSequence.inactiveVideos.map((input) => {
              const manifestIndex = inputs.videos.indexOf(input);
              const label = inputLabel(input, manifestIndex);
              return (
                <li key={input.referenceId}>
                  <button
                    type="button"
                    aria-label={`Inspect ${label}`}
                    aria-pressed={input.referenceId === selectedReferenceId}
                    onClick={() => onSelectReference(input.referenceId)}
                  >
                    <strong>{label}</strong>
                    <span>{inactiveStatus(input)}</span>
                  </button>
                  <label>
                    <input
                      type="checkbox"
                      aria-label={`Enable ${label}`}
                      checked={input.entry.enabled}
                      disabled={exportRunning}
                      onChange={(event) => onUpdateVideo(input.referenceId, { enabled: event.currentTarget.checked })}
                    />
                    <span>Enabled</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {selectedVideo ? (
        <ClipPropertiesToolbar
          disabled={exportRunning}
          index={selectedVideoIndex}
          input={selectedVideo}
          onMove={(offset) => onMoveVideo(selectedVideo.referenceId, offset)}
          onUpdate={(patch) => onUpdateVideo(selectedVideo.referenceId, patch)}
          total={inputs.videos.length}
        />
      ) : selectedBgm ? null : (
        <div className="agent-editing-timeline__no-selection">Select a clip or audio track to edit its settings.</div>
      )}
    </div>
  );
}
