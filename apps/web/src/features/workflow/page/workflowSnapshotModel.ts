import { deleteCanvasSnapshot, loadCanvasSnapshot } from "../../../projects/newProject";
import type { WorkflowGraph } from "../../../types";
import type { WorkflowAutosaveSnapshot } from "../workflowAutosave";

export const LOCAL_WORKFLOW_ID = "local-workflow";
export const SNAPSHOT_PREFIX = "ad-workflow-canvas:";
export const SNAPSHOT_AUTOSAVE_DELAY_MS = 1800;
export const SNAPSHOT_IDLE_TIMEOUT_MS = 2200;

export function loadSnapshot(workflowId: string): WorkflowAutosaveSnapshot | null {
  try {
    return (loadCanvasSnapshot(window.localStorage, workflowId) as WorkflowAutosaveSnapshot | undefined) ?? null;
  } catch {
    return null;
  }
}

export function isSnapshotCompatibleWithWorkflow(snapshot: WorkflowAutosaveSnapshot, workflow?: WorkflowGraph | null) {
  if (!workflow?.workflow_id) return snapshot.workflowId === LOCAL_WORKFLOW_ID;
  const backendNodeIds = new Set((workflow.nodes ?? []).map((node) => node.id));
  if (!backendNodeIds.size) return false;
  return snapshot.workflowId === workflow.workflow_id && snapshot.nodes.every((node) => backendNodeIds.has(node.id));
}

export function isBackendWorkflowNode(nodeId: string, workflow?: WorkflowGraph | null) {
  if (!workflow?.workflow_id) return false;
  return (workflow.nodes ?? []).some((node) => node.id === nodeId);
}

export function snapshotKey(workflowId: string) {
  return `${SNAPSHOT_PREFIX}${workflowId}`;
}

export function clearSnapshot(workflowId: string) {
  deleteCanvasSnapshot(workflowId, window.localStorage);
}
