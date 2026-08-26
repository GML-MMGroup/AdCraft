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
  type WheelEvent as ReactWheelEvent,
} from "react";

import {
  clampPixelsPerSecond,
  fitPixelsPerSecond,
  pixelsToTime,
  timeToPixels,
} from "./editingTimelineMath.ts";

const TRACK_LABEL_WIDTH = 124;
const TIME_GUTTER_WIDTH = 18;
const MIN_ZOOM_LEVEL = 1;
const MAX_ZOOM_LEVEL = 8;
const ZOOM_STEP = 0.25;

export interface EditingTimelineViewportRenderState {
  pixelsPerSecond: number;
  visibleStartSeconds: number;
  visibleEndSeconds: number;
  contentWidth: number;
}

interface EditingTimelineViewportProps {
  children: (state: EditingTimelineViewportRenderState) => ReactNode;
  duration: number;
  playheadSeconds: number;
  onPlayheadChange: (seconds: number) => void;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function timeLabel(value: number): string {
  const totalSeconds = Math.max(0, Math.round(value));
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}:${String(totalSeconds % 60).padStart(2, "0")}`;
}

function tickInterval(pixelsPerSecond: number): number {
  const minimumSeconds = pixelsPerSecond > 0 ? 72 / pixelsPerSecond : 1;
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(1, minimumSeconds)));
  return [1, 2, 5, 10].map((factor) => factor * magnitude)
    .find((candidate) => candidate >= minimumSeconds) ?? 10 * magnitude;
}

export function EditingTimelineViewport({
  children,
  duration,
  onPlayheadChange,
  playheadSeconds,
}: EditingTimelineViewportProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const playheadDragCancelRef = useRef<(() => void) | null>(null);
  const zoomAnchorRef = useRef<number | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [zoomLevel, setZoomLevel] = useState(MIN_ZOOM_LEVEL);

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
  const pixelsPerSecond = clampPixelsPerSecond(
    fitScale * zoomLevel,
    {
      viewportWidth: timeViewportWidth,
      duration: safeDuration,
      max: fitScale * MAX_ZOOM_LEVEL,
    },
  );
  const contentWidth = Math.max(timeViewportWidth, timeToPixels(safeDuration, pixelsPerSecond));
  const timeScrollSurfaceWidth = TIME_GUTTER_WIDTH + contentWidth + TIME_GUTTER_WIDTH;
  const maxScrollLeft = Math.max(0, timeScrollSurfaceWidth - availableTrackWidth);

  const updateZoom = (nextLevel: number) => {
    const nextZoomLevel = clamp(nextLevel, MIN_ZOOM_LEVEL, MAX_ZOOM_LEVEL);
    if (nextZoomLevel === zoomLevel) return;
    if (safeDuration && pixelsPerSecond && timeViewportWidth) {
      zoomAnchorRef.current = clamp(
        pixelsToTime(scrollLeft + timeViewportWidth / 2, pixelsPerSecond),
        0,
        safeDuration,
      );
    }
    setZoomLevel(nextZoomLevel);
  };

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const anchorSeconds = zoomAnchorRef.current;
    if (!viewport || anchorSeconds === null || !pixelsPerSecond) return;

    const nextScrollLeft = clamp(
      timeToPixels(anchorSeconds, pixelsPerSecond) - timeViewportWidth / 2,
      0,
      maxScrollLeft,
    );
    viewport.scrollLeft = nextScrollLeft;
    setScrollLeft(nextScrollLeft);
    zoomAnchorRef.current = null;
  }, [maxScrollLeft, pixelsPerSecond, timeViewportWidth]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || scrollLeft <= maxScrollLeft) return;
    viewport.scrollLeft = maxScrollLeft;
    setScrollLeft(maxScrollLeft);
  }, [maxScrollLeft, scrollLeft]);

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
      updateZoom(zoomLevel + (delta < 0 ? ZOOM_STEP : -ZOOM_STEP));
      return;
    }

    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    const nextScrollLeft = clamp(scrollLeft + delta, 0, maxScrollLeft);
    if (nextScrollLeft === scrollLeft) return;
    event.preventDefault();
    viewport.scrollLeft = nextScrollLeft;
    setScrollLeft(nextScrollLeft);
  };

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
      onPlayheadChange(Math.max(0, playheadSeconds - 1));
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      onPlayheadChange(Math.min(safeDuration, playheadSeconds + 1));
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
    "--agent-editing-timeline-content-width": `${contentWidth}px`,
    "--agent-editing-timeline-time-gutter": `${TIME_GUTTER_WIDTH}px`,
    width: TRACK_LABEL_WIDTH + timeScrollSurfaceWidth,
  } as CSSProperties;

  return (
    <div className="agent-editing-timeline-viewport">
      <div className="agent-editing-timeline-viewport__toolbar" role="toolbar" aria-label="Timeline view controls">
        <button
          type="button"
          className="agent-editing-timeline-viewport__zoom-button"
          aria-label="Zoom out"
          title="Zoom out"
          disabled={zoomLevel <= MIN_ZOOM_LEVEL}
          onClick={() => updateZoom(zoomLevel - ZOOM_STEP)}
        >
          <span aria-hidden="true">−</span>
        </button>
        <input
          className="agent-editing-timeline-viewport__zoom-range"
          type="range"
          aria-label="Timeline zoom"
          min={MIN_ZOOM_LEVEL}
          max={MAX_ZOOM_LEVEL}
          step={ZOOM_STEP}
          value={zoomLevel}
          aria-valuetext={`${Math.round(zoomLevel * 100)}%`}
          onChange={(event) => updateZoom(Number(event.currentTarget.value))}
        />
        <span className="agent-editing-timeline-viewport__zoom-value" aria-live="polite">
          {Math.round(zoomLevel * 100)}%
        </span>
        <button
          type="button"
          className="agent-editing-timeline-viewport__zoom-button"
          aria-label="Fit timeline"
          title="Fit entire timeline"
          onClick={() => updateZoom(MIN_ZOOM_LEVEL)}
        >
          Fit
        </button>
        <button
          type="button"
          className="agent-editing-timeline-viewport__zoom-button"
          aria-label="Zoom in"
          title="Zoom in"
          disabled={zoomLevel >= MAX_ZOOM_LEVEL}
          onClick={() => updateZoom(zoomLevel + ZOOM_STEP)}
        >
          <span aria-hidden="true">+</span>
        </button>
      </div>
      <div
        ref={viewportRef}
        className="agent-editing-timeline-viewport__scroller"
        data-testid="timeline-scroll-viewport"
        onScroll={(event) => setScrollLeft(event.currentTarget.scrollLeft)}
        onWheel={onWheel}
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
              if (event.key === "ArrowLeft") onPlayheadChange(Math.max(0, playheadSeconds - 1));
              if (event.key === "ArrowRight") onPlayheadChange(Math.min(safeDuration, playheadSeconds + 1));
              if (event.key === "Home") onPlayheadChange(0);
              if (event.key === "End") onPlayheadChange(safeDuration);
            }}
          >
            <div className="agent-editing-timeline-viewport__ruler-label" aria-hidden="true">Time</div>
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
