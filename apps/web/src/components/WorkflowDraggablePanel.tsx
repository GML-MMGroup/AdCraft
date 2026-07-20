import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { createDomTransformScheduler, translate3dTransform, writeElementTransform } from "../workflow/highFrequencyInteraction";

export type DraggablePanelKey = "run" | "detail" | "v2-slot-composer" | "v2-storyboard-prompt-composer";

export type PanelOffset = {
  x: number;
  y: number;
};

const PANEL_VIEWPORT_MARGIN = 8;

function clampPanelOffsetToViewport(
  panel: HTMLElement | null,
  requested: PanelOffset,
  applied: PanelOffset,
): PanelOffset {
  if (!panel || typeof window === "undefined") return requested;
  const rect = panel.getBoundingClientRect();
  const baseLeft = rect.left - applied.x;
  const baseTop = rect.top - applied.y;
  const minX = PANEL_VIEWPORT_MARGIN - baseLeft;
  const maxX = window.innerWidth - PANEL_VIEWPORT_MARGIN - baseLeft - rect.width;
  const minY = PANEL_VIEWPORT_MARGIN - baseTop;
  const maxY = window.innerHeight - PANEL_VIEWPORT_MARGIN - baseTop - rect.height;
  return {
    x: minX > maxX ? minX : Math.min(maxX, Math.max(minX, requested.x)),
    y: minY > maxY ? minY : Math.min(maxY, Math.max(minY, requested.y)),
  };
}

type PanelDragSession = {
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  nextOffset: PanelOffset;
};

type WorkflowDraggablePanelProps = {
  panelKey: DraggablePanelKey;
  offset: PanelOffset;
  className?: string;
  headingClassName?: string;
  heading: ReactNode;
  children: ReactNode;
  as?: "div" | "aside";
  style?: CSSProperties;
  onOffsetCommit: (panelKey: DraggablePanelKey, offset: PanelOffset) => void;
};

function joinClassNames(...items: Array<string | false | null | undefined>) {
  return items.filter(Boolean).join(" ");
}

export const WorkflowDraggablePanel = memo(function WorkflowDraggablePanel({
  panelKey,
  offset,
  className,
  headingClassName,
  heading,
  children,
  as = "div",
  style,
  onOffsetCommit,
}: WorkflowDraggablePanelProps) {
  const panelRef = useRef<HTMLElement | null>(null);
  const dragSessionRef = useRef<PanelDragSession | null>(null);
  const committedOffsetRef = useRef(offset);
  const latestTransformOffsetRef = useRef(offset);
  const [isDragging, setIsDragging] = useState(false);
  const Element = as;
  const transformScheduler = useMemo(
    () =>
      createDomTransformScheduler({
        getElement: () => panelRef.current,
        getOffset: () => latestTransformOffsetRef.current,
      }),
    [],
  );

  useLayoutEffect(() => {
    const clamped = clampPanelOffsetToViewport(panelRef.current, offset, offset);
    committedOffsetRef.current = clamped;
    latestTransformOffsetRef.current = clamped;
    if (!dragSessionRef.current) {
      writeElementTransform(panelRef.current, clamped);
    }
    if (clamped.x !== offset.x || clamped.y !== offset.y) onOffsetCommit(panelKey, clamped);
  }, [offset, onOffsetCommit, panelKey]);

  useEffect(() => {
    const clampOnResize = () => {
      if (dragSessionRef.current) return;
      const current = committedOffsetRef.current;
      const clamped = clampPanelOffsetToViewport(panelRef.current, current, latestTransformOffsetRef.current);
      if (clamped.x === current.x && clamped.y === current.y) return;
      committedOffsetRef.current = clamped;
      latestTransformOffsetRef.current = clamped;
      writeElementTransform(panelRef.current, clamped);
      onOffsetCommit(panelKey, clamped);
    };
    window.addEventListener("resize", clampOnResize);
    return () => window.removeEventListener("resize", clampOnResize);
  }, [onOffsetCommit, panelKey]);

  useEffect(() => {
    return () => transformScheduler.cancel();
  }, [transformScheduler]);

  const setPanelElement = useCallback((element: HTMLElement | null) => {
    panelRef.current = element;
  }, []);

  const finishDrag = useCallback(
    (event: PointerEvent<HTMLElement>) => {
      const session = dragSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) return;

      const finalOffset = session.nextOffset;
      transformScheduler.cancel();
      dragSessionRef.current = null;
      committedOffsetRef.current = finalOffset;
      latestTransformOffsetRef.current = finalOffset;
      const panel = panelRef.current;
      if (panel?.hasPointerCapture?.(event.pointerId)) {
        panel.releasePointerCapture(event.pointerId);
      }
      writeElementTransform(panel, finalOffset);
      setIsDragging(false);
      onOffsetCommit(panelKey, finalOffset);
    },
    [onOffsetCommit, panelKey, transformScheduler],
  );

  const handlePointerDown = useCallback(
    (event: PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest("button, input, textarea, select, a")) return;
      event.preventDefault();
      const origin = committedOffsetRef.current;
      dragSessionRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originX: origin.x,
        originY: origin.y,
        nextOffset: origin,
      };
      panelRef.current?.setPointerCapture?.(event.pointerId);
      setIsDragging(true);
    },
    [],
  );

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLElement>) => {
      const session = dragSessionRef.current;
      if (!session || session.pointerId !== event.pointerId) return;
      const requested = {
        x: session.originX + event.clientX - session.startX,
        y: session.originY + event.clientY - session.startY,
      };
      session.nextOffset = clampPanelOffsetToViewport(
        panelRef.current,
        requested,
        latestTransformOffsetRef.current,
      );
      latestTransformOffsetRef.current = session.nextOffset;
      transformScheduler.schedule();
    },
    [transformScheduler],
  );

  return (
    <Element
      ref={setPanelElement}
      className={joinClassNames(className, "draggable-panel", isDragging && "is-dragging")}
      data-panel-key={panelKey}
      style={{ ...style, transform: translate3dTransform(offset) }}
      onPointerMove={handlePointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      <div className={joinClassNames("panel-heading", "draggable-panel-heading", headingClassName)} onPointerDown={handlePointerDown}>
        {heading}
      </div>
      {children}
    </Element>
  );
});
