import { useCallback } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import type { V2GlobalRunRequest, WorkflowV2RunResponse } from "../../../types-v2.ts";

export type WorkflowV2ControllerArgs = {
  workflowId?: string | null;
  runWorkflow?: (body?: V2GlobalRunRequest) => Promise<WorkflowV2RunResponse>;
  refreshRuntime: (workflowId: string) => Promise<unknown> | unknown;
};

export type WorkflowV2Controller = {
  actions: {
    runWorkflow: (body?: V2GlobalRunRequest) => Promise<WorkflowV2RunResponse>;
    regenerateSlot: (slotId: string) => Promise<WorkflowV2RunResponse | null>;
  };
};

export function useWorkflowV2Controller({
  workflowId,
  runWorkflow: runWorkflowAction,
  refreshRuntime,
}: WorkflowV2ControllerArgs): WorkflowV2Controller {
  const runWorkflow = useCallback(async (body: V2GlobalRunRequest = { mode: "fill_missing_required_slots" }) => {
    if (!workflowId) throw new Error("Generate a V2 workflow before running it.");
    return runWorkflowAction ? runWorkflowAction(body) : v2Api.runWorkflowAsync(workflowId, body);
  }, [runWorkflowAction, workflowId]);

  const regenerateSlot = useCallback(async (slotId: string) => {
    if (!workflowId || !slotId) return null;
    const response = await v2Api.regenerateSlot(workflowId, slotId);
    await refreshRuntime(workflowId);
    return response;
  }, [refreshRuntime, workflowId]);

  return { actions: { runWorkflow, regenerateSlot } };
}
