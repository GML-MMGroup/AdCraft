import { isNetworkError, isV2ApiError, v2Api } from "../api/v2Client";
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

export type PlanningFailureState = {
  shouldNavigate: false;
  message: string;
  stage?: string;
  violations: unknown[];
  suggestedActions: Array<Record<string, unknown>>;
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

export function planningFailureState(error: unknown): PlanningFailureState {
  if (isNetworkError(error)) {
    return {
      shouldNavigate: false,
      message: "Backend is not available yet. Check the connection and try again.",
      violations: [],
      suggestedActions: [],
    };
  }
  if (isV2ApiError(error)) {
    return {
      shouldNavigate: false,
      message: error.message,
      stage: error.stage,
      violations: error.violations,
      suggestedActions: error.suggestedActions,
    };
  }
  if (hasHttpErrorShape(error)) {
    return {
      shouldNavigate: false,
      message: error.message,
      violations: [],
      suggestedActions: [],
    };
  }
  return {
    shouldNavigate: false,
    message: error instanceof Error ? error.message : "Planning could not be completed. Try again.",
    violations: [],
    suggestedActions: [],
  };
}

function hasHttpErrorShape(value: unknown): value is { status: number; message: string } {
  return Boolean(
    value
    && typeof value === "object"
    && typeof (value as { status?: unknown }).status === "number"
    && typeof (value as { message?: unknown }).message === "string",
  );
}
