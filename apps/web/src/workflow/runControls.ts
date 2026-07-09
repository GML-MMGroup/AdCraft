import type { AdRequest, WorkflowRunRequest, WorkflowRunResponse } from "../types";
import { isHiddenWorkflowNodeType } from "./visibility.ts";

export function buildMainWorkflowRunRequest(
  runSettings: Partial<WorkflowRunRequest>,
  adRequest: Partial<AdRequest>,
): WorkflowRunRequest {
  const runtimeSettings = { ...runSettings };
  delete runtimeSettings.force_rerun;
  delete runtimeSettings.only_missing;
  delete runtimeSettings.run_downstream;
  return {
    ...runtimeSettings,
    ...adRequest,
    ad_request: adRequest,
    mode: runSettings.mode ?? "run_from_frontier",
  };
}

export function formatWorkflowRunStatus(result: WorkflowRunResponse | null | undefined, fallback: string) {
  if (!result) return fallback;
  if (result.status === "no_op") return result.message || "Workflow is already completed and has no stale nodes.";
  const parts = [result.status ? `Workflow ${result.status}` : fallback];
  if (result.execution_id) parts.push(result.execution_id);
  if (result.mode) parts.push(`mode: ${result.mode}`);
  if (result.frontier_node_id && !isHiddenWorkflowNodeType(result.frontier_node_id)) parts.push(`frontier: ${result.frontier_node_id}`);
  const selectedNodes = visibleNodeIds(result.selected_node_ids);
  const queuedNodes = visibleNodeIds(result.queued_node_ids);
  const waitingNodes = visibleNodeIds(result.waiting_node_ids);
  const runningNodes = visibleNodeIds(result.running_node_ids);
  const executedNodes = visibleNodeIds(result.executed_node_ids);
  const skippedNodes = visibleNodeIds(result.skipped_node_ids);
  const failedNodes = visibleNodeIds(result.failed_node_id ? [result.failed_node_id] : result.failed_node_ids);
  if (selectedNodes.length && result.status === "queued") parts.push(`selected: ${selectedNodes.join(", ")}`);
  if (queuedNodes.length) parts.push(`queued: ${queuedNodes.join(", ")}`);
  if (runningNodes.length) parts.push(`running: ${runningNodes.join(", ")}`);
  if (waitingNodes.length) parts.push(`waiting: ${waitingNodes.join(", ")}`);
  if (executedNodes.length) parts.push(`executed: ${executedNodes.join(", ")}`);
  if (skippedNodes.length) parts.push(`skipped: ${skippedNodes.join(", ")}`);
  if (failedNodes.length) parts.push(`failed: ${failedNodes.join(", ")}`);
  return parts.join(" · ");
}

function visibleNodeIds(nodeIds?: string[]) {
  return (nodeIds ?? []).filter((nodeId) => !isHiddenWorkflowNodeType(nodeId));
}
