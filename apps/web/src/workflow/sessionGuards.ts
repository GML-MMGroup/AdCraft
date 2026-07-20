export function shouldApplyWorkflowScopedResult(requestWorkflowId?: string | null, activeWorkflowId?: string | null) {
  return Boolean(requestWorkflowId && activeWorkflowId && requestWorkflowId === activeWorkflowId);
}
