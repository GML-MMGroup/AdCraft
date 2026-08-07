import type { Edge, ReactFlowInstance, Viewport } from "@xyflow/react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

import type { AgentCanvasFlowNode } from "./AgentCanvasNode.tsx";

type AgentCanvasFlowInstance = ReactFlowInstance<AgentCanvasFlowNode, Edge>;

interface UseAgentCanvasNodeFocusOptions {
  flowRef: RefObject<AgentCanvasFlowInstance | null>;
  scopeKey: string;
}

const OTHER_NODE_EXIT_DELAY_MS = 220;
export const AGENT_CANVAS_FOCUS_MAX_ZOOM = 4;

export function useAgentCanvasNodeFocus({
  flowRef,
  scopeKey,
}: UseAgentCanvasNodeFocusOptions) {
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const previousViewportRef = useRef<Viewport | null>(null);
  const exitTimerRef = useRef<number | null>(null);
  const fitFrameRef = useRef<number | null>(null);
  const scopeKeyRef = useRef(scopeKey);

  const cancelPendingExit = useCallback(() => {
    if (exitTimerRef.current !== null) {
      window.clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
  }, []);

  const cancelPendingFit = useCallback(() => {
    if (fitFrameRef.current !== null) {
      window.cancelAnimationFrame(fitFrameRef.current);
      fitFrameRef.current = null;
    }
  }, []);

  const exitFocus = useCallback(() => {
    cancelPendingExit();
    cancelPendingFit();
    const previousViewport = previousViewportRef.current;
    previousViewportRef.current = null;
    setFocusedNodeId(null);
    if (previousViewport && flowRef.current) {
      void flowRef.current.setViewport(previousViewport, { duration: 320 });
    }
  }, [cancelPendingExit, cancelPendingFit, flowRef]);

  const focusNode = useCallback((nodeId: string) => {
    const instance = flowRef.current;
    if (!instance) return;
    cancelPendingExit();
    cancelPendingFit();
    if (!previousViewportRef.current) {
      previousViewportRef.current = instance.getViewport();
    }
    setFocusedNodeId(nodeId);
    fitFrameRef.current = window.requestAnimationFrame(() => {
      fitFrameRef.current = null;
      void instance.fitView({
        nodes: [{ id: nodeId }],
        padding: 0.12,
        duration: 420,
        minZoom: 0.05,
        maxZoom: AGENT_CANVAS_FOCUS_MAX_ZOOM,
      });
    });
  }, [cancelPendingExit, cancelPendingFit, flowRef]);

  const scheduleExitForNodeSelection = useCallback((nodeId: string) => {
    cancelPendingExit();
    if (!focusedNodeId || focusedNodeId === nodeId) return;
    exitTimerRef.current = window.setTimeout(() => {
      exitTimerRef.current = null;
      exitFocus();
    }, OTHER_NODE_EXIT_DELAY_MS);
  }, [cancelPendingExit, exitFocus, focusedNodeId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && previousViewportRef.current) exitFocus();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [exitFocus]);

  useEffect(() => {
    if (scopeKeyRef.current === scopeKey) return;
    scopeKeyRef.current = scopeKey;
    cancelPendingExit();
    cancelPendingFit();
    previousViewportRef.current = null;
    setFocusedNodeId(null);
  }, [cancelPendingExit, cancelPendingFit, scopeKey]);

  useEffect(() => () => {
    cancelPendingExit();
    cancelPendingFit();
  }, [cancelPendingExit, cancelPendingFit]);

  return {
    focusedNodeId,
    focusNode,
    exitFocus,
    scheduleExitForNodeSelection,
  };
}
