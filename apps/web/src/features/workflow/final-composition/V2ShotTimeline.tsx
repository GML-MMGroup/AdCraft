/* eslint-disable react-refresh/only-export-components */
import type { TimelineEditor, TimelineState } from "@xzdarcy/react-timeline-editor";
// Version 1.0.0 does not publish a declaration mapping for its working CJS runtime entry.
// @ts-expect-error The root entry is not Node-compatible, but this artifact exports Timeline.
import { Timeline } from "@xzdarcy/react-timeline-editor/dist/index.cjs.js";
import {
  useEffect,
  useLayoutEffect,
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
  TrashIcon,
} from "../../../icons.tsx";
import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineClip,
  V2FinalTimelineSource,
  V2FinalTimelineTrack,
} from "../../../types-v2.ts";
import {
  findTimelineSource,
  timelineSourceKey,
  useTimelineMediaVisuals,
} from "./useTimelineMediaVisuals.ts";
import type { V2FinalCompositionTool } from "./useV2FinalCompositionEditor.ts";

const ROW_HEIGHT = 48;
const BASE_SCALE_WIDTH = 52;
const MIN_DISPLAYED_DURATION_SECONDS = 12;
const LIBRARY_ACTION_END_PADDING_SCALE_COUNT = 5;
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

type TimelineGestureMutation = {
  timeline: V2FinalCompositionTimeline;
};

type TimelineGestureController = {
  moveClip: (
    clipId: string,
    trackIdOrStartTime: string | number,
    startTime?: number,
  ) => TimelineGestureMutation | null | void;
  trimClip: (
    clipId: string,
    edge: "left" | "right",
    sourceTime: number,
  ) => TimelineGestureMutation | null | void;
  finalizeGesture: () => void;
};

type V2ShotTimelineProps = TimelineGestureController & {
  workflowId: string;
  timeline: V2FinalCompositionTimeline;
  sources: V2FinalTimelineSource[];
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
  onRemoveImportedLane: (trackId: string) => unknown;
  mediaUrl: (path?: string | null) => string;
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
        flexible: (clip.clip_type === "video" || clip.clip_type === "audio") && track.enabled && clip.enabled && !locked,
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

export function displayedShotTimelineDuration(timeline: V2FinalCompositionTimeline) {
  return Math.max(
    MIN_DISPLAYED_DURATION_SECONDS,
    timeline.duration_seconds,
    ...timeline.clips.map((clip) => clip.start_time + clip.duration),
  );
}

export function effectiveShotTimelineScaleCount(timeline: V2FinalCompositionTimeline) {
  const maxActionEnd = Math.max(
    0,
    ...toShotTimelineRows(timeline).flatMap((row) => row.actions.map((action) => action.end)),
  );
  return Math.max(
    Math.ceil(displayedShotTimelineDuration(timeline)),
    Math.ceil(maxActionEnd) + LIBRARY_ACTION_END_PADDING_SCALE_COUNT,
  );
}

export function fitShotTimelineZoom(
  timeline: V2FinalCompositionTimeline,
  viewportWidth: number,
) {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return 1;
  return viewportWidth / (effectiveShotTimelineScaleCount(timeline) * BASE_SCALE_WIDTH);
}

export function activeCompatibilityPreviewClips(
  timeline: V2FinalCompositionTimeline,
  time: number,
) {
  const tracksById = new Map(timeline.tracks.map((track) => [track.track_id, track]));
  const activeClips = timeline.clips
    .filter((clip) => clip.enabled
      && tracksById.get(clip.track_id)?.enabled === true
      && time >= clip.start_time
      && time < clip.start_time + clip.duration)
    .sort((left, right) => (
      (tracksById.get(left.track_id)?.order ?? 0) - (tracksById.get(right.track_id)?.order ?? 0)
    ));
  return {
    visualClips: activeClips.filter((clip) => clip.clip_type === "video" || clip.clip_type === "image"),
    subtitleClips: activeClips.filter((clip) => clip.clip_type === "subtitle"),
  };
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
    let mutation: TimelineGestureMutation | null | void = undefined;
    if (Math.abs(action.start - clip.start_time) > EPSILON) {
      mutation = clip.clip_type === "audio"
        ? controller.moveClip(clip.clip_id, clip.track_id, action.start)
        : controller.moveClip(clip.clip_id, action.start);
    }
    controller.finalizeGesture();
    return mutation;
  }

  if (clip.clip_type !== "video" && clip.clip_type !== "audio") {
    controller.finalizeGesture();
    return;
  }
  const edge = gesture === "left" || gesture === "right"
    ? gesture
    : Math.abs(action.start - clip.start_time) > EPSILON ? "left" : "right";
  let mutation: TimelineGestureMutation | null | void = undefined;
  if (edge === "left") {
    if (Math.abs(action.start - clip.start_time) > EPSILON) {
      const sourceTime = clip.trim_in + (action.start - clip.start_time);
      mutation = controller.trimClip(clip.clip_id, "left", sourceTime);
    }
  } else if (Math.abs(action.end - (clip.start_time + clip.duration)) > EPSILON) {
    const originalEnd = clip.start_time + clip.duration;
    const originalTrimOut = clip.trim_out ?? clip.trim_in + clip.duration;
    const sourceTime = originalTrimOut + (action.end - originalEnd);
    mutation = controller.trimClip(clip.clip_id, "right", sourceTime);
  }
  controller.finalizeGesture();
  return mutation;
}

export function completeTimelineGesture(
  timeline: V2FinalCompositionTimeline,
  action: Pick<ShotTimelineAction, "id" | "start" | "end" | "effectId">,
  gesture: "move" | "resize" | "left" | "right",
  controller: TimelineGestureController,
  selectedClipIds: string[] = [],
) {
  const mutation = commitTimelineActionChange(timeline, action, gesture, controller);
  return toShotTimelineRows(mutation?.timeline ?? timeline, selectedClipIds);
}

export function V2ShotTimeline({
  workflowId,
  timeline,
  sources,
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
  onRemoveImportedLane,
  mediaUrl,
  moveClip,
  trimClip,
  finalizeGesture,
}: V2ShotTimelineProps) {
  const timelineRef = useRef<TimelineState>(null);
  const snapSuppressedRef = useRef(false);
  const [snapSuppressed, setSnapSuppressed] = useState(false);
  const projectedRows = useMemo(
    () => toShotTimelineRows(timeline, selectedClipIds),
    [selectedClipIds, timeline],
  );
  const [rows, setRows] = useState(projectedRows);
  const visibleTracks = useMemo(
    () => rows.map((row) => timeline.tracks.find((track) => track.track_id === row.id)!).filter(Boolean),
    [rows, timeline.tracks],
  );
  const clipsById = useMemo(
    () => new Map(timeline.clips.map((clip) => [clip.clip_id, clip])),
    [timeline.clips],
  );
  const displayedDuration = displayedShotTimelineDuration(timeline);
  const effectiveScaleCount = effectiveShotTimelineScaleCount(timeline);
  const mediaVisuals = useTimelineMediaVisuals({
    workflowId,
    timeline,
    sources,
    selectedClipIds,
    playheadSeconds,
    mediaUrl,
  });

  useLayoutEffect(() => {
    setRows(projectedRows);
  }, [projectedRows]);

  useEffect(() => {
    timelineRef.current?.setTime(Math.min(playheadSeconds, displayedDuration));
  }, [displayedDuration, playheadSeconds]);

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
    setRows(completeTimelineGesture(timeline, action, gesture, controller, selectedClipIds));
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
              onRemoveImportedLane={onRemoveImportedLane}
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
          minScaleCount={effectiveScaleCount}
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
            const source = findTimelineSource(sources, clip);
            const sourceKey = source ? timelineSourceKey(source) : "";
            const posterUrl = sourceKey ? mediaVisuals.posterUrls.get(sourceKey) : undefined;
            const waveform = sourceKey ? mediaVisuals.waveforms.get(sourceKey) : undefined;
            return (
              <div
                className={`v2-composition-timeline-clip is-${clip.clip_type} ${action.selected ? "is-selected" : ""}`}
                title={`${displayClipName(clip, visibleTracks)} - ${clip.duration.toFixed(2)} seconds`}
              >
                <span className="v2-shot-trim-handle is-left" aria-hidden="true" />
                {clip.clip_type === "video" && posterUrl ? (
                  <span className="v2-shot-poster-strip" aria-hidden="true">
                    {[0, 1, 2].map((index) => <img key={index} src={posterUrl} alt="" draggable={false} />)}
                  </span>
                ) : null}
                {clip.clip_type === "audio" && waveform ? (
                  <span className="v2-shot-waveform" aria-hidden="true">
                    {waveform.map((height, index) => (
                      <i key={index} style={{ height: `${Math.round(height * 100)}%` }} />
                    ))}
                  </span>
                ) : null}
                <span className="v2-shot-clip-label">
                  {displayClipName(clip, visibleTracks)} · {clip.duration.toFixed(2)}s
                </span>
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
          onActionResizing={({ action, row }) => (action.effectId === "shot" || action.effectId === "bgm")
            && row.id === clipsById.get(action.id)?.track_id}
          onActionResizeEnd={({ action, start, end, dir }) => {
            commitAtGestureEnd({ ...action, start, end } as ShotTimelineAction, dir);
          }}
          onClickTimeArea={(time) => {
            onSetPlayheadSeconds(Math.max(0, Math.min(displayedDuration, time)));
            return true;
          }}
          onCursorDrag={(time) => onSetPlayheadSeconds(Math.max(0, Math.min(displayedDuration, time)))}
          onCursorDragEnd={(time) => onSetPlayheadSeconds(Math.max(0, Math.min(displayedDuration, time)))}
          onClickRow={(_event, { time }) => onSetPlayheadSeconds(Math.max(0, Math.min(displayedDuration, time)))}
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
  onRemoveImportedLane,
}: {
  track: V2FinalTimelineTrack;
  clips: V2FinalTimelineClip[];
  index: number;
  shotTracks: V2FinalTimelineTrack[];
  onUpdateTrack: (trackId: string, update: Partial<V2FinalTimelineTrack>) => void;
  onSetClipAudio: (clipId: string, update: { muted?: boolean; volume?: number }) => void;
  onReorderLane: (trackId: string, targetIndex: number) => unknown;
  onRemoveImportedLane: (trackId: string) => unknown;
}) {
  const locked = isTrackLocked(track);
  const editor = editorMetadata(track);
  const allMuted = clips.length > 0 && clips.every((clip) => clip.muted || clip.audio.muted);
  const shotIndex = shotTracks.findIndex((candidate) => candidate.track_id === track.track_id);
  const label = displayTrackName(track, index);
  const imported = track.track_type === "video" && editor.imported === true;

  return (
    <div
      className={`v2-composition-track-label ${track.enabled ? "" : "is-disabled"}`}
      style={{ height: ROW_HEIGHT }}
    >
      {imported ? (
        <EditableImportedLaneName track={track} label={label} onUpdateTrack={onUpdateTrack} />
      ) : <strong title={label}>{label}</strong>}
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
        {imported ? (
          <LaneButton
            label={`Remove imported lane ${label}`}
            disabled={locked}
            onClick={() => onRemoveImportedLane(track.track_id)}
          >
            <TrashIcon />
          </LaneButton>
        ) : null}
      </span>
    </div>
  );
}

function EditableImportedLaneName({
  track,
  label,
  onUpdateTrack,
}: {
  track: V2FinalTimelineTrack;
  label: string;
  onUpdateTrack: (trackId: string, update: Partial<V2FinalTimelineTrack>) => void;
}) {
  const [draft, setDraft] = useState(label);
  const cancelRenameCommitRef = useRef(false);
  useEffect(() => {
    cancelRenameCommitRef.current = false;
    setDraft(label);
  }, [label]);
  const commit = () => {
    if (cancelRenameCommitRef.current) {
      cancelRenameCommitRef.current = false;
      return;
    }
    const name = draft.trim() || "Imported video";
    setDraft(name);
    if (name === label) return;
    onUpdateTrack(track.track_id, {
      metadata: { ...track.metadata, editor: { ...editorMetadata(track), name } },
    });
  };
  return (
    <input
      aria-label="Imported video name"
      title="Imported video name"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onFocus={() => {
        cancelRenameCommitRef.current = false;
      }}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          event.currentTarget.blur();
        }
        if (event.key === "Escape") {
          event.preventDefault();
          cancelRenameCommitRef.current = true;
          setDraft(label);
          event.currentTarget.blur();
        }
      }}
    />
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
