import type { CanvasEdge, CanvasNode } from "../types.ts";
import type { WorkflowGraph } from "../../../types.ts";
import type { WorkflowV2 } from "../../../types-v2.ts";

export type WorkflowGraphControllerOptions = {
  workflow?: WorkflowGraph | null;
  workflowV2?: WorkflowV2 | null;
  setWorkflow?: (workflow: WorkflowGraph | null) => void;
  setWorkflowV2?: (workflow: WorkflowV2 | null) => void;
  setFlowNodes?: (updater: CanvasNode[] | ((nodes: CanvasNode[]) => CanvasNode[])) => void;
  setFlowEdges?: (updater: CanvasEdge[] | ((edges: CanvasEdge[]) => CanvasEdge[])) => void;
};

export function useWorkflowGraphController(options: WorkflowGraphControllerOptions = {}) {
  async function applyWorkflowGraph(workflow: WorkflowGraph) {
    options.setWorkflow?.(workflow);
  }
  async function applyWorkflowV2(workflow: WorkflowV2) {
    options.setWorkflowV2?.(workflow);
  }
  async function refreshWorkflowGraph() {
    return options.workflow ?? null;
  }
  async function refreshV2WorkflowGraph() {
    return options.workflowV2 ?? null;
  }
  async function saveCanvas() {
    return options.workflow ?? null;
  }
  async function validateBackendGraph() {
    return null;
  }
  function persistLocalSnapshot() {
    return undefined;
  }
  function scheduleIdleSnapshotWrite() {
    return undefined;
  }
  function cancelIdleSnapshotWrite() {
    return undefined;
  }
  return {
    applyWorkflowGraph,
    applyWorkflowV2,
    refreshWorkflowGraph,
    refreshV2WorkflowGraph,
    saveCanvas,
    validateBackendGraph,
    persistLocalSnapshot,
    scheduleIdleSnapshotWrite,
    cancelIdleSnapshotWrite,
  };
}
