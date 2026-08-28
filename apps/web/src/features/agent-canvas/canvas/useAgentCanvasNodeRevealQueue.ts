import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { ReactFlowInstance } from "@xyflow/react";

import type { ProgressiveNodePlacementPlan } from "./agentCanvasProgressivePlacement.ts";

export interface AgentCanvasNodeRevealQueueOptions {
  workflowId: string | null;
  flowRef: { current: Pick<ReactFlowInstance, "getNodes"> | null };
  onFocusNode: (nodeId: string) => void;
  reducedMotion?: boolean;
}

export interface AgentCanvasNodeRevealQueue {
  enqueue: (plan: ProgressiveNodePlacementPlan) => void;
  reserveNodeIds: (nodeIds: readonly string[]) => void;
  syncCanonicalNodeIds: (nodeIds: readonly string[]) => void;
  releaseNodeIds: (nodeIds: readonly string[]) => void;
  interrupt: () => void;
  reset: () => void;
  visibleNodeIds: ReadonlySet<string>;
  pendingNodeIds: readonly string[];
  activeNodeId: string | null;
}

export function useAgentCanvasNodeRevealQueue({
  workflowId,
  flowRef,
  onFocusNode,
  reducedMotion = false,
}: AgentCanvasNodeRevealQueueOptions): AgentCanvasNodeRevealQueue {
  const [visibleNodeIds, setVisibleNodeIds] = useState<ReadonlySet<string>>(() => new Set());
  const [pendingNodeIds, setPendingNodeIds] = useState<readonly string[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const workflowIdRef = useRef(workflowId);
  const canonicalNodeIdsRef = useRef<ReadonlySet<string>>(new Set());
  const visibleNodeIdsRef = useRef<ReadonlySet<string>>(new Set());
  const reservedNodeIdsRef = useRef(new Set<string>());
  const queuedNodeIdsRef = useRef<string[]>([]);
  const activeNodeIdRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const mountRetryTimerRef = useRef<number | null>(null);
  const completionTimerRef = useRef<number | null>(null);
  const pumpRef = useRef<() => void>(() => undefined);

  const clearTimers = useCallback(() => {
    if (mountRetryTimerRef.current !== null) {
      window.clearTimeout(mountRetryTimerRef.current);
      mountRetryTimerRef.current = null;
    }
    if (completionTimerRef.current !== null) {
      window.clearTimeout(completionTimerRef.current);
      completionTimerRef.current = null;
    }
  }, []);

  const updateVisibleNodeIds = useCallback((next: ReadonlySet<string>) => {
    visibleNodeIdsRef.current = next;
    setVisibleNodeIds(next);
  }, []);

  const updatePendingNodeIds = useCallback((next: readonly string[]) => {
    setPendingNodeIds(next);
  }, []);

  const completeActiveNode = useCallback(() => {
    activeNodeIdRef.current = null;
    setActiveNodeId(null);
    completionTimerRef.current = null;
    updatePendingNodeIds(queuedNodeIdsRef.current);
    pumpRef.current();
  }, [updatePendingNodeIds]);

  const focusWhenMounted = useCallback((nodeId: string, generation: number) => {
    const mounted = flowRef.current?.getNodes().some((node) => node.id === nodeId) ?? false;
    if (generation !== generationRef.current || activeNodeIdRef.current !== nodeId) return;
    if (!mounted) {
      mountRetryTimerRef.current = window.setTimeout(() => {
        mountRetryTimerRef.current = null;
        focusWhenMounted(nodeId, generation);
      }, 16);
      return;
    }
    onFocusNode(nodeId);
    completionTimerRef.current = window.setTimeout(
      completeActiveNode,
      reducedMotion ? 0 : 420,
    );
  }, [completeActiveNode, flowRef, onFocusNode, reducedMotion]);

  const pump = useCallback(() => {
    if (activeNodeIdRef.current || !canonicalNodeIdsRef.current.size) return;
    const nextIndex = queuedNodeIdsRef.current.findIndex((nodeId) => (
      canonicalNodeIdsRef.current.has(nodeId)
    ));
    if (nextIndex < 0) return;
    const [nodeId] = queuedNodeIdsRef.current.splice(nextIndex, 1);
    if (!nodeId) return;
    reservedNodeIdsRef.current.delete(nodeId);
    activeNodeIdRef.current = nodeId;
    setActiveNodeId(nodeId);
    updatePendingNodeIds(queuedNodeIdsRef.current);
    const nextVisible = new Set(visibleNodeIdsRef.current);
    nextVisible.add(nodeId);
    updateVisibleNodeIds(nextVisible);
    const generation = generationRef.current;
    window.requestAnimationFrame(() => focusWhenMounted(nodeId, generation));
  }, [focusWhenMounted, updatePendingNodeIds, updateVisibleNodeIds]);
  pumpRef.current = pump;

  const reset = useCallback(() => {
    generationRef.current += 1;
    clearTimers();
    canonicalNodeIdsRef.current = new Set();
    reservedNodeIdsRef.current.clear();
    queuedNodeIdsRef.current = [];
    activeNodeIdRef.current = null;
    setActiveNodeId(null);
    updateVisibleNodeIds(new Set());
    updatePendingNodeIds([]);
  }, [clearTimers, updatePendingNodeIds, updateVisibleNodeIds]);

  useLayoutEffect(() => {
    if (workflowIdRef.current === workflowId) return;
    workflowIdRef.current = workflowId;
    reset();
  }, [reset, workflowId]);

  useLayoutEffect(() => () => {
    generationRef.current += 1;
    clearTimers();
  }, [clearTimers]);

  const reserveNodeIds = useCallback((nodeIds: readonly string[]) => {
    nodeIds.forEach((nodeId) => {
      if (!visibleNodeIdsRef.current.has(nodeId)) reservedNodeIdsRef.current.add(nodeId);
    });
  }, []);

  const releaseNodeIds = useCallback((nodeIds: readonly string[]) => {
    nodeIds.forEach((nodeId) => reservedNodeIdsRef.current.delete(nodeId));
  }, []);

  const syncCanonicalNodeIds = useCallback((nodeIds: readonly string[]) => {
    const canonical = new Set(nodeIds);
    canonicalNodeIdsRef.current = canonical;
    if (activeNodeIdRef.current && !canonical.has(activeNodeIdRef.current)) {
      clearTimers();
      activeNodeIdRef.current = null;
      setActiveNodeId(null);
    }
    const nextVisible = new Set(visibleNodeIdsRef.current);
    canonical.forEach((nodeId) => {
      if (
        !reservedNodeIdsRef.current.has(nodeId)
        && !queuedNodeIdsRef.current.includes(nodeId)
        && activeNodeIdRef.current !== nodeId
      ) {
        nextVisible.add(nodeId);
      }
    });
    updateVisibleNodeIds(nextVisible);
    updatePendingNodeIds(queuedNodeIdsRef.current);
    pump();
  }, [clearTimers, pump, updatePendingNodeIds, updateVisibleNodeIds]);

  const enqueue = useCallback((plan: ProgressiveNodePlacementPlan) => {
    const queued = new Set(queuedNodeIdsRef.current);
    const visible = visibleNodeIdsRef.current;
    plan.orderedNodeIds.forEach((nodeId) => {
      if (visible.has(nodeId) || queued.has(nodeId) || activeNodeIdRef.current === nodeId) return;
      queuedNodeIdsRef.current.push(nodeId);
      queued.add(nodeId);
    });
    updatePendingNodeIds(queuedNodeIdsRef.current);
    pump();
  }, [pump, updatePendingNodeIds]);

  const interrupt = useCallback(() => {
    generationRef.current += 1;
    clearTimers();
    queuedNodeIdsRef.current = [];
    reservedNodeIdsRef.current.clear();
    activeNodeIdRef.current = null;
    setActiveNodeId(null);
    const nextVisible = new Set(visibleNodeIdsRef.current);
    canonicalNodeIdsRef.current.forEach((nodeId) => nextVisible.add(nodeId));
    updateVisibleNodeIds(nextVisible);
    updatePendingNodeIds([]);
  }, [clearTimers, updatePendingNodeIds, updateVisibleNodeIds]);

  return {
    enqueue,
    reserveNodeIds,
    syncCanonicalNodeIds,
    releaseNodeIds,
    interrupt,
    reset,
    visibleNodeIds,
    pendingNodeIds,
    activeNodeId,
  };
}
