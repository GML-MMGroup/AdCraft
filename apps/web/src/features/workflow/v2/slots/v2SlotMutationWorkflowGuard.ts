import type { WorkflowV2 } from "../../../../types-v2.ts";
import type { V2WorkflowApplicationCapture } from "../../graph/v2WorkflowApplicationRevisionGuard.ts";

export async function reconcileV2SlotMutationWorkflow(args: {
  workflowId: string;
  capture: V2WorkflowApplicationCapture;
  activeWorkflowId: string | null;
  isCurrentRevision: (capture: V2WorkflowApplicationCapture, currentActiveWorkflowId: string | null) => boolean;
  returnedWorkflow?: WorkflowV2 | null;
  applyWorkflowV2: (workflow: WorkflowV2) => Promise<void>;
  refreshLatestWorkflow: () => Promise<WorkflowV2 | null>;
}) {
  if (args.isCurrentRevision(args.capture, args.activeWorkflowId)) {
    if (args.returnedWorkflow) await args.applyWorkflowV2(args.returnedWorkflow);
    return { stale: false as const, workflow: args.returnedWorkflow ?? null };
  }
  if (args.activeWorkflowId !== args.workflowId) return { stale: true as const, workflow: null };
  return { stale: true as const, workflow: await args.refreshLatestWorkflow() };
}
