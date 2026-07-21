export type V2WorkflowApplicationCapture = {
  workflowId: string;
  revision: number;
};

export type V2WorkflowApplicationRevisionGuard = ReturnType<typeof createV2WorkflowApplicationRevisionGuard>;

/** Tracks authoritative V2 workflow applications independently from request ordering. */
export function createV2WorkflowApplicationRevisionGuard() {
  let activeWorkflowId: string | null = null;
  let revision = 0;

  return {
    activateWorkflow(workflowId: string | null) {
      if (activeWorkflowId === workflowId) return;
      activeWorkflowId = workflowId;
      revision += 1;
    },
    invalidate() {
      activeWorkflowId = null;
      revision += 1;
    },
    appliedWorkflow(workflowId: string) {
      activeWorkflowId = workflowId;
      revision += 1;
    },
    capture(workflowId: string): V2WorkflowApplicationCapture {
      return { workflowId, revision };
    },
    isCurrent(capture: V2WorkflowApplicationCapture, currentActiveWorkflowId: string | null) {
      return capture.workflowId === currentActiveWorkflowId && capture.workflowId === activeWorkflowId && capture.revision === revision;
    },
  };
}
