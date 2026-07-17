/* eslint-disable react-refresh/only-export-components */
import type { TimelineEditor, TimelineState } from "@xzdarcy/react-timeline-editor";
// Version 1.0.0 does not publish a declaration mapping for its working CJS runtime entry.
// @ts-expect-error The root entry is not Node-compatible, but this artifact exports Timeline.
import { Timeline } from "@xzdarcy/react-timeline-editor/dist/index.cjs.js";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ForwardRefExoticComponent,
  type RefAttributes,
} from "react";
import {
  AssetsIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  PreviewIcon,
} from "../../../icons.tsx";
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineTrack,
} from "../../../types-v2.ts";
import type { V2FinalCompositionTool } from "./useV2FinalCompositionEditor.ts";

const ROW_HEIGHT = 48;
const BASE_SCALE_WIDTH = 52;
const EPSILON = 1e-6;
const TimelineComponent = Timeline as ForwardRefExoticComponent<
  TimelineEditor & RefAttributes<TimelineState>
>;

export type ShotTimelineAction = {
  id: string;
  start: number;
  end: number;
  effectId: "shot" | "bgm";
  selected?: boolean;
  flexible?: boolean;
  movable?: boolean;
  disable?: boolean;
  minStart?: number;
};

export type ShotTimelineRow = {
  id: string;
  actions: ShotTimelineAction[];
  rowHeight: number;
  selected?: boolean;
  classNames?: string[];
};

type TimelineGestureController = {
  moveClip: (
    clipId: string,
    trackIdOrStartTime: string | number,
    startTime?: number,
  ) => unknown;
  trimClip: (
    clipId: string,
    edge: "left" | "right",
    sourceTime: number,
  ) => unknown;
  finalizeGesture: () => void;
};

type V2ShotTimelineProps = TimelineGestureController & {
  timeline: V2FinalCompositionTimeline;
  selectedClipIds: string[];
  playheadSeconds: number;
  zoom: number;
  snapEnabled: boolean;
  tool: V2FinalCompositionTool;
  onSetSnapEnabled: (enabled: boolean) => void;
  onSetSelectedClipIds: (clipIds: string[]) => void;
  onSetPlayheadSeconds: (seconds: number) => void;
  onSplitAtPlayhead: (clipId?: string) => unknown;
  onUpdateTrack: (trackId: string, update: Partial<V2FinalTimelineTrack>) => void;
  onSetClipAudio: (clipId: string, update: { muted?: boolean; volume?: number }) => void;
  onReorderLane: (trackId: string, targetIndex: number) => unknown;
};

const TIMELINE_EFFECTS = {
  shot: { id: "shot", name: "Shot" },
  bgm: { id: "bgm", name: "BGM" },
};

export function toShotTimelineRows(
  timeline: V2FinalCompositionTimeline,
  selectedClipIds: string[] = [],
): ShotTimelineRow[] {
  const selected = new Set(selectedClipIds);
  const shotTracks = timeline.tracks
    .filter((track) => track.track_type === "video")
    .sort((left, right) => right.order - left.order || left.track_id.localeCompare(right.track_id));
  const bgmTracks = timeline.tracks
    .filter((track) => track.track_type === "audio")
    .sort((left, right) => right.order - left.order || left.track_id.localeCompare(right.track_id));

  return [...shotTracks, ...bgmTracks].map((track) => {
    const locked = isTrackLocked(track);
    const actions = timeline.clips
      .filter((clip) => clip.track_id === track.track_id && clip.clip_type === track.track_type)
      .sort((left, right) => left.start_time - right.start_time || left.clip_id.localeCompare(right.clip_id))
      .map((clip): ShotTimelineAction => ({
        id: clip.clip_id,
        start: clip.start_time,
        end: clip.start_time + clip.duration,
        effectId: clip.clip_type === "audio" ? "bgm" : "shot",
        selected: selected.has(clip.clip_id),
        flexible: clip.clip_type === "video" && track.enabled && clip.enabled && !locked,
        movable: track.enabled && clip.enabled && !locked,
        disable: !track.enabled || !clip.enabled,
        minStart: 0,
      }));
    return {
      id: track.track_id,
      actions,
      rowHeight: ROW_HEIGHT,
      selected: actions.some((action) => action.selected),
      classNames: [
        track.track_type === "audio" ? "v2-shot-timeline-row-bgm" : "v2-shot-timeline-row-video",
        track.enabled ? "" : "is-disabled",
        locked ? "is-locked" : "",
      ].filter(Boolean),
    };
  });
}

export function commitTimelineActionChange(
  timeline: V2FinalCompositionTimeline,
  action: Pick<ShotTimelineAction, "id" | "start" | "end" | "effectId">,
  gesture: "move" | "resize" | "left" | "right",
  controller: TimelineGestureController,
) {
  const clip = timeline.clips.find((candidate) => candidate.clip_id === action.id);
  if (!clip) {
    controller.finalizeGesture();
    return;
  }

  if (gesture === "move") {
    if (Math.abs(action.start - clip.start_time) > EPSILON) {
      if (clip.clip_type === "audio") controller.moveClip(clip.clip_id, clip.track_id, action.start);
      else controller.moveClip(clip.clip_id, action.start);
    }
    controller.finalizeGesture();
    return;
  }

  if (clip.clip_type !== "video") {
    controller.finalizeGesture();
    return;
  }
  const edge = gesture === "left" || gesture === "right"
    ? gesture
    : Math.abs(action.start - clip.start_time) > EPSILON ? "left" : "right";
  if (edge === "left") {
    const sourceTime = clip.trim_in + (action.start - clip.start_time);
    controller.trimClip(clip.clip_id, "left", sourceTime);
  } else {
    const originalEnd = clip.start_time + clip.duration;
    const originalTrimOut = clip.trim_out ?? clip.trim_in + clip.duration;
    const sourceTime = originalTrimOut + (action.end - originalEnd);
    controller.trimClip(clip.clip_id, "right", sourceTime);
  }
  controller.finalizeGesture();
}

export function V2ShotTimeline({
  timeline,
  selectedClipIds,
  playheadSeconds,
  zoom,
  snapEnabled,
  tool,
  onSetSnapEnabled,
  onSetSelectedClipIds,
  onSetPlayheadSeconds,
  onSplitAtPlayhead,
  onUpdateTrack,
  onSetClipAudio,
  onReorderLane,
  moveClip,
  trimClip,
  finalizeGesture,
}: V2ShotTimelineProps) {
  const timelineRef = useRef<TimelineState>(null);
  const snapSuppressedRef = useRef(false);
  const [snapSuppressed, setSnapSuppressed] = useState(false);
  const rows = useMemo(
    () => toShotTimelineRows(timeline, selectedClipIds),
    [selectedClipIds, timeline],
  );
  const visibleTracks = useMemo(
    () => rows.map((row) => timeline.tracks.find((track) => track.track_id === row.id)!).filter(Boolean),
    [rows, timeline.tracks],
  );
  const clipsById = useMemo(
    () => new Map(timeline.clips.map((clip) => [clip.clip_id, clip])),
    [timeline.clips],
  );
  const duration = Math.max(
    12,
    timeline.duration_seconds,
    ...timeline.clips.map((clip) => clip.start_time + clip.duration),
  );

  useEffect(() => {
    timelineRef.current?.setTime(Math.min(playheadSeconds, duration));
  }, [duration, playheadSeconds]);

  useEffect(() => {
    const suppressSnap = (event: KeyboardEvent) => {
      if (event.key !== "Alt") return;
      snapSuppressedRef.current = true;
      setSnapSuppressed(true);
    };
    const restoreSnap = (event: KeyboardEvent) => {
      if (event.key !== "Alt") return;
      snapSuppressedRef.current = false;
      setSnapSuppressed(false);
    };
    const resetSnap = () => {
      snapSuppressedRef.current = false;
      setSnapSuppressed(false);
    };
    window.addEventListener("keydown", suppressSnap);
    window.addEventListener("keyup", restoreSnap);
    window.addEventListener("blur", resetSnap);
    return () => {
      window.removeEventListener("keydown", suppressSnap);
      window.removeEventListener("keyup", restoreSnap);
      window.removeEventListener("blur", resetSnap);
    };
  }, []);

  const controller = useMemo<TimelineGestureController>(
    () => ({ moveClip, trimClip, finalizeGesture }),
    [finalizeGesture, moveClip, trimClip],
  );

  const commitAtGestureEnd = (
    action: Pick<ShotTimelineAction, "id" | "start" | "end" | "effectId">,
    gesture: "move" | "left" | "right",
  ) => {
    const temporarilyDisableSnap = snapEnabled && snapSuppressedRef.current;
    if (temporarilyDisableSnap) onSetSnapEnabled(false);
    commitTimelineActionChange(timeline, action, gesture, controller);
    if (temporarilyDisableSnap) onSetSnapEnabled(true);
  };

  const handleClipSelection = (clipId: string, extend: boolean) => {
    if (!extend) {
      onSetSelectedClipIds([clipId]);
      return;
    }
    onSetSelectedClipIds(
      selectedClipIds.includes(clipId)
        ? selectedClipIds.filter((candidate) => candidate !== clipId)
        : [...selectedClipIds, clipId],
    );
  };

  return (
    <section className="v2-composition-timeline v2-shot-timeline" aria-label="Shot timeline editor">
      <div
        className="v2-shot-timeline-grid"
        style={{ display: "grid", gridTemplateColumns: "132px minmax(0, 1fr)", minWidth: 0 }}
      >
        <div className="v2-shot-timeline-headers" aria-label="Timeline lanes">
          <div aria-hidden="true" style={{ height: 42 }} />
          {visibleTracks.map((track, index) => (
            <LaneHeader
              key={track.track_id}
              track={track}
              clips={timeline.clips.filter((clip) => clip.track_id === track.track_id)}
              index={index}
              shotTracks={visibleTracks.filter((candidate) => candidate.track_type === "video")}
              onUpdateTrack={onUpdateTrack}
              onSetClipAudio={onSetClipAudio}
              onReorderLane={onReorderLane}
            />
          ))}
        </div>
        <TimelineComponent
          ref={timelineRef}
          editorData={rows}
          effects={TIMELINE_EFFECTS}
          scale={1}
          scaleSplitCount={Math.max(1, Math.min(timeline.fps, 30))}
          scaleWidth={BASE_SCALE_WIDTH * zoom}
          minScaleCount={Math.ceil(duration)}
          maxScaleCount={86400}
          startLeft={0}
          rowHeight={ROW_HEIGHT}
          gridSnap={snapEnabled && !snapSuppressed}
          dragLine={snapEnabled && !snapSuppressed}
          hideCursor={false}
          enableRowDrag={false}
          autoScroll
          style={{ width: "100%", height: Math.max(90, 42 + rows.length * ROW_HEIGHT) }}
          getScaleRender={(seconds) => formatRulerTime(seconds)}
          getActionRender={(action) => {
            const clip = clipsById.get(action.id);
            if (!clip) return null;
            return (
              <div
                className={`v2-composition-timeline-clip is-${clip.clip_type} ${action.selected ? "is-selected" : ""}`}
                title={`${displayClipName(clip, visibleTracks)} - ${clip.duration.toFixed(2)} seconds`}
              >
                <span className="v2-shot-trim-handle is-left" aria-hidden="true" />
                <span>{displayClipName(clip, visibleTracks)} · {clip.duration.toFixed(2)}s</span>
                {!clip.muted ? <span className="v2-shot-source-audio" aria-hidden="true">A</span> : null}
                <span className="v2-shot-trim-handle is-right" aria-hidden="true" />
              </div>
            );
          }}
          onActionMoveStart={() => undefined}
          onActionMoving={({ action, row }) => clipsById.get(action.id)?.track_id === row.id}
          onActionMoveEnd={({ action, start, end }) => {
            commitAtGestureEnd({ ...action, start, end } as ShotTimelineAction, "move");
          }}
          onActionResizeStart={() => undefined}
          onActionResizing={({ action, row }) => action.effectId === "shot" && row.id === clipsById.get(action.id)?.track_id}
          onActionResizeEnd={({ action, start, end, dir }) => {
            commitAtGestureEnd({ ...action, start, end } as ShotTimelineAction, dir);
          }}
          onClickTimeArea={(time) => {
            onSetPlayheadSeconds(Math.max(0, Math.min(duration, time)));
            return true;
          }}
          onCursorDrag={(time) => onSetPlayheadSeconds(Math.max(0, Math.min(duration, time)))}
          onCursorDragEnd={(time) => onSetPlayheadSeconds(Math.max(0, Math.min(duration, time)))}
          onClickRow={(_event, { time }) => onSetPlayheadSeconds(Math.max(0, Math.min(duration, time)))}
          onClickActionOnly={(event, { action, time }) => {
            event.stopPropagation();
            if (tool === "blade" && action.effectId === "shot") {
              onSetPlayheadSeconds(time);
              onSplitAtPlayhead(action.id);
              return;
            }
            handleClipSelection(action.id, event.shiftKey || event.metaKey || event.ctrlKey);
          }}
          onChange={() => false}
        />
      </div>
    </section>
  );
}

function LaneHeader({
  track,
  clips,
  index,
  shotTracks,
  onUpdateTrack,
  onSetClipAudio,
  onReorderLane,
}: {
  track: V2FinalTimelineTrack;
  clips: V2FinalTimelineClip[];
  index: number;
  shotTracks: V2FinalTimelineTrack[];
  onUpdateTrack: (trackId: string, update: Partial<V2FinalTimelineTrack>) => void;
  onSetClipAudio: (clipId: string, update: { muted?: boolean; volume?: number }) => void;
  onReorderLane: (trackId: string, targetIndex: number) => unknown;
}) {
  const locked = isTrackLocked(track);
  const editor = editorMetadata(track);
  const allMuted = clips.length > 0 && clips.every((clip) => clip.muted || clip.audio.muted);
  const shotIndex = shotTracks.findIndex((candidate) => candidate.track_id === track.track_id);
  const label = displayTrackName(track, index);

  return (
    <div
      className={`v2-composition-track-label ${track.enabled ? "" : "is-disabled"}`}
      style={{ height: ROW_HEIGHT }}
    >
      <strong title={label}>{label}</strong>
      <span>
        {track.track_type === "video" ? (
          <>
            <button
              type="button"
              draggable={!locked}
              disabled={locked}
              aria-label={`Drag to reorder ${label}`}
              title={`Drag to reorder ${label}`}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("application/x-adcraft-shot-lane", track.track_id);
              }}
              onDragOver={(event) => {
                if (!locked) event.preventDefault();
              }}
              onDrop={(event) => {
                if (locked || shotIndex < 0) return;
                const sourceTrackId = event.dataTransfer.getData("application/x-adcraft-shot-lane");
                if (!sourceTrackId || sourceTrackId === track.track_id) return;
                event.preventDefault();
                onReorderLane(sourceTrackId, shotIndex);
              }}
            >
              <span aria-hidden="true">::</span>
            </button>
            <LaneButton
              label={`Move ${label} up`}
              disabled={locked || shotIndex <= 0}
              onClick={() => onReorderLane(track.track_id, shotIndex - 1)}
            >
              <ChevronUpIcon />
            </LaneButton>
            <LaneButton
              label={`Move ${label} down`}
              disabled={locked || shotIndex < 0 || shotIndex >= shotTracks.length - 1}
              onClick={() => onReorderLane(track.track_id, shotIndex + 1)}
            >
              <ChevronDownIcon />
            </LaneButton>
          </>
        ) : null}
        <LaneButton
          label={track.enabled ? `Hide ${label}` : `Show ${label}`}
          pressed={track.enabled}
          onClick={() => onUpdateTrack(track.track_id, { enabled: !track.enabled })}
        >
          <PreviewIcon />
        </LaneButton>
        <LaneButton
          label={locked ? `Unlock ${label}` : `Lock ${label}`}
          pressed={locked}
          onClick={() => onUpdateTrack(track.track_id, {
            metadata: { ...track.metadata, editor: { ...editor, locked: !locked } },
          })}
        >
          <span aria-hidden="true">{locked ? "L" : "U"}</span>
        </LaneButton>
        <LaneButton
          label={allMuted ? `Unmute ${label}` : `Mute ${label}`}
          pressed={allMuted}
          disabled={!clips.length}
          onClick={() => clips.forEach((clip) => onSetClipAudio(clip.clip_id, { muted: !allMuted }))}
        >
          <AssetsIcon />
        </LaneButton>
      </span>
    </div>
  );
}

function LaneButton({
  label,
  pressed,
  disabled,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function editorMetadata(track: V2FinalTimelineTrack) {
  const editor = track.metadata.editor;
  return typeof editor === "object" && editor !== null && !Array.isArray(editor)
    ? editor as Record<string, unknown>
    : {};
}

function isTrackLocked(track: V2FinalTimelineTrack) {
  return editorMetadata(track).locked === true;
}

function displayTrackName(track: V2FinalTimelineTrack, index: number) {
  const name = editorMetadata(track).name;
  if (typeof name === "string" && name.trim()) return name;
  return track.track_type === "audio" ? "BGM" : `Shot ${String(index + 1).padStart(2, "0")}`;
}

function displayClipName(clip: V2FinalTimelineClip, tracks: V2FinalTimelineTrack[]) {
  const trackIndex = tracks.findIndex((track) => track.track_id === clip.track_id);
  const track = tracks[trackIndex];
  return track ? displayTrackName(track, trackIndex) : clip.clip_type === "audio" ? "BGM" : "Shot";
}

function formatRulerTime(value: number) {
  const seconds = Math.max(0, Math.round(value));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
