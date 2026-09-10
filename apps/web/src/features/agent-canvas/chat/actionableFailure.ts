import type {
  ActionableFailureV1,
  ActionableRetryScopeV1,
  ActionableUserActionV1,
  AgentCanvasChatTurnV2,
  CanvasNodeV2,
  ChatCapabilityActivityV2,
} from "../../../types-v2.ts";

export function canRetryFailureInScope(
  failure: ActionableFailureV1 | null | undefined,
  scope: Exclude<ActionableRetryScopeV1, "none">,
): boolean {
  return failure?.user_action === "retry"
    && failure.retry_scope === scope;
}

export function failureUserAction(
  failure: ActionableFailureV1 | null | undefined,
): ActionableUserActionV1 {
  return failure?.user_action ?? "none";
}

export function turnActionableFailure(
  turn: AgentCanvasChatTurnV2 | null | undefined,
): ActionableFailureV1 | null {
  return turn?.actionable_failure
    ?? turn?.operation_failure?.actionable_failure
    ?? null;
}

export function activityActionableFailure(
  activity: ChatCapabilityActivityV2,
  turn?: AgentCanvasChatTurnV2 | null,
): ActionableFailureV1 | null {
  return turnActionableFailure(turn) ?? activity.actionable_failure ?? null;
}

export function nodeActionableFailure(node: {
  error?: { actionable_failure?: ActionableFailureV1 | null } | null;
  latest_attempt?: {
    error?: { actionable_failure?: ActionableFailureV1 | null } | null;
  } | null;
}): ActionableFailureV1 | null {
  return node.latest_attempt?.error?.actionable_failure
    ?? node.error?.actionable_failure
    ?? null;
}

export function canRetryNodeExecution(node: CanvasNodeV2): boolean {
  return canRetryFailureInScope(nodeActionableFailure(node), "execution");
}
