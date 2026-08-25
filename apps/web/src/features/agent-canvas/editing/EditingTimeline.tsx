import { useMemo, type ReactNode } from "react";

import { MuteIcon, UnmuteIcon, VideoIcon } from "../../../icons.tsx";
import type { EditingBgmEntryV2, EditingVideoEntryV2 } from "../../../types-v2.ts";
import { AudioWaveformTrack } from "./AudioWaveformTrack.tsx";
import { ClipPropertiesToolbar } from "./ClipPropertiesToolbar.tsx";
import {
  buildTimelineSegments,
} from "./editingTimelineMath.ts";
import { EditingTimelineViewport } from "./EditingTimelineViewport.tsx";
import { frameStripActiveIndices } from "./editingTimelineVisibility.ts";
import type { EditingInputs } from "./editingModel.ts";
import { VideoTimelineClip } from "./VideoTimelineClip.tsx";

export interface EditingTimelineProps {
  inputs: EditingInputs;
  timelineDuration: number;
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

function TrackLabel({
  children,
  count,
  icon,
  onSelect,
}: {
  children: string;
  count?: number;
  icon: ReactNode;
  onSelect?: () => void;
}) {
  return (
    <div className="agent-editing-timeline__track-label">
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
  timelineDuration,
}: EditingTimelineProps) {
  const segments = useMemo(() => buildTimelineSegments(inputs.videos.map((input) => ({
    referenceId: input.referenceId,
    sourceDuration: input.asset?.duration_seconds
      ?? input.entry.trim_end_seconds
      ?? input.entry.trim_start_seconds + 0.5,
    trimStart: input.entry.trim_start_seconds,
    trimEnd: input.entry.trim_end_seconds,
  }))), [inputs.videos]);
  const sequenceDuration = segments.at(-1)?.timelineEnd ?? Math.max(0, timelineDuration);
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
                <TrackLabel icon={<VideoIcon />} count={inputs.videos.length}>Video Track</TrackLabel>
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
                  {inputs.videos.length === 0 ? (
                    <span className="agent-editing-timeline__empty">Connect ready Video nodes to build the sequence.</span>
                  ) : inputs.videos.map((input, index) => (
                    <VideoTimelineClip
                      key={input.referenceId}
                      active={activeFrames.has(index)}
                      disabled={exportRunning}
                      index={index}
                      input={input}
                      onCommitStagedManifest={onCommitStagedManifest}
                      onDiscardStagedManifest={onDiscardStagedManifest}
                      onSelect={() => onSelectReference(input.referenceId)}
                      onStageVideo={onStageVideo}
                      pixelsPerSecond={viewport.pixelsPerSecond}
                      segment={segments[index]!}
                      selected={input.referenceId === selectedReferenceId}
                    />
                  ))}
                </div>
              </section>

              <section
                className="agent-editing-timeline__track agent-editing-timeline__track--audio"
                aria-label="Audio track"
                role="group"
              >
                <TrackLabel
                  icon={inputs.bgm ? <UnmuteIcon /> : <MuteIcon />}
                  onSelect={inputs.bgm ? () => onSelectReference(inputs.bgm!.referenceId) : undefined}
                >Audio Track</TrackLabel>
                <div className="agent-editing-timeline__lane agent-editing-timeline__lane--audio" style={{ width: viewport.contentWidth }}>
                  {inputs.bgm ? (
                    <AudioWaveformTrack
                      audioUrl={inputs.bgm.asset?.media_url ?? null}
                      disabled={exportRunning}
                      durationSeconds={inputs.bgm.asset?.duration_seconds ?? sequenceDuration}
                      enabled={inputs.bgm.entry.enabled}
                      fadeInSeconds={inputs.bgm.entry.fade_in_seconds}
                      fadeOutSeconds={inputs.bgm.entry.fade_out_seconds}
                      name={inputs.bgm.node?.title || inputs.bgm.asset?.display_name || "Campaign BGM"}
                      onSetBgm={onSetBgm}
                      onSetBgmVolume={onSetBgmVolume}
                      playheadSeconds={playheadSeconds}
                      renderedWidth={Math.max(1, Math.min(512, Math.ceil(viewport.contentWidth / 3)))}
                      trimEndSeconds={inputs.bgm.entry.trim_end_seconds}
                      trimStartSeconds={inputs.bgm.entry.trim_start_seconds}
                      volume={inputs.bgm.entry.volume}
                    />
                  ) : <span className="agent-editing-timeline__empty">Optional BGM input</span>}
                </div>
              </section>
            </div>
          );
        }}
      </EditingTimelineViewport>

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
