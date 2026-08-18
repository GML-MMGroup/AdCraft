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
}: {
  workflowId: string;
  persistPositions: (positions: CanvasLayoutPositionV2[]) => Promise<void>;
  restoreViewport: (viewport: Viewport) => Promise<unknown> | unknown;
}): {
  status: AgentCanvasLayoutPreviewStatus;
  error: string | null;
  active: boolean;
  positions: CanvasLayoutPositionV2[];
  begin: (preview: AgentCanvasLayoutPreviewStart<TNode>) => void;
  cancel: () => void;
  keep: () => Promise<void>;
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

  workflowIdRef.current = workflowId;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!snapshot || snapshot.workflowId === workflowId) return;
    if (snapshotRef.current?.transactionId !== snapshot.transactionId) return;
    snapshotRef.current = null;
    savingTransactionIdRef.current = null;
    setSnapshot(null);
    setStatus("idle");
    setError(null);
  }, [snapshot, workflowId]);

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
    setSnapshot(null);
    setStatus("idle");
    setError(null);
    void Promise.resolve(restoreViewport(currentSnapshot.originalViewport)).catch(() => undefined);
  }, [restoreViewport]);

  const keep = useCallback(async () => {
    const currentSnapshot = snapshotRef.current;
    if (
      !currentSnapshot
      || currentSnapshot.workflowId !== workflowId
      || savingTransactionIdRef.current !== null
    ) return;

    const transactionId = currentSnapshot.transactionId;
    savingTransactionIdRef.current = transactionId;
    setStatus("saving");
    setError(null);
    try {
      await persistPositions(currentSnapshot.targetPositions);
      if (
        !mountedRef.current
        || workflowIdRef.current !== currentSnapshot.workflowId
        || snapshotRef.current?.transactionId !== transactionId
      ) return;
      snapshotRef.current = null;
      savingTransactionIdRef.current = null;
      setSnapshot(null);
      setStatus("idle");
    } catch (saveError) {
      if (
        !mountedRef.current
        || workflowIdRef.current !== currentSnapshot.workflowId
        || snapshotRef.current?.transactionId !== transactionId
      ) return;
      savingTransactionIdRef.current = null;
      setStatus("save_error");
      setError(previewErrorMessage(saveError));
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
