export type ScopedWorkflowRefreshPlan = {
  graph?: boolean;
  media?: boolean;
  nodeRuns?: boolean;
  nodeIds: Set<string>;
  resolvedInputNodeIds: Set<string>;
  candidateNodeIds: Set<string>;
};

export type PendingScopedWorkflowRefresh = ScopedWorkflowRefreshPlan & {
  workflowId: string;
};

export function createPendingScopedWorkflowRefresh(workflowId: string): PendingScopedWorkflowRefresh {
  return {
    workflowId,
    graph: false,
    media: false,
    nodeRuns: false,
    nodeIds: new Set<string>(),
    resolvedInputNodeIds: new Set<string>(),
    candidateNodeIds: new Set<string>(),
  };
}

export function mergeScopedWorkflowRefreshPlan(pending: PendingScopedWorkflowRefresh, plan: ScopedWorkflowRefreshPlan): void {
  pending.graph = Boolean(pending.graph || plan.graph);
  pending.media = Boolean(pending.media || plan.media);
  pending.nodeRuns = Boolean(pending.nodeRuns || plan.nodeRuns);
  plan.nodeIds.forEach((id) => pending.nodeIds.add(id));
  plan.resolvedInputNodeIds.forEach((id) => pending.resolvedInputNodeIds.add(id));
  plan.candidateNodeIds.forEach((id) => pending.candidateNodeIds.add(id));
}

export function scopedRefreshPlanFromHints(refreshHints: string[], targetNodeId?: string | null): ScopedWorkflowRefreshPlan {
  const plan: ScopedWorkflowRefreshPlan = {
    graph: refreshHints.includes("graph"),
    media: refreshHints.includes("media"),
    nodeRuns: refreshHints.includes("node_runs"),
    nodeIds: new Set<string>(),
    resolvedInputNodeIds: new Set<string>(),
    candidateNodeIds: new Set<string>(),
  };
  if (targetNodeId) {
    plan.nodeIds.add(targetNodeId);
    if (refreshHints.includes("resolved_inputs")) plan.resolvedInputNodeIds.add(targetNodeId);
    if (refreshHints.includes("candidates")) plan.candidateNodeIds.add(targetNodeId);
  }
  return plan;
}
