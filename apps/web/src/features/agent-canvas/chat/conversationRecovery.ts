import { isV2ApiError } from "../../../api/agentCanvasApi.ts";

export type ConversationRecoveryScope =
  | "interaction"
  | "composer"
  | "context"
  | "timeline"
  | "workflow";

export interface ConversationRecoveryView {
  scope: ConversationRecoveryScope;
  title: string;
  message: string;
  technicalDetail: string | null;
  action: "retry" | "refresh" | "review" | "none";
}

const STALE_AUTHORITY_CODES = new Set([
  "guided_interaction_stale",
  "guided_action_stale",
  "guided_action_superseded",
  "guidance_revision_conflict",
  "journey_revision_conflict",
  "proposal_action_stale",
]);

function technicalDetail(error: unknown): string | null {
  if (isV2ApiError(error)) {
    return error.code ? `${error.code}: ${error.message}` : error.message;
  }
  return error instanceof Error ? error.message : null;
}

function scopeCopy(scope: Exclude<ConversationRecoveryScope, "interaction">) {
  if (scope === "composer") {
    return {
      title: "Response could not be submitted",
      message: "Your message is still here. Try sending it again.",
    };
  }
  if (scope === "context") {
    return {
      title: "Context could not be updated",
      message: "Your current message context was preserved.",
    };
  }
  if (scope === "timeline") {
    return {
      title: "Conversation could not be refreshed",
      message: "The last available conversation is still shown.",
    };
  }
  return {
    title: "Agent workspace could not be refreshed",
    message: "Your current workspace state was preserved.",
  };
}

export function conversationRecoveryFromError(
  scope: Exclude<ConversationRecoveryScope, "interaction">,
  error: unknown,
  options: { retryable?: boolean } = {},
): ConversationRecoveryView {
  const copy = scopeCopy(scope);
  const detail = technicalDetail(error);

  if (isV2ApiError(error) && error.code && STALE_AUTHORITY_CODES.has(error.code)) {
    return {
      scope,
      title: "Conversation state changed",
      message: "Review the latest state before trying again.",
      technicalDetail: detail,
      action: "review",
    };
  }

  const isPermissionFailure = isV2ApiError(error) && (error.status === 401 || error.status === 403);
  const isContractFailure = isV2ApiError(error) && error.status === 422 && scope === "workflow";
  let action: ConversationRecoveryView["action"] = "none";
  if (!isPermissionFailure && !isContractFailure) {
    if (scope === "timeline" || scope === "workflow") action = "refresh";
    else if (options.retryable) action = "retry";
  }

  return {
    scope,
    ...copy,
    technicalDetail: detail,
    action,
  };
}
