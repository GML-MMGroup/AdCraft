import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
} from "react";

import { FitIcon, PlusIcon } from "../../../icons.tsx";
import {
  clampPixelsPerSecond,
  fitPixelsPerSecond,
  pixelsToTime,
  timeToPixels,
} from "./editingTimelineMath.ts";

const TRACK_LABEL_WIDTH = 124;
const MAX_PIXELS_PER_SECOND = 240;
const BUTTON_ZOOM_FACTOR = 1.25;
const WHEEL_ZOOM_FACTOR = 1.12;

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
  const pendingAnchorRef = useRef<number | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [zoomScale, setZoomScale] = useState(1);

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
  const availableWidth = Math.max(1, viewportWidth - TRACK_LABEL_WIDTH);
  const fit = fitPixelsPerSecond(availableWidth, safeDuration);
  const pixelsPerSecond = clampPixelsPerSecond(fit * zoomScale, {
    viewportWidth: availableWidth,
    duration: safeDuration,
    max: MAX_PIXELS_PER_SECOND,
  });
  const maximumPixelsPerSecond = Math.max(fit, MAX_PIXELS_PER_SECOND);
  const contentWidth = Math.max(availableWidth, timeToPixels(safeDuration, pixelsPerSecond));
  const maxScrollLeft = Math.max(0, contentWidth - availableWidth);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || pendingAnchorRef.current === null) return;
    const nextScrollLeft = clamp(pendingAnchorRef.current, 0, maxScrollLeft);
    pendingAnchorRef.current = null;
    viewport.scrollLeft = nextScrollLeft;
    setScrollLeft(nextScrollLeft);
  }, [maxScrollLeft, pixelsPerSecond]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || scrollLeft <= maxScrollLeft) return;
    viewport.scrollLeft = maxScrollLeft;
    setScrollLeft(maxScrollLeft);
  }, [maxScrollLeft, scrollLeft]);

  const setPixelsPerSecond = useCallback((value: number) => {
    const clamped = clampPixelsPerSecond(value, {
      viewportWidth: availableWidth,
      duration: safeDuration,
      max: MAX_PIXELS_PER_SECOND,
    });
    setZoomScale(fit > 0 ? clamped / fit : 1);
  }, [availableWidth, fit, safeDuration]);

  const fitTimeline = useCallback(() => {
    pendingAnchorRef.current = 0;
    setZoomScale(1);
  }, []);

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    if (event.ctrlKey || event.metaKey) {
      if (!safeDuration || event.deltaY === 0) return;
      const factor = event.deltaY < 0 ? WHEEL_ZOOM_FACTOR : 1 / WHEEL_ZOOM_FACTOR;
      const nextPixelsPerSecond = clampPixelsPerSecond(pixelsPerSecond * factor, {
        viewportWidth: availableWidth,
        duration: safeDuration,
        max: MAX_PIXELS_PER_SECOND,
      });
      if (nextPixelsPerSecond === pixelsPerSecond) return;

      const rect = viewport.getBoundingClientRect();
      const pointerOffset = clamp(event.clientX - rect.left - TRACK_LABEL_WIDTH, 0, availableWidth);
      const anchorSeconds = pixelsToTime(scrollLeft + pointerOffset, pixelsPerSecond);
      pendingAnchorRef.current = timeToPixels(anchorSeconds, nextPixelsPerSecond) - pointerOffset;
      event.preventDefault();
      setPixelsPerSecond(nextPixelsPerSecond);
      return;
    }

    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    const nextScrollLeft = clamp(scrollLeft + delta, 0, maxScrollLeft);
    if (nextScrollLeft === scrollLeft) return;
    event.preventDefault();
    viewport.scrollLeft = nextScrollLeft;
    setScrollLeft(nextScrollLeft);
  };

  const seekFromClientX = (clientX: number, bounds: DOMRect) => {
    const timelinePixels = scrollLeft + clientX - bounds.left - TRACK_LABEL_WIDTH;
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
    visibleStartSeconds: pixelsToTime(scrollLeft, pixelsPerSecond),
    visibleEndSeconds: Math.min(safeDuration, pixelsToTime(scrollLeft + availableWidth, pixelsPerSecond)),
    contentWidth,
  };

  return (
    <div className="agent-editing-timeline-viewport">
      <div className="agent-editing-timeline-viewport__toolbar" role="toolbar" aria-label="Timeline zoom controls">
        <button type="button" aria-label="Zoom out" title="Zoom out" disabled={pixelsPerSecond <= fit} onClick={() => setPixelsPerSecond(pixelsPerSecond / BUTTON_ZOOM_FACTOR)}>
          <span aria-hidden="true">-</span>
        </button>
        <input
          type="range"
          min={fit}
          max={maximumPixelsPerSecond}
          step={Math.max(0.01, (maximumPixelsPerSecond - fit) / 100)}
          value={pixelsPerSecond}
          aria-label="Timeline zoom"
          onChange={(event) => setPixelsPerSecond(Number(event.currentTarget.value))}
        />
        <button type="button" aria-label="Zoom in" title="Zoom in" disabled={pixelsPerSecond >= maximumPixelsPerSecond} onClick={() => setPixelsPerSecond(pixelsPerSecond * BUTTON_ZOOM_FACTOR)}>
          <PlusIcon />
        </button>
        <button type="button" aria-label="Fit timeline" title="Fit timeline" onClick={fitTimeline}>
          <FitIcon />
        </button>
        <output aria-label="Timeline zoom level">{Math.round((fit > 0 ? pixelsPerSecond / fit : 1) * 100)}%</output>
      </div>

      <div
        ref={viewportRef}
        className="agent-editing-timeline-viewport__scroller"
        data-testid="timeline-scroll-viewport"
        onScroll={(event) => setScrollLeft(event.currentTarget.scrollLeft)}
        onWheel={onWheel}
      >
        <div className="agent-editing-timeline-viewport__content" style={{ width: TRACK_LABEL_WIDTH + contentWidth }}>
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
            onDoubleClick={fitTimeline}
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
            style={{ left: TRACK_LABEL_WIDTH + timeToPixels(clamp(playheadSeconds, 0, safeDuration), pixelsPerSecond) }}
            aria-hidden="true"
          />
          {children(state)}
        </div>
      </div>

      <input
        className="agent-editing-timeline__scrubber"
        type="range"
        min="0"
        max={safeDuration}
        step="0.01"
        value={clamp(playheadSeconds, 0, safeDuration)}
        aria-label="Timeline playhead"
        onChange={(event) => onPlayheadChange(Number(event.currentTarget.value))}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            onPlayheadChange(Math.max(0, playheadSeconds - 1));
          }
          if (event.key === "ArrowRight") {
            event.preventDefault();
            onPlayheadChange(Math.min(safeDuration, playheadSeconds + 1));
          }
        }}
      />
    </div>
  );
}
