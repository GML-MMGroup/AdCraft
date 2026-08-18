import type { Viewport } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  CanvasLayoutPositionV2,
  CanvasPositionV2,
} from "../../../types-v2.ts";

export type AgentCanvasLayoutPreviewStatus =
  | "idle"
  | "previewing"
  | "saving"
  | "save_error";

export interface AgentCanvasLayoutPreviewStart<TNode> {
  workflowId: string;
  nodes: readonly TNode[];
  targetPositions: CanvasLayoutPositionV2[];
  viewport: Viewport;
}

type PreviewSnapshot = {
  transactionId: number;
  workflowId: string;
  originalPositions: CanvasLayoutPositionV2[];
  targetPositions: CanvasLayoutPositionV2[];
  originalViewport: Viewport;
  persistenceStarted: boolean;
};

function previewErrorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Unable to save the canvas layout.";
}

export function overlayAgentCanvasLayoutPreview<TNode extends {
  id: string;
  position: CanvasPositionV2;
}>(
  nodes: readonly TNode[],
  positions: readonly CanvasLayoutPositionV2[],
): TNode[] {
  const positionsByNodeId = new Map(positions.map((position) => [position.node_id, position]));
  return nodes.map((node) => {
    const position = positionsByNodeId.get(node.id);
    return position ? { ...node, position: { x: position.x, y: position.y } } : node;
  });
}

export function useAgentCanvasLayoutPreview<TNode extends {
  id: string;
  position: CanvasPositionV2;
}>({
  workflowId,
  persistPositions,
  restoreViewport,
  rollbackPositions,
}: {
  workflowId: string;
  persistPositions: (positions: CanvasLayoutPositionV2[]) => Promise<void>;
  restoreViewport: (viewport: Viewport, workflowId: string) => Promise<unknown> | unknown;
  rollbackPositions?: (
    workflowId: string,
    positions: CanvasLayoutPositionV2[],
  ) => Promise<unknown> | unknown;
}): {
  status: AgentCanvasLayoutPreviewStatus;
  error: string | null;
  active: boolean;
  positions: CanvasLayoutPositionV2[];
  begin: (preview: AgentCanvasLayoutPreviewStart<TNode>) => void;
  cancel: () => void;
  keep: () => Promise<boolean>;
  overlay: (nodes: readonly TNode[]) => TNode[];
} {
  const [snapshot, setSnapshot] = useState<PreviewSnapshot | null>(null);
  const [status, setStatus] = useState<AgentCanvasLayoutPreviewStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const workflowIdRef = useRef(workflowId);
  const snapshotRef = useRef<PreviewSnapshot | null>(null);
  const nextTransactionIdRef = useRef(0);
  const savingTransactionIdRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const restoreViewportRef = useRef(restoreViewport);
  const rollbackPositionsRef = useRef(rollbackPositions);

  workflowIdRef.current = workflowId;
  restoreViewportRef.current = restoreViewport;
  rollbackPositionsRef.current = rollbackPositions;

  const restoreSnapshot = useCallback((currentSnapshot: PreviewSnapshot) => {
    if (currentSnapshot.persistenceStarted) {
      void Promise.resolve(rollbackPositionsRef.current?.(
        currentSnapshot.workflowId,
        currentSnapshot.originalPositions,
      )).catch(() => undefined);
    }
    void Promise.resolve(restoreViewportRef.current(
      currentSnapshot.originalViewport,
      currentSnapshot.workflowId,
    )).catch(() => undefined);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const currentSnapshot = snapshotRef.current;
      if (currentSnapshot) {
        snapshotRef.current = null;
        savingTransactionIdRef.current = null;
        restoreSnapshot(currentSnapshot);
      }
    };
  }, [restoreSnapshot]);

  useEffect(() => {
    if (!snapshot || snapshot.workflowId === workflowId) return;
    if (snapshotRef.current?.transactionId !== snapshot.transactionId) return;
    restoreSnapshot(snapshot);
    snapshotRef.current = null;
    savingTransactionIdRef.current = null;
    setSnapshot(null);
    setStatus("idle");
    setError(null);
  }, [restoreSnapshot, snapshot, workflowId]);

  const active = snapshot?.workflowId === workflowId;
  const positions = useMemo(() => active ? snapshot?.targetPositions ?? [] : [], [active, snapshot]);

  const begin = useCallback((preview: AgentCanvasLayoutPreviewStart<TNode>) => {
    if (snapshotRef.current || preview.workflowId !== workflowId) return;
    const nextSnapshot = {
      transactionId: nextTransactionIdRef.current + 1,
      workflowId: preview.workflowId,
      originalPositions: preview.nodes.map((node) => ({
        node_id: node.id,
        x: node.position.x,
        y: node.position.y,
      })),
      targetPositions: preview.targetPositions.map((position) => ({ ...position })),
      originalViewport: { ...preview.viewport },
      persistenceStarted: false,
    };
    nextTransactionIdRef.current = nextSnapshot.transactionId;
    snapshotRef.current = nextSnapshot;
    savingTransactionIdRef.current = null;
    setSnapshot(nextSnapshot);
    setStatus("previewing");
    setError(null);
  }, [workflowId]);

  const cancel = useCallback(() => {
    const currentSnapshot = snapshotRef.current;
    if (!currentSnapshot) return;
    snapshotRef.current = null;
    if (savingTransactionIdRef.current === currentSnapshot.transactionId) {
      savingTransactionIdRef.current = null;
    }
    restoreSnapshot(currentSnapshot);
    setSnapshot(null);
    setStatus("idle");
    setError(null);
  }, [restoreSnapshot]);

  const keep = useCallback(async () => {
    const currentSnapshot = snapshotRef.current;
    if (
      !currentSnapshot
      || currentSnapshot.workflowId !== workflowId
      || savingTransactionIdRef.current !== null
    ) return false;

    const transactionId = currentSnapshot.transactionId;
    currentSnapshot.persistenceStarted = true;
    savingTransactionIdRef.current = transactionId;
    setStatus("saving");
    setError(null);
    try {
      await persistPositions(currentSnapshot.targetPositions);
      if (
        !mountedRef.current
        || workflowIdRef.current !== currentSnapshot.workflowId
        || snapshotRef.current?.transactionId !== transactionId
      ) return false;
      snapshotRef.current = null;
      savingTransactionIdRef.current = null;
      setSnapshot(null);
      setStatus("idle");
      return true;
    } catch (saveError) {
      if (
        !mountedRef.current
        || workflowIdRef.current !== currentSnapshot.workflowId
        || snapshotRef.current?.transactionId !== transactionId
      ) return false;
      savingTransactionIdRef.current = null;
      setStatus("save_error");
      setError(previewErrorMessage(saveError));
      return false;
    }
  }, [persistPositions, workflowId]);

  const overlay = useCallback((nodes: readonly TNode[]) => (
    overlayAgentCanvasLayoutPreview(nodes, positions)
  ), [positions]);

  return {
    status,
    error,
    active,
    positions,
    begin,
    cancel,
    keep,
    overlay,
  };
}
