import type { WorkflowEdge, WorkflowExecutionState, WorkflowRunResponse } from "../types";

export type ExecutionPollingState = "idle" | "starting" | "polling" | "completed" | "failed";

export type ExecutionRuntimeState = {
  activeExecutionId: string | null;
  nodeStatusById: Record<string, string>;
  runningNodeIds: string[];
  pollingState: ExecutionPollingState;
};

type ExecutionRuntimeSource = Pick<WorkflowRunResponse | WorkflowExecutionState, "execution_id" | "status" | "nodes" | "running_node_ids">;
type EdgeLike = Pick<WorkflowEdge, "id" | "source" | "target" | "source_node_id" | "target_node_id">;

export function executionRuntimeFromRunResponse(source?: ExecutionRuntimeSource | null): ExecutionRuntimeState {
  const activeExecutionId = normalizeText(source?.execution_id) ?? null;
  const nodeStatusById: Record<string, string> = {};

  for (const node of source?.nodes ?? []) {
    const nodeId = normalizeText(node.node_id);
    const status = normalizeText(node.status);
    if (nodeId && status) nodeStatusById[nodeId] = status;
  }

  return {
    activeExecutionId,
    nodeStatusById,
    runningNodeIds: uniqueStrings(source?.running_node_ids ?? []),
    pollingState: pollingStateFromExecutionStatus(source?.status, activeExecutionId),
  };
}

export function nodeStatusWithExecution(nodeId: string, fallbackStatus: string | undefined, executionNodeStatusById: Record<string, string>) {
  return executionNodeStatusById[nodeId] ?? fallbackStatus;
}

export function executionRunningEdgeIds<T extends EdgeLike>(edges: T[], runningNodeIds: Set<string>) {
  return new Set(
    edges
      .filter((edge) => runningNodeIds.has(edge.source ?? edge.source_node_id ?? ""))
      .map((edge) => edge.id ?? edgeIdFromEndpoints(edge.source ?? edge.source_node_id, edge.target ?? edge.target_node_id))
      .filter((edgeId): edgeId is string => Boolean(edgeId)),
  );
}

export function isExecutionRuntimeTerminal(status?: string | null) {
  if (!status) return false;
  return ["completed", "complete", "success", "succeeded", "failed", "error", "cancelled", "canceled", "partial_failed", "timeout", "timed_out", "done", "finish", "finished"].includes(
    status.toLowerCase(),
  );
}

function pollingStateFromExecutionStatus(status?: string | null, executionId?: string | null): ExecutionPollingState {
  const normalized = (status ?? "").toLowerCase();
  if (["completed", "complete", "success", "succeeded", "done", "finish", "finished"].includes(normalized)) return "completed";
  if (["failed", "error", "cancelled", "canceled", "partial_failed", "timeout", "timed_out"].includes(normalized)) return "failed";
  if (executionId || ["queued", "running", "waiting", "pending", "processing", "in_progress"].includes(normalized)) return "polling";
  return "idle";
}

function uniqueStrings(values: unknown[]) {
  const seen = new Set<string>();
  const items: string[] = [];
  for (const value of values) {
    const text = normalizeText(value);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    items.push(text);
  }
  return items;
}

function normalizeText(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function edgeIdFromEndpoints(source?: string | null, target?: string | null) {
  return source && target ? `${source}-${target}` : undefined;
}
