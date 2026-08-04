import { useWorkflowCopilotPlanning } from "../copilot/useWorkflowCopilotPlanning.ts";
import { useWorkflowRunController } from "../runtime/useWorkflowRunController.ts";
import { useAgentConversationBridge } from "../copilot/useAgentConversationBridge.ts";
import { useWorkflowLocalSnapshotController } from "./useWorkflowLocalSnapshotController.ts";
import { useWorkflowGraphMutationController } from "../graph/useWorkflowGraphMutationController.ts";
import { defaultAdRequest } from "./workflowPageDefaults.ts";
import type { WorkflowPageRunGraphControllersArgs } from "./workflowPageContracts.ts";

export function useWorkflowPageRunGraphControllers(args: WorkflowPageRunGraphControllersArgs) {
  const copilotPlanning = useWorkflowCopilotPlanning({
    ...args.planning,
    bridgeFrontDeskMessagesToAgentConversation: (requestWorkflowId, plannedMessages) =>
      args.refs.bridgeFrontDeskMessagesToAgentConversation.current?.(requestWorkflowId, plannedMessages) ?? Promise.resolve(),
  });
  const { askCopilot, uploadV2PromptInputAsset, v2PlanFromPromptRequest } = copilotPlanning.actions;

  const workflowRunController = useWorkflowRunController({
    ...args.run,
    defaultAdRequest,
    v2PlanFromPromptRequest,
    syncV2Events: (requestWorkflowId) => args.runtime.v2Runtime.syncEvents(requestWorkflowId),
    syncV2Snapshot: (requestWorkflowId) => args.runtime.v2Runtime.syncSnapshot(requestWorkflowId),
    runV2Workflow: args.runtime.workflowV2Controller.actions.runWorkflow,
  });
  args.refs.workflowRunActions.current = workflowRunController.actions;

  const agentConversationBridge = useAgentConversationBridge({
    ...args.conversation,
    askCopilot,
  });
  args.refs.bridgeFrontDeskMessagesToAgentConversation.current = agentConversationBridge.actions.bridgeFrontDeskMessagesToAgentConversation;

  const localSnapshot = useWorkflowLocalSnapshotController(args.snapshot);

  const workflowGraphMutations = useWorkflowGraphMutationController({
    ...args.graph,
    getCurrentRunAdRequest: workflowRunController.actions.getCurrentRunAdRequest,
    persistLocalSnapshot: localSnapshot.actions.persistLocalSnapshot,
    persistNodePositionSnapshot: localSnapshot.actions.persistNodePositionSnapshot,
  });
  args.refs.workflowGraphMutations.current = workflowGraphMutations;

  return {
    askCopilot,
    uploadV2PromptInputAsset,
    workflowRunController,
    agentConversationBridge,
    workflowGraphMutations,
    persistLocalSnapshot: localSnapshot.actions.persistLocalSnapshot,
  };
}
