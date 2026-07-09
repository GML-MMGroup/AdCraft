import { ApiError } from "../../../api/client";
import { normalizeMediaStatus, normalizeWorkflowRunResponse } from "../../../api/workflowNormalizers";
import { isStoryboardVideoNode, shouldPollStoryboardVideoMedia, type StoryboardVideoReadiness } from "../../../workflow/mediaSegments";
import type {
  MediaStatus,
  NodeRunResult,
  ResolvedNodeInputs,
  WorkflowExecutionState,
  WorkflowRunResponse,
} from "../../../types";
import type { CanvasEdge, CanvasNode } from "../types";
import { findMediaPath } from "../final-composition/finalCompositionTimelineModel";
import { isFailedNodeStatus, isNodeStatusTerminal } from "../quality/qualityReviewViewModel";

export function getWorkflowRunNodeIds(nodes: CanvasNode[], edges: CanvasEdge[], startNodeId: string | null | undefined, includeDownstream: boolean) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  if (!startNodeId || !nodeIds.has(startNodeId)) return nodeIds;
  const selected = new Set([startNodeId]);
  if (!includeDownstream) return selected;

  const childrenBySource = new Map<string, string[]>();
  for (const edge of edges) {
    childrenBySource.set(edge.source, [...(childrenBySource.get(edge.source) ?? []), edge.target]);
  }
  const queue = [startNodeId];
  while (queue.length) {
    const current = queue.shift();
    if (!current) continue;
    for (const child of childrenBySource.get(current) ?? []) {
      if (selected.has(child)) continue;
      selected.add(child);
      queue.push(child);
    }
  }
  return selected;
}

export function shouldStopWorkflowPolling(
  runs: NodeRunResult[],
  expectedNodeIds: Set<string>,
  mediaStatus: MediaStatus | null,
  runResult: WorkflowRunResponse | undefined,
  attempt: number,
) {
  const expectedRunIds = [...expectedNodeIds].filter((nodeId) =>
    runs.some((run) => run.node_id === nodeId || run.node_type === nodeId),
  );
  const storyboardRunPending = hasPendingStoryboardVideoRun(runs);
  const expectedComplete =
    expectedRunIds.length >= expectedNodeIds.size &&
    expectedRunIds.length > 0 &&
    expectedRunIds.every((nodeId) =>
      runs
        .filter((run) => run.node_id === nodeId || run.node_type === nodeId)
        .every((run) => isNodeStatusTerminal(run.status)),
    );
  const allRunsTerminal = runs.length > 0 && runs.every((run) => isNodeStatusTerminal(run.status));
  const storyboardMediaPending = expectedNodeIds.has("storyboard-video-generation") && shouldPollStoryboardVideoMedia(mediaStatus);

  if (storyboardRunPending) return false;
  if (storyboardMediaPending) return false;
  if (expectedComplete) return true;
  if (!expectedNodeIds.size && allRunsTerminal) return true;
  if (isWorkflowRunTerminalStatus(runResult?.status) && attempt >= 2 && (runs.length > 0 || mediaStatus?.status)) return true;
  if (mediaStatus?.status && isWorkflowRunTerminalStatus(mediaStatus.status) && attempt >= 2) return true;
  return false;
}

export function getFailedRunNodeIds(runs: NodeRunResult[]) {
  return runs.filter((run) => isFailedNodeStatus(run.status)).map((run) => run.node_id || run.node_type).filter(Boolean);
}

export function workflowRunFailedNodeIds(result: WorkflowRunResponse) {
  return result.failed_node_id ? [result.failed_node_id] : result.failed_node_ids ?? [];
}

export function hasPendingStoryboardVideoRun(runs: NodeRunResult[]) {
  return runs.some((run) => isStoryboardVideoNode({ id: run.node_id, node_type: run.node_type }) && shouldPollStoryboardVideoMedia(run));
}

export function formatStoryboardVideoWaitingStatus(readiness: StoryboardVideoReadiness) {
  const { readyCount, totalCount } = readiness.progress;
  const progress = readyCount !== null && totalCount !== null ? ` (${readyCount}/${totalCount})` : "";
  return `${readiness.reason ?? "Storyboard video segments are still generating."}${progress}`;
}

export function resolvedInputsHaveReadyStoryboardSegments(resolvedInputs: ResolvedNodeInputs, readiness: StoryboardVideoReadiness) {
  const context = resolvedInputs.resolved_input_context ?? {};
  return (
    hasReadySegmentList(context.storyboard_video_segments) ||
    hasReadySegmentList(context.segments) ||
    hasReadySegmentList(context.input_assets) ||
    hasReadySegmentList(resolvedInputs.resolved_input_assets) ||
    readiness.assets.length > 0
  );
}

export function getMediaStatusFromRunResult(result: WorkflowRunResponse): MediaStatus | null {
  const base = result.media_status && typeof result.media_status === "object" ? result.media_status : null;
  if (!base && !result.final_video) return null;
  return normalizeMediaStatus({
    ...(base ?? {}),
    workflow_id: result.workflow_id ?? (base?.workflow_id as string | undefined),
    status: (base?.status as string | undefined) ?? result.status,
    final_video: result.final_video ?? base?.final_video ?? null,
  });
}

export function workflowRunResultFromExecution(execution?: WorkflowExecutionState | null): WorkflowRunResponse | null {
  const finalResult = execution?.final_result;
  return finalResult && typeof finalResult === "object" && !Array.isArray(finalResult) ? normalizeWorkflowRunResponse(finalResult) : null;
}

export function workflowRunResponseFromExecutionState(execution: WorkflowExecutionState, fallback?: WorkflowRunResponse): WorkflowRunResponse {
  return normalizeWorkflowRunResponse({
    ...(fallback ?? {}),
    workflow_id: execution.workflow_id ?? fallback?.workflow_id,
    execution_id: execution.execution_id ?? fallback?.execution_id,
    status: execution.status ?? fallback?.status,
    mode: execution.mode ?? fallback?.mode,
    frontier_node_id: execution.frontier_node_id ?? fallback?.frontier_node_id,
    selected_node_ids: execution.selected_node_ids ?? fallback?.selected_node_ids,
    queued_node_ids: execution.queued_node_ids ?? fallback?.queued_node_ids,
    running_node_ids: execution.running_node_ids ?? fallback?.running_node_ids,
    waiting_node_ids: execution.waiting_node_ids ?? fallback?.waiting_node_ids,
    completed_node_ids: execution.completed_node_ids ?? fallback?.completed_node_ids,
    skipped_node_ids: execution.skipped_node_ids ?? fallback?.skipped_node_ids,
    failed_node_ids: execution.failed_node_ids ?? fallback?.failed_node_ids,
    nodes: execution.nodes ?? fallback?.nodes,
    execution,
  });
}

export function formatWorkflowExecutionError(error: unknown) {
  const code = error instanceof ApiError ? apiErrorCode(error.payload) : "";
  const message = error instanceof Error ? error.message : "";
  if (code === "workflow_execution_already_running") {
    return { code, message: message || "当前工作流仍有等待中或运行中的执行。" };
  }
  if (code === "workflow_execution_not_found") {
    return { code, message: message || "Workflow execution was not found. Refreshing workflow state." };
  }
  if (code === "workflow_execution_invalid_state") {
    return { code, message: message || "Workflow execution is in an invalid state." };
  }
  return { code: "", message };
}

export function formatPromptOptimizerError(error: unknown) {
  const code = error instanceof ApiError ? apiErrorCode(error.payload) : "";
  if (code === "prompt_optimizer_failed") {
    return { code, message: "Prompt optimization failed. Keep editing your prompt or try again." };
  }
  if (code === "prompt_optimizer_invalid_output") {
    return { code, message: "Prompt optimizer returned invalid output." };
  }
  if (code === "prompt_optimizer_not_supported") {
    return { code, message: "Prompt optimization is not supported for this node." };
  }
  return { code, message: error instanceof Error ? error.message : "" };
}

export function workflowExecutionIdFromMessage(message: string) {
  return message.match(/\bexec[_-][A-Za-z0-9_-]+\b/)?.[0] ?? null;
}

export function hasReadySegmentList(value: unknown) {
  if (!Array.isArray(value)) return false;
  return value.some((item) => {
    if (!item || typeof item !== "object") return false;
    return Boolean(findMediaPath(item));
  });
}

export function finalCompositionErrorMessage(error: unknown) {
  const code = error instanceof ApiError ? apiErrorCode(error.payload) : "";
  const fallback = error instanceof Error ? error.message : "Final composition timeline request failed.";
  if (code === "timeline_version_conflict") return "Timeline version conflict. Current active final video remains available.";
  if (code === "timeline_not_found") return "Timeline was not found. Refresh the Final Composition timeline.";
  if (code === "timeline_invalid_source") return "Timeline contains an invalid source. Current active final video remains available.";
  if (code === "timeline_missing_source_asset") return "Timeline has a missing source asset. Current active final video remains available.";
  if (code === "timeline_has_stale_enabled_clips") return "Timeline has stale enabled clips. Current active final video remains available.";
  if (code === "timeline_no_enabled_video_clips") return "Enable at least one video clip before rendering.";
  if (code === "timeline_render_failed") return "Final render failed. Current active final video remains available.";
  if (code === "final_video_candidate_create_failed") return "Final video candidate could not be created. Current active final video remains available.";
  return fallback;
}

export function isWorkflowRunTerminalStatus(status?: string | null) {
  if (!status) return false;
  return ["completed", "complete", "success", "succeeded", "failed", "error", "cancelled", "canceled", "partial_failed", "timeout", "timed_out", "done", "finish", "finished"].includes(
    status.toLowerCase(),
  );
}

function apiErrorCode(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  if (typeof record.code === "string") return record.code;
  if (typeof record.error === "string") return record.error;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const detailRecord = detail as Record<string, unknown>;
    return String(detailRecord.code ?? detailRecord.error ?? detailRecord.type ?? "");
  }
  return "";
}
