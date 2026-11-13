import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import {
  fitPixelsPerSecond,
  pixelsToTime,
  timeToPixels,
} from "./editingTimelineMath.ts";

import { frameTime } from "./editingManualActions.ts";
import { useEditingText } from "./editingMessages.ts";

const TRACK_LABEL_WIDTH = 124;
const TIME_GUTTER_WIDTH = 18;

export interface EditingTimelineViewportRenderState {
  pixelsPerSecond: number;
  visibleStartSeconds: number;
  visibleEndSeconds: number;
  contentWidth: number;
}

interface EditingTimelineViewportProps {
  children: (state: EditingTimelineViewportRenderState) => ReactNode;
  duration: number;
  zoom?: number;
  fps?: number;
  playing?: boolean;
  playheadSeconds: number;
  onPlayheadChange: (seconds: number) => void;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function timeLabel(value: number): string {
  const totalSeconds = Math.max(0, Math.floor(value));
  const minutes = Math.floor(totalSeconds / 60);
  const fraction = value % 1 > .001 ? (value % 1).toFixed(2).slice(1) : "";
  return `${minutes}:${String(totalSeconds % 60).padStart(2, "0")}${fraction}`;
}

function tickInterval(pixelsPerSecond: number): number {
  const minimumSeconds = pixelsPerSecond > 0 ? 72 / pixelsPerSecond : 1;
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(.001, minimumSeconds)));
  return [1, 2, 5, 10].map((factor) => factor * magnitude)
    .find((candidate) => candidate >= minimumSeconds) ?? 10 * magnitude;
}

export function EditingTimelineViewport({
  children,
  duration,
  zoom = 1,
  fps = 30,
  playing = false,
  onPlayheadChange,
  playheadSeconds,
}: EditingTimelineViewportProps) {
  const t = useEditingText();
  const previousScaleRef = useRef(0);
  const viewportRef = useRef<HTMLDivElement>(null);
  const playheadDragCancelRef = useRef<(() => void) | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const measure = () => setViewportWidth(Math.max(0, viewport.clientWidth || viewport.getBoundingClientRect().width));
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  const safeDuration = Math.max(0, duration);
  const availableTrackWidth = Math.max(0, viewportWidth - TRACK_LABEL_WIDTH);
  const timeViewportWidth = Math.max(1, availableTrackWidth - 2 * TIME_GUTTER_WIDTH);
  const timeOrigin = TRACK_LABEL_WIDTH + TIME_GUTTER_WIDTH;
  const fitScale = fitPixelsPerSecond(timeViewportWidth, safeDuration);
  const pixelsPerSecond = fitScale * Math.max(1, Math.min(16, zoom));
  const contentWidth = Math.max(timeViewportWidth, timeToPixels(safeDuration, pixelsPerSecond));
  const timeScrollSurfaceWidth = TIME_GUTTER_WIDTH + contentWidth + TIME_GUTTER_WIDTH;
  const maxScrollLeft = Math.max(0, timeScrollSurfaceWidth - availableTrackWidth);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const previousScale = previousScaleRef.current;
    previousScaleRef.current = pixelsPerSecond;
    let next = viewport.scrollLeft;
    if (previousScale > 0 && previousScale !== pixelsPerSecond) {
      const anchor = Math.max(0, Math.min(timeViewportWidth, playheadSeconds * previousScale - next));
      next = playheadSeconds * pixelsPerSecond - anchor;
    } else if (playing) {
      const position = playheadSeconds * pixelsPerSecond;
      if (position < next || position > next + timeViewportWidth) next = position - timeViewportWidth * .2;
    }
    next = clamp(next, 0, maxScrollLeft);
    if (Math.abs(viewport.scrollLeft - next) > .5) {
      viewport.scrollLeft = next;
      setScrollLeft(next);
    }
  }, [maxScrollLeft, pixelsPerSecond, playheadSeconds, playing, timeViewportWidth]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      const next = clamp(viewport.scrollLeft + delta, 0, maxScrollLeft);
      if (next === viewport.scrollLeft) return;
      event.preventDefault();
      viewport.scrollLeft = next;
    };
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, [maxScrollLeft]);

  const updatePlayheadFromClientX = (clientX: number) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const bounds = viewport.getBoundingClientRect();
    const timelinePixels = viewport.scrollLeft + clientX - bounds.left - timeOrigin;
    onPlayheadChange(clamp(pixelsToTime(timelinePixels, pixelsPerSecond), 0, safeDuration));
  };

  const startPlayheadDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !safeDuration || !pixelsPerSecond) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.currentTarget;
    const pointerId = event.pointerId;
    target.setPointerCapture?.(pointerId);
    let finished = false;

    const cleanup = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      if (target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
      if (playheadDragCancelRef.current === cancel) playheadDragCancelRef.current = null;
    };
    const finish = () => {
      if (finished) return;
      finished = true;
      cleanup();
    };
    const onPointerMove = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== pointerId || finished) return;
      updatePlayheadFromClientX(pointerEvent.clientX);
    };
    const onPointerUp = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId !== pointerId) return;
      updatePlayheadFromClientX(pointerEvent.clientX);
      finish();
    };
    const onPointerCancel = (pointerEvent: PointerEvent) => {
      if (pointerEvent.pointerId === pointerId) finish();
    };
    function cancel() {
      finish();
    }

    playheadDragCancelRef.current?.();
    playheadDragCancelRef.current = cancel;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
    updatePlayheadFromClientX(event.clientX);
  };

  useEffect(() => () => playheadDragCancelRef.current?.(), []);

  const onPlayheadKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      onPlayheadChange(Math.max(0, playheadSeconds - 1 / fps));
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      onPlayheadChange(Math.min(safeDuration, playheadSeconds + 1 / fps));
    }
    if (event.key === "Home") {
      event.preventDefault();
      onPlayheadChange(0);
    }
    if (event.key === "End") {
      event.preventDefault();
      onPlayheadChange(safeDuration);
    }
  };

  const seekFromClientX = (clientX: number, bounds: DOMRect) => {
    const viewport = viewportRef.current;
    const timelinePixels = (viewport?.scrollLeft ?? 0) + clientX - bounds.left - timeOrigin;
    onPlayheadChange(clamp(pixelsToTime(timelinePixels, pixelsPerSecond), 0, safeDuration));
  };

  const ticks = useMemo(() => {
    if (!safeDuration) return [0];
    const interval = tickInterval(pixelsPerSecond);
    const count = Math.ceil(safeDuration / interval);
    return Array.from({ length: count + 1 }, (_, index) => Math.min(safeDuration, index * interval))
      .filter((value, index, values) => index === 0 || value !== values[index - 1]);
  }, [pixelsPerSecond, safeDuration]);

  const state: EditingTimelineViewportRenderState = {
    pixelsPerSecond,
    visibleStartSeconds: pixelsToTime(Math.max(0, scrollLeft - TIME_GUTTER_WIDTH), pixelsPerSecond),
    visibleEndSeconds: Math.min(
      safeDuration,
      pixelsToTime(
        Math.max(0, scrollLeft + viewportWidth - timeOrigin),
        pixelsPerSecond,
      ),
    ),
    contentWidth,
  };

  const contentStyle = {
    "--editing-major-tick-width": `${tickInterval(pixelsPerSecond) * pixelsPerSecond}px`,
    "--editing-minor-tick-width": `${tickInterval(pixelsPerSecond) * pixelsPerSecond / 5}px`,
    "--agent-editing-timeline-content-width": `${contentWidth}px`,
    "--agent-editing-timeline-time-gutter": `${TIME_GUTTER_WIDTH}px`,
    width: TRACK_LABEL_WIDTH + timeScrollSurfaceWidth,
  } as CSSProperties;

  return (
    <div className="agent-editing-timeline-viewport">
      <div
        ref={viewportRef}
        className="agent-editing-timeline-viewport__scroller"
        data-testid="timeline-scroll-viewport"
        onScroll={(event) => setScrollLeft(event.currentTarget.scrollLeft)}
      >
        <div className="agent-editing-timeline-viewport__content" style={contentStyle}>
          <div
            className="agent-editing-timeline-viewport__ruler-row"
            data-testid="timeline-ruler"
            role="slider"
            tabIndex={0}
            aria-label="Seek timeline ruler"
            aria-valuemin={0}
            aria-valuemax={safeDuration}
            aria-valuenow={playheadSeconds}
            onClick={(event) => seekFromClientX(event.clientX, event.currentTarget.getBoundingClientRect())}
            onKeyDown={(event) => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) event.preventDefault();
              if (event.key === "ArrowLeft") onPlayheadChange(Math.max(0, playheadSeconds - 1 / fps));
              if (event.key === "ArrowRight") onPlayheadChange(Math.min(safeDuration, playheadSeconds + 1 / fps));
              if (event.key === "Home") onPlayheadChange(0);
              if (event.key === "End") onPlayheadChange(safeDuration);
            }}
          >
            <div className="agent-editing-timeline-viewport__ruler-label" aria-hidden="true">
              <strong>{frameTime(playheadSeconds, fps)}</strong>
              <small>{fps} FPS · {t("Time")}</small>
            </div>
            <div className="agent-editing-timeline-viewport__ruler" style={{ width: contentWidth }} aria-hidden="true">
              {ticks.map((tick) => (
                <span key={tick} style={{ left: timeToPixels(tick, pixelsPerSecond) }}>
                  {timeLabel(tick)}
                </span>
              ))}
            </div>
          </div>
          <div
            className="agent-editing-timeline-viewport__playhead"
            style={{
              left: timeOrigin + timeToPixels(clamp(playheadSeconds, 0, safeDuration), pixelsPerSecond),
              zIndex: 20,
            }}
            role="slider"
            tabIndex={safeDuration ? 0 : -1}
            aria-label="Timeline playhead"
            aria-valuemin={0}
            aria-valuemax={safeDuration}
            aria-valuenow={clamp(playheadSeconds, 0, safeDuration)}
            onKeyDown={onPlayheadKeyDown}
            onPointerDown={startPlayheadDrag}
          />
          {children(state)}
        </div>
      </div>
    </div>
  );
}
