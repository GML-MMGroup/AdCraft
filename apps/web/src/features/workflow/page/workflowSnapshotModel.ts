import { deleteCanvasSnapshot, loadCanvasSnapshot } from "../../../projects/newProject";
import type { WorkflowGraph } from "../../../types";
import type { WorkflowAutosaveSnapshot } from "../workflowAutosave";

export const LOCAL_WORKFLOW_ID = "local-workflow";
export const SNAPSHOT_PREFIX = "ad-workflow-canvas:";
export const SNAPSHOT_AUTOSAVE_DELAY_MS = 1800;
export const SNAPSHOT_IDLE_TIMEOUT_MS = 2200;

const RETIRED_DEFAULT_NODE_IDS = new Set(["prompt", "image-set", "video-preview"]);
const RETIRED_DEFAULT_EDGE_IDS = new Set(["prompt:image-set", "image-set:video-preview"]);

export function loadSnapshot(workflowId: string): WorkflowAutosaveSnapshot | null {
  try {
    const snapshot = (loadCanvasSnapshot(window.localStorage, workflowId) as WorkflowAutosaveSnapshot | undefined) ?? null;
    if (snapshot && isRetiredDefaultGraphSnapshot(snapshot)) {
      clearSnapshot(workflowId);
      return null;
    }
    return snapshot;
  } catch {
    return null;
  }
}

export function isSnapshotCompatibleWithWorkflow(snapshot: WorkflowAutosaveSnapshot, workflow?: WorkflowGraph | null) {
  if (!workflow?.workflow_id) {
    return snapshot.workflowId === LOCAL_WORKFLOW_ID && !isRetiredDefaultGraphSnapshot(snapshot);
  }
  const backendNodeIds = new Set((workflow.nodes ?? []).map((node) => node.id));
  if (!backendNodeIds.size) return false;
  return snapshot.workflowId === workflow.workflow_id && snapshot.nodes.every((node) => backendNodeIds.has(node.id));
}

function isRetiredDefaultGraphSnapshot(snapshot: WorkflowAutosaveSnapshot) {
  if (snapshot.workflowId !== LOCAL_WORKFLOW_ID || snapshot.nodes.length !== RETIRED_DEFAULT_NODE_IDS.size) return false;
  const nodeIds = new Set(snapshot.nodes.map((node) => node.id));
  if (nodeIds.size !== RETIRED_DEFAULT_NODE_IDS.size) return false;
  if (![...RETIRED_DEFAULT_NODE_IDS].every((nodeId) => nodeIds.has(nodeId))) return false;
  if (snapshot.edges.length !== RETIRED_DEFAULT_EDGE_IDS.size) return false;
  const edgeIds = new Set(snapshot.edges.map((edge) => `${edge.source}:${edge.target}`));
  return edgeIds.size === RETIRED_DEFAULT_EDGE_IDS.size
    && [...RETIRED_DEFAULT_EDGE_IDS].every((edgeId) => edgeIds.has(edgeId));
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
