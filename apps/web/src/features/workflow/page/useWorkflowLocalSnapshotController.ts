import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import type {
  AssetLibraryEntitySummary,
  FrontDeskMessage,
  NodeRunResult,
  UploadedAsset,
  WorkflowGraph,
  WorkflowNode,
  WorkflowVariable,
} from "../../../types";
import type { CanvasEdge, CanvasNode } from "../types";
import { normalizeFlowEdges } from "../canvas/workflowCanvasModel.ts";
import {
  createWorkflowPositionSnapshotPayload,
  createWorkflowSnapshotPayload,
  loadWorkflowSnapshot,
  saveWorkflowSnapshot,
  scheduleWorkflowSnapshotWrite,
  stableSnapshotHash,
  stableSnapshotPositionHash,
} from "../workflowAutosave.ts";
import {
  SNAPSHOT_AUTOSAVE_DELAY_MS,
  SNAPSHOT_IDLE_TIMEOUT_MS,
} from "./workflowSnapshotModel.ts";

const POSITION_SNAPSHOT_SAVE_DELAY_MS = 900;

type SaveProjectInput = {
  workflow: WorkflowGraph | null;
  messages: FrontDeskMessage[];
  nodeRuns: NodeRunResult[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
};

export type WorkflowLocalSnapshotControllerArgs = {
  workflowId: string;
  canvasNodes: WorkflowNode[];
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  workflowVariables: WorkflowVariable[];
  reactFlow: ReactFlowInstance<CanvasNode, CanvasEdge> | null;
  activeProjectId: string | null;
  isRestoringWorkspace: boolean;
  workflow: WorkflowGraph | null | undefined;
  messages: FrontDeskMessage[];
  nodeRuns: NodeRunResult[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  saveProject: (input: SaveProjectInput) => void;
  setSavedAt: (value: string | null) => void;
  setStatus: (value: string) => void;
};

export function useWorkflowLocalSnapshotController({
  workflowId,
  canvasNodes,
  flowNodes,
  flowEdges,
  workflowVariables,
  reactFlow,
  activeProjectId,
  isRestoringWorkspace,
  workflow,
  messages,
  nodeRuns,
  selectedAssets,
  promptLibraryEntities,
  saveProject,
  setSavedAt,
  setStatus,
}: WorkflowLocalSnapshotControllerArgs) {
  const snapshotIdleHandleRef = useRef<(() => void) | null>(null);
  const pendingSnapshotCommitRef = useRef<(() => void) | null>(null);
  const positionSnapshotTimerRef = useRef<number | null>(null);
  const pendingPositionSnapshotCommitRef = useRef<(() => void) | null>(null);
  const lastSnapshotHashRef = useRef("");
  const lastPositionSnapshotHashRef = useRef("");
  const skipNextAutosaveForPositionRef = useRef(false);

  const cancelIdleSnapshotWrite = useCallback(() => {
    if (snapshotIdleHandleRef.current !== null) {
      snapshotIdleHandleRef.current();
      snapshotIdleHandleRef.current = null;
    }
    pendingSnapshotCommitRef.current = null;
  }, []);

  const flushIdleSnapshotWrite = useCallback(() => {
    const pendingCommit = pendingSnapshotCommitRef.current;
    if (!pendingCommit) return;
    if (snapshotIdleHandleRef.current !== null) {
      snapshotIdleHandleRef.current();
      snapshotIdleHandleRef.current = null;
    }
    pendingSnapshotCommitRef.current = null;
    pendingCommit();
  }, []);

  const scheduleIdleSnapshotWrite = useCallback((callback: () => void) => {
    cancelIdleSnapshotWrite();
    pendingSnapshotCommitRef.current = callback;
    snapshotIdleHandleRef.current = scheduleWorkflowSnapshotWrite(() => {
      snapshotIdleHandleRef.current = null;
      const pendingCommit = pendingSnapshotCommitRef.current;
      pendingSnapshotCommitRef.current = null;
      pendingCommit?.();
    }, { timeout: SNAPSHOT_IDLE_TIMEOUT_MS });
  }, [cancelIdleSnapshotWrite]);

  const cancelPositionSnapshotWrite = useCallback(() => {
    if (positionSnapshotTimerRef.current !== null) {
      window.clearTimeout(positionSnapshotTimerRef.current);
      positionSnapshotTimerRef.current = null;
    }
    pendingPositionSnapshotCommitRef.current = null;
  }, []);

  const flushPositionSnapshotWrite = useCallback(() => {
    const pendingCommit = pendingPositionSnapshotCommitRef.current;
    if (!pendingCommit) return;
    if (positionSnapshotTimerRef.current !== null) {
      window.clearTimeout(positionSnapshotTimerRef.current);
      positionSnapshotTimerRef.current = null;
    }
    pendingPositionSnapshotCommitRef.current = null;
    pendingCommit();
  }, []);

  const schedulePositionSnapshotWrite = useCallback((callback: () => void) => {
    cancelPositionSnapshotWrite();
    pendingPositionSnapshotCommitRef.current = callback;
    positionSnapshotTimerRef.current = window.setTimeout(() => {
      positionSnapshotTimerRef.current = null;
      const pendingCommit = pendingPositionSnapshotCommitRef.current;
      pendingPositionSnapshotCommitRef.current = null;
      pendingCommit?.();
    }, POSITION_SNAPSHOT_SAVE_DELAY_MS);
  }, [cancelPositionSnapshotWrite]);

  const persistLocalSnapshot = useCallback((nodes = canvasNodes, options: { immediate?: boolean; flowNodes?: CanvasNode[] } = {}) => {
    try {
      const commitSnapshot = () => {
        try {
          performance.mark?.("workflow:persistLocalSnapshot:start");
          const snapshot = createWorkflowSnapshotPayload({
            workflowId,
            nodes,
            flowNodes: options.flowNodes ?? flowNodes,
            edges: flowEdges,
            variables: workflowVariables,
            viewport: reactFlow?.getViewport(),
            normalizeEdges: normalizeFlowEdges,
          });
          const snapshotHash = stableSnapshotHash(snapshot);
          if (snapshotHash === lastSnapshotHashRef.current) return;
          saveWorkflowSnapshot(window.localStorage, workflowId, snapshot);
          lastSnapshotHashRef.current = snapshotHash;
          performance.mark?.("workflow:persistLocalSnapshot:commit");
          performance.measure?.("workflow:persistLocalSnapshot", "workflow:persistLocalSnapshot:start", "workflow:persistLocalSnapshot:commit");
          setSavedAt(snapshot.savedAt);
          if (activeProjectId || workflow || messages.length || nodeRuns.length || selectedAssets.length) {
            saveProject({ workflow: workflow ?? null, messages, nodeRuns, selectedAssets, promptLibraryEntities });
          }
        } catch {
          setStatus("Local draft snapshot failed, but workflow actions can continue.");
        }
      };

      if (options.immediate) {
        cancelIdleSnapshotWrite();
        commitSnapshot();
      } else {
        scheduleIdleSnapshotWrite(commitSnapshot);
      }
    } catch {
      setStatus("Local draft snapshot failed, but workflow actions can continue.");
    }
  }, [
    activeProjectId,
    cancelIdleSnapshotWrite,
    canvasNodes,
    flowEdges,
    flowNodes,
    messages,
    nodeRuns,
    promptLibraryEntities,
    reactFlow,
    saveProject,
    scheduleIdleSnapshotWrite,
    selectedAssets,
    setSavedAt,
    setStatus,
    workflow,
    workflowId,
    workflowVariables,
  ]);

  const persistNodePositionSnapshot = useCallback((nodes = canvasNodes, options: { flowNodes?: CanvasNode[] } = {}) => {
    try {
      skipNextAutosaveForPositionRef.current = true;
      const commitSnapshot = () => {
        try {
          performance.mark?.("workflow:persistNodePositionSnapshot:start");
          const existingSnapshot = loadWorkflowSnapshot(window.localStorage, workflowId) ?? null;
          const snapshot = createWorkflowPositionSnapshotPayload({
            workflowId,
            existingSnapshot,
            nodes,
            flowNodes: options.flowNodes ?? flowNodes,
            edges: flowEdges,
            variables: workflowVariables,
            viewport: reactFlow?.getViewport(),
            normalizeEdges: normalizeFlowEdges,
          });
          const snapshotHash = stableSnapshotPositionHash(snapshot);
          if (snapshotHash === lastPositionSnapshotHashRef.current) return;
          saveWorkflowSnapshot(window.localStorage, workflowId, snapshot);
          lastPositionSnapshotHashRef.current = snapshotHash;
          performance.mark?.("workflow:persistNodePositionSnapshot:commit");
          performance.measure?.("workflow:persistNodePositionSnapshot", "workflow:persistNodePositionSnapshot:start", "workflow:persistNodePositionSnapshot:commit");
          setSavedAt(snapshot.savedAt);
        } catch {
          setStatus("Position snapshot failed, but workflow actions can continue.");
        }
      };

      schedulePositionSnapshotWrite(commitSnapshot);
    } catch {
      setStatus("Position snapshot failed, but workflow actions can continue.");
    }
  }, [
    canvasNodes,
    flowEdges,
    flowNodes,
    reactFlow,
    schedulePositionSnapshotWrite,
    setSavedAt,
    setStatus,
    workflowId,
    workflowVariables,
  ]);

  useEffect(() => {
    if (isRestoringWorkspace) return;
    if (skipNextAutosaveForPositionRef.current) {
      skipNextAutosaveForPositionRef.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      persistLocalSnapshot();
    }, SNAPSHOT_AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [isRestoringWorkspace, persistLocalSnapshot]);

  useEffect(() => () => {
    flushIdleSnapshotWrite();
    flushPositionSnapshotWrite();
  }, [flushIdleSnapshotWrite, flushPositionSnapshotWrite]);

  return useMemo(
    () => ({
      actions: {
        persistLocalSnapshot,
        persistNodePositionSnapshot,
        cancelIdleSnapshotWrite,
        flushIdleSnapshotWrite,
      },
    }),
    [cancelIdleSnapshotWrite, flushIdleSnapshotWrite, persistLocalSnapshot, persistNodePositionSnapshot],
  );
}
