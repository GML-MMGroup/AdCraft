import { useEffect, useMemo, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent } from "react";

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
  onStageVideoOrder: (orderedReferenceIds: readonly string[]) => void;
}

interface ClipLayout {
  referenceId: string;
  left: number;
  right: number;
  center: number;
}

interface ClipDragState {
  referenceId: string;
  initialOrder: string[];
  offsetX: number;
  dropIndicatorLeft: number;
}

interface ClipDragSession {
  referenceId: string;
  initialOrder: string[];
  layouts: ClipLayout[];
  startClientX: number;
  laneLeft: number;
  pointerId: number;
  targetOrder: string[];
  targetIndex: number;
  moved: boolean;
  finished: boolean;
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
  onStageVideoOrder,
  onStageVideo,
  onUpdateVideo,
  playheadSeconds,
  selectedReferenceId,
  sequence,
}: EditingTimelineProps) {
  const videoLaneRef = useRef<HTMLDivElement>(null);
  const clipDragCancelRef = useRef<(() => void) | null>(null);
  const clipDragSessionRef = useRef<ClipDragSession | null>(null);
  const [clipDrag, setClipDrag] = useState<ClipDragState | null>(null);
  const activeSequence = useMemo(
    () => sequence ?? buildPlayableEditingSequence(inputs.videos),
    [inputs.videos, sequence],
  );
  const { segments } = activeSequence;
  const sequenceDuration = activeSequence.duration;
  const selectedVideoIndex = inputs.videos.findIndex((input) => input.referenceId === selectedReferenceId);
  const selectedVideo = selectedVideoIndex >= 0 ? inputs.videos[selectedVideoIndex] : null;
  const selectedBgm = inputs.bgm?.referenceId === selectedReferenceId ? inputs.bgm : null;

  useEffect(() => () => clipDragCancelRef.current?.(), []);

  const startReorder = (referenceId: string, event: ReactPointerEvent<HTMLButtonElement>) => {
    if (exportRunning || event.button !== 0 || clipDragSessionRef.current) return;
    const lane = videoLaneRef.current;
    if (!lane) return;
    const laneBounds = lane.getBoundingClientRect();
    const clipElements = [...lane.querySelectorAll<HTMLElement>(".agent-editing-timeline-clip[data-reference-id]")];
    const layouts = clipElements.flatMap((element) => {
      const id = element.dataset.referenceId;
      if (!id) return [];
      const bounds = element.getBoundingClientRect();
      const left = bounds.left - laneBounds.left;
      const right = bounds.right - laneBounds.left;
      return [{ referenceId: id, left, right, center: (left + right) / 2 }];
    });
    const initialOrder = activeSequence.videos.map((input) => input.referenceId);
    const draggedIndex = initialOrder.indexOf(referenceId);
    if (draggedIndex < 0 || layouts.length < 2) return;

    const session: ClipDragSession = {
      referenceId,
      initialOrder,
      layouts,
      startClientX: event.clientX,
      laneLeft: laneBounds.left,
      pointerId: event.pointerId,
      targetOrder: initialOrder,
      targetIndex: draggedIndex,
      moved: false,
      finished: false,
    };
    clipDragSessionRef.current = session;
    const updateDrag = (pointerEvent: PointerEvent) => {
      const current = clipDragSessionRef.current;
      if (!current || current.finished) return;
      const offsetX = pointerEvent.clientX - current.startClientX;
      if (!current.moved && Math.abs(offsetX) < 4) return;
      current.moved = true;
      const others = current.layouts.filter((layout) => layout.referenceId !== current.referenceId);
      const localClientX = pointerEvent.clientX - current.laneLeft;
      const foundTargetIndex = others.findIndex((layout) => localClientX < layout.center);
      const normalizedTargetIndex = foundTargetIndex < 0 ? others.length : foundTargetIndex;
      const targetOrder = [...others.map((layout) => layout.referenceId)];
      targetOrder.splice(normalizedTargetIndex, 0, current.referenceId);
      const previousLayout = others[normalizedTargetIndex - 1];
      const nextLayout = others[normalizedTargetIndex];
      const dropIndicatorLeft = normalizedTargetIndex === 0
        ? nextLayout?.left ?? 0
        : normalizedTargetIndex >= others.length
          ? previousLayout?.right ?? 0
          : ((previousLayout?.right ?? 0) + (nextLayout?.left ?? 0)) / 2;
      current.targetIndex = normalizedTargetIndex;
      current.targetOrder = targetOrder;
      setClipDrag({
        referenceId: current.referenceId,
        initialOrder: current.initialOrder,
        offsetX,
        dropIndicatorLeft,
      });
      pointerEvent.preventDefault();
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      window.removeEventListener("keydown", onWindowKeyDown);
      if (clipDragCancelRef.current === cancel) clipDragCancelRef.current = null;
      clipDragSessionRef.current = null;
      setClipDrag(null);
    };
    const finish = (commit: boolean) => {
      const current = clipDragSessionRef.current;
      if (!current || current.finished) return;
      current.finished = true;
      cleanup();
      if (commit && current.moved && current.targetOrder.some((id, index) => id !== current.initialOrder[index])) {
        onStageVideoOrder(current.targetOrder);
        void onCommitStagedManifest();
      }
    };
    const onPointerMove = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === session.pointerId) updateDrag(pointerEvent);
    };
    const onPointerUp = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === session.pointerId) finish(true);
    };
    const onPointerCancel = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === session.pointerId) finish(false);
    };
    const onWindowKeyDown = (keyboardEvent: globalThis.KeyboardEvent) => {
      if (keyboardEvent.key === "Escape") {
        keyboardEvent.preventDefault();
        finish(false);
      }
    };
    function cancel() {
      finish(false);
    }

    clipDragCancelRef.current?.();
    clipDragCancelRef.current = cancel;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
    window.addEventListener("keydown", onWindowKeyDown);
  };

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
                <TrackLabel
                  icon={<img src="/imgs/node-icons/video.svg" alt="" aria-hidden="true" />}
                  count={activeSequence.videos.length}
                >Video Track</TrackLabel>
                <div
                  ref={videoLaneRef}
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
                      dragging={clipDrag?.referenceId === input.referenceId}
                      index={manifestIndex}
                      input={input}
                      onCommitStagedManifest={onCommitStagedManifest}
                      onDiscardStagedManifest={onDiscardStagedManifest}
                      onSelect={() => onSelectReference(input.referenceId)}
                      onStageVideo={onStageVideo}
                      onStartReorder={startReorder}
                      pixelsPerSecond={viewport.pixelsPerSecond}
                      reorderOffsetX={clipDrag?.referenceId === input.referenceId ? clipDrag.offsetX : 0}
                      segment={segments[index]!}
                      selected={input.referenceId === selectedReferenceId}
                    />
                    );
                  })}
                  {clipDrag ? (
                    <span
                      className="agent-editing-timeline__drop-indicator"
                      style={{ left: clipDrag.dropIndicatorLeft }}
                      aria-hidden="true"
                    />
                  ) : null}
                </div>
              </section>

              <section
                className="agent-editing-timeline__track agent-editing-timeline__track--audio"
                aria-label="Audio track"
                role="group"
              >
                <TrackLabel
                  icon={<img src="/imgs/node-icons/audio.svg" alt="" aria-hidden="true" />}
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
