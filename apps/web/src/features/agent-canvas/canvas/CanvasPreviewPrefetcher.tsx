import type { Viewport } from "@xyflow/react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  type RefObject,
} from "react";

import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";
import {
  createCanvasPreviewPrefetchScheduler,
  type CanvasPreviewCandidate,
  type CanvasPreviewPrefetchScheduler,
} from "./canvasPreviewPrefetch.ts";
import { canvasPreviewCandidates } from "./canvasPreviewPrefetchModel.ts";

export interface CanvasPreviewPrefetchHandle {
  setViewport(viewport: Viewport): void;
  setPaused(paused: boolean): void;
}

interface CanvasPreviewPrefetcherProps {
  nodes: readonly AgentCanvasFlowNode[];
  boardRef: RefObject<HTMLElement | null>;
}

export const CanvasPreviewPrefetcher = forwardRef<CanvasPreviewPrefetchHandle, CanvasPreviewPrefetcherProps>(
  function CanvasPreviewPrefetcher({ nodes, boardRef }, ref) {
    const schedulerRef = useRef<CanvasPreviewPrefetchScheduler | null>(null);
    const viewportRef = useRef<Viewport>({ x: 0, y: 0, zoom: 1 });
    const pausedRef = useRef(false);
    const frameRef = useRef<number | null>(null);
    const nodesRef = useRef(nodes);
    nodesRef.current = nodes;

    if (!schedulerRef.current) schedulerRef.current = createCanvasPreviewPrefetchScheduler();

    const schedule = useCallback(() => {
      if (frameRef.current !== null) return;
      const callback = () => {
        frameRef.current = null;
        const board = boardRef.current;
        if (!board) return;
        schedulerRef.current?.setPaused(pausedRef.current);
        schedulerRef.current?.update(canvasPreviewCandidates(
          nodesRef.current,
          viewportRef.current,
          board.clientWidth,
          board.clientHeight,
        ));
      };
      frameRef.current = typeof window !== "undefined" && window.requestAnimationFrame
        ? window.requestAnimationFrame(callback)
        : setTimeout(callback, 0) as unknown as number;
    }, [boardRef]);

    useImperativeHandle(ref, () => ({
      setViewport(viewport) {
        viewportRef.current = viewport;
        schedule();
      },
      setPaused(paused) {
        pausedRef.current = paused;
        schedule();
      },
    }), [schedule]);

    useEffect(() => {
      schedule();
      return () => {
        if (frameRef.current !== null) {
          if (typeof window !== "undefined" && window.cancelAnimationFrame) window.cancelAnimationFrame(frameRef.current);
          else clearTimeout(frameRef.current);
          frameRef.current = null;
        }
      };
    }, [nodes, schedule]);

    useEffect(() => () => schedulerRef.current?.dispose(), []);
    return null;
  },
);
