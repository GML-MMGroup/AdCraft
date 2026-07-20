import { useMemo } from "react";

export type WorkflowRuntimeFacadeArgs = {
  isV2: boolean;
  v1RunningNodeIds: string[];
  v2RunningNodeIds: string[];
  connectionState: string;
  runV1Workflow: () => Promise<void>;
  runV2Workflow: () => Promise<void>;
};

export type WorkflowRuntimeFacade = {
  state: {
    runningNodeIds: string[];
    connectionState: string;
  };
  actions: {
    runWorkflow: () => Promise<void>;
  };
};

export function useWorkflowRuntimeFacade(args: WorkflowRuntimeFacadeArgs): WorkflowRuntimeFacade {
  return useMemo(
    () => ({
      state: {
        runningNodeIds: args.isV2 ? args.v2RunningNodeIds : args.v1RunningNodeIds,
        connectionState: args.connectionState,
      },
      actions: {
        runWorkflow: args.isV2 ? args.runV2Workflow : args.runV1Workflow,
      },
    }),
    [
      args.connectionState,
      args.isV2,
      args.runV1Workflow,
      args.runV2Workflow,
      args.v1RunningNodeIds,
      args.v2RunningNodeIds,
    ],
  );
}
