import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

import { VideoIcon } from "../../../icons.tsx";
import type { CanvasNodeStatusV2, EditingVideoEntryV2 } from "../../../types-v2.ts";
import {
  clampTrimRange,
  MIN_EDITED_CLIP_SECONDS,
  type TimelineSegment,
} from "./editingTimelineMath.ts";
import type { EditingBoundInput } from "./editingModel.ts";
import { useVideoFrameStrip } from "./useVideoFrameStrip.ts";
import { mediaAssetContentPath, mediaAssetPreviewPath } from "../../../workflow/mediaPreview.ts";

interface VideoTimelineClipProps {
  active: boolean;
  disabled: boolean;
  dragging?: boolean;
  index: number;
  input: EditingBoundInput<EditingVideoEntryV2>;
  onCommitStagedManifest: () => void | Promise<unknown>;
  onDiscardStagedManifest: () => void;
  onSelect: () => void;
  onStageVideo: (referenceId: string, patch: Partial<EditingVideoEntryV2>) => void;
  onStartMove: (referenceId: string, event: ReactPointerEvent<HTMLButtonElement>) => void;
  invalidDrop?: boolean;
  pixelsPerSecond: number;
  moveOffsetX?: number;
  segment: TimelineSegment;
  selected: boolean;
}

interface TrimRange {
  start: number;
  end: number;
}

function statusOf(input: EditingBoundInput<EditingVideoEntryV2>): CanvasNodeStatusV2 | "unavailable" {
  return input.node?.status ?? input.asset?.status ?? "unavailable";
}

function seconds(value: number): string {
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(Math.round(value % 60)).padStart(2, "0")}`;
}

function roundTrim(value: number): number {
  return Math.round(value * 1_000) / 1_000;
}

export function VideoTimelineClip({
  active,
  disabled,
  dragging = false,
  index,
  input,
  onCommitStagedManifest,
  onDiscardStagedManifest,
  onSelect,
  onStageVideo,
  onStartMove,
  invalidDrop = false,
  pixelsPerSecond,
  moveOffsetX = 0,
  segment,
  selected,
}: VideoTimelineClipProps) {
  const sourceDuration = Math.max(0, input.asset?.duration_seconds ?? segment.sourceEnd);
  const label = input.node?.title || input.asset?.display_name || `Shot ${index + 1}`;
  const [trimRange, setTrimRange] = useState<TrimRange>({ start: segment.sourceStart, end: segment.sourceEnd });
  const dragCancelRef = useRef<(() => void) | null>(null);
  const samples = useVideoFrameStrip({
    assetId: input.asset?.asset_id ?? input.entry.asset_id ?? input.referenceId,
    mediaUrl: input.asset ? mediaAssetContentPath(input.asset) || null : null,
    previewUrl: input.asset ? mediaAssetPreviewPath(input.asset) || null : null,
    sourceStart: segment.sourceStart,
    sourceEnd: segment.sourceEnd,
    renderedWidth: Math.max(0, (segment.timelineEnd - segment.timelineStart) * pixelsPerSecond),
    active,
  });

  useEffect(() => {
    setTrimRange({ start: segment.sourceStart, end: segment.sourceEnd });
  }, [segment.sourceEnd, segment.sourceStart]);

  useEffect(() => () => dragCancelRef.current?.(), []);

  const stageRange = (edge: "start" | "end", range: TrimRange) => {
    setTrimRange(range);
    onStageVideo(input.referenceId, edge === "start"
      ? { trim_start_seconds: range.start }
      : { trim_end_seconds: range.end });
  };

  const startDrag = (edge: "start" | "end", event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);

    const target = event.currentTarget;
    const pointerId = event.pointerId;
    const startClientX = event.clientX;
    const initial = { ...trimRange };
    let last = initial;
    let changed = false;
    let staged = false;
    let finished = false;

    const cleanup = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      window.removeEventListener("keydown", onWindowKeyDown);
      if (target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
      if (dragCancelRef.current === cancel) dragCancelRef.current = null;
    };
    const finish = (commit: boolean) => {
      if (finished) return;
      finished = true;
      cleanup();
      if (commit && changed) void onCommitStagedManifest();
      if (commit && staged && !changed) onDiscardStagedManifest();
    };
    const onPointerMove = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== pointerId || finished) return;
      const deltaSeconds = pixelsPerSecond > 0 ? (pointerEvent.clientX - startClientX) / pixelsPerSecond : 0;
      const clamped = clampTrimRange({
        sourceDuration,
        start: edge === "start" ? initial.start + deltaSeconds : initial.start,
        end: edge === "end" ? initial.end + deltaSeconds : initial.end,
        edge,
      });
      const next = { start: roundTrim(clamped.start), end: roundTrim(clamped.end) };
      if (next.start === last.start && next.end === last.end) return;
      last = next;
      changed = next.start !== initial.start || next.end !== initial.end;
      staged = true;
      stageRange(edge, next);
    };
    const onPointerUp = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === pointerId) finish(true);
    };
    const onPointerCancel = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== pointerId) return;
      setTrimRange(initial);
      cancel();
    };
    function cancel() {
      if (finished) return;
      finish(false);
      onDiscardStagedManifest();
    }
    const onWindowKeyDown = (keyboardEvent: globalThis.KeyboardEvent) => {
      if (keyboardEvent.key !== "Escape") return;
      keyboardEvent.preventDefault();
      setTrimRange(initial);
      cancel();
    };

    dragCancelRef.current?.();
    dragCancelRef.current = cancel;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
    window.addEventListener("keydown", onWindowKeyDown);
  };

  const onHandleKeyDown = (edge: "start" | "end", event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    event.stopPropagation();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const delta = direction * (event.shiftKey ? 1 : 0.1);
    const clamped = clampTrimRange({
      sourceDuration,
      start: edge === "start" ? trimRange.start + delta : trimRange.start,
      end: edge === "end" ? trimRange.end + delta : trimRange.end,
      edge,
    });
    const next = { start: roundTrim(clamped.start), end: roundTrim(clamped.end) };
    if (next.start === trimRange.start && next.end === trimRange.end) return;
    stageRange(edge, next);
    void onCommitStagedManifest();
  };

  const renderHandle = (edge: "start" | "end") => (
    <div
      className={`agent-editing-timeline-clip__trim agent-editing-timeline-clip__trim--${edge}`}
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label={`Trim ${edge} ${label}`}
      aria-valuemin={edge === "start" ? 0 : endMinimum}
      aria-valuemax={edge === "start" ? startMaximum : sourceDuration}
      aria-valuenow={edge === "start" ? trimRange.start : trimRange.end}
      aria-disabled={disabled}
      onKeyDown={(event) => onHandleKeyDown(edge, event)}
      onPointerDown={(event) => startDrag(edge, event)}
    >
      <span aria-hidden="true" />
    </div>
  );

  const clipWidth = (segment.timelineEnd - segment.timelineStart) * pixelsPerSecond;
  const hasFrame = samples.some((sample) => Boolean(sample.url));
  const effectiveMinimum = Math.min(MIN_EDITED_CLIP_SECONDS, sourceDuration);
  const startMaximum = Math.max(0, Math.min(sourceDuration, trimRange.end - effectiveMinimum));
  const endMinimum = Math.min(sourceDuration, Math.max(0, trimRange.start + effectiveMinimum));

  return (
    <div
      className={`agent-editing-timeline-clip agent-editing-timeline__clip--${statusOf(input)}${selected ? " is-selected" : ""}${dragging ? " is-moving" : ""}${invalidDrop ? " is-invalid-drop" : ""}`}
      data-testid={`timeline-clip-${input.referenceId}`}
      data-reference-id={input.referenceId}
      aria-invalid={invalidDrop || undefined}
      style={{
        left: segment.timelineStart * pixelsPerSecond,
        overflow: selected ? "visible" : undefined,
        transform: dragging ? `translate3d(${moveOffsetX}px, 0, 0)` : undefined,
        width: clipWidth,
        zIndex: dragging ? 15 : selected ? 8 : undefined,
      }}
    >
      <button
        type="button"
        className="agent-editing-timeline-clip__surface"
        style={{ overflow: "hidden" }}
        aria-label={`Select ${label}`}
        aria-pressed={selected}
        onPointerDown={(event) => onStartMove(input.referenceId, event)}
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
      >
        <span className="agent-editing-timeline-clip__frames" aria-hidden="true">
          {hasFrame ? samples.map((sample) => (
            sample.url ? <img key={sample.sourceSeconds} src={sample.url} alt="" /> : null
          )) : <VideoIcon />}
        </span>
        <span className="agent-editing-timeline__clip-scrim" />
        <span className="agent-editing-timeline__clip-copy">
          <strong>{String(index + 1).padStart(2, "0")}</strong>
          <small>{seconds(segment.timelineEnd - segment.timelineStart)}</small>
        </span>
      </button>
      {selected ? renderHandle("start") : null}
      {selected ? renderHandle("end") : null}
    </div>
  );
}
