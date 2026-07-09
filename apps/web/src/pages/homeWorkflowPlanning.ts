import { v2Api } from "../api/v2Client";
import { buildV2PlanFromChatRequest } from "../features/workflow/copilot/copilotRequestBuilders";
import type { AssetLibraryEntitySummary, FrontDeskMessage, WorkflowGraph } from "../types";
import { workflowV2ToWorkflowGraph } from "../workflow-v2/pageAdapter";

export type HomeWorkflowPlanningArgs = {
  prompt: string;
  history: FrontDeskMessage[];
  inputAssets: string[];
  libraryEntities: AssetLibraryEntitySummary[];
};

export type HomeWorkflowPlanningResult = {
  reply: string;
  workflow: WorkflowGraph | null;
  shouldStartWorkflow: boolean;
};

export async function planHomeWorkflow(args: HomeWorkflowPlanningArgs): Promise<HomeWorkflowPlanningResult> {
  const response = await v2Api.planFromChat(buildV2PlanFromChatRequest({
    message: args.prompt,
    history: args.history,
    inputAssets: args.inputAssets,
    audioMode: "bgm_only",
    libraryEntityIds: args.libraryEntities.map((entity) => entity.entity_id),
    referenceMode: "strict",
  }));
  return {
    reply: response.front_desk.reply,
    workflow: response.workflow ? workflowV2ToWorkflowGraph(response.workflow) : null,
    shouldStartWorkflow: response.front_desk.should_start_workflow,
  };
}
