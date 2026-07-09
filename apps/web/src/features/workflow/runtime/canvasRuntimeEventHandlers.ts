export type ScopedWorkflowRefreshPlan = {
  nodeIds?: Array<string | null | undefined>;
  resolvedInputNodeIds?: Array<string | null | undefined>;
  graph?: boolean;
  mediaStatus?: boolean;
  runtimeSnapshot?: boolean;
};

export type PendingScopedWorkflowRefresh = {
  workflowId: string;
  nodeIds: Set<string>;
  resolvedInputNodeIds: Set<string>;
  graph: boolean;
  mediaStatus: boolean;
  runtimeSnapshot: boolean;
};

function createPendingScopedWorkflowRefresh(workflowId: string): PendingScopedWorkflowRefresh {
  return {
    workflowId,
    nodeIds: new Set<string>(),
    resolvedInputNodeIds: new Set<string>(),
    graph: false,
    mediaStatus: false,
    runtimeSnapshot: false,
  };
}

function mergeScopedWorkflowRefreshPlan(pending: PendingScopedWorkflowRefresh, plan: ScopedWorkflowRefreshPlan) {
  plan.nodeIds?.forEach((nodeId) => {
    if (nodeId) pending.nodeIds.add(nodeId);
  });
  plan.resolvedInputNodeIds?.forEach((nodeId) => {
    if (nodeId) pending.resolvedInputNodeIds.add(nodeId);
  });
  pending.graph ||= Boolean(plan.graph);
  pending.mediaStatus ||= Boolean(plan.mediaStatus);
  pending.runtimeSnapshot ||= Boolean(plan.runtimeSnapshot);
}

function isNodeStatusRuntimeEvent(type: string) {
  return [
    "node_status_changed",
    "node_started",
    "node_running",
    "node_queued",
    "node_waiting",
    "node_failed",
    "node_completed",
    "node_skipped",
    "node_cancelled",
    "node_blocked",
  ].includes(type);
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

export const canvasRuntimeEventHandlers = {
  createPendingScopedWorkflowRefresh,
  mergeScopedWorkflowRefreshPlan,
  isNodeStatusRuntimeEvent,
  recordFromUnknown,
};
