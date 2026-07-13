export type V2WorkflowHydrationRequestToken = {
  workflowId: string;
  generation: number;
};

export function createV2WorkflowHydrationRequestGuard() {
  let activeWorkflowId: string | null = null;
  let generation = 0;

  return {
    activateWorkflow(workflowId: string | null) {
      if (activeWorkflowId === workflowId) return;
      activeWorkflowId = workflowId;
      generation += 1;
    },
    begin(workflowId: string): V2WorkflowHydrationRequestToken {
      if (activeWorkflowId !== workflowId) {
        return { workflowId, generation: -1 };
      }
      generation += 1;
      return { workflowId, generation };
    },
    isCurrent(token: V2WorkflowHydrationRequestToken, workflowId: string | null) {
      return activeWorkflowId === workflowId && token.workflowId === workflowId && token.generation === generation;
    },
    invalidate() {
      generation += 1;
    },
  };
}
