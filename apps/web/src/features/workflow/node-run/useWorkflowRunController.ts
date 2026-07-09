import type { MediaStatus, NodeRunResult, WorkflowGraph, WorkflowRunRequest } from "../../../types.ts";
import type { WorkflowV2 } from "../../../types-v2.ts";

export function useWorkflowRunController(options: {
  workflow?: WorkflowGraph | null;
  workflowV2?: WorkflowV2 | null;
  selectedNodeId?: string | null;
  activeV2SlotId?: string | null;
  buildWorkflowRunRequest?: (overrides?: Partial<WorkflowRunRequest>) => WorkflowRunRequest;
  refreshWorkflowGraph?: (workflowId?: string) => Promise<void>;
  refreshV2WorkflowGraph?: (workflowId: string) => Promise<void>;
  applyNodeRunsToCanvas?: (runs: NodeRunResult[]) => void;
  applyMediaStatusToCanvas?: (status: MediaStatus | null) => void;
} = {}) {
  async function runWorkflow() {
    return null;
  }
  async function runFromSelected() {
    return null;
  }
  async function runNode() {
    return null;
  }
  async function refreshExecutionRuntime() {
    return null;
  }
  async function executeWorkflowRun() {
    return null;
  }
  async function pollWorkflowResults() {
    return null;
  }
  async function refreshMediaStatus() {
    return null;
  }
  void options;
  return { runWorkflow, runFromSelected, runNode, refreshExecutionRuntime, executeWorkflowRun, pollWorkflowResults, refreshMediaStatus };
}
