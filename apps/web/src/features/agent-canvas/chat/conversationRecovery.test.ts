import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/agentCanvasApi.ts";
import { conversationRecoveryFromError } from "./conversationRecovery.ts";

function apiError(status: number, code: string | undefined, message: string) {
  return new V2ApiError({
    status,
    code,
    message,
    details: {},
    violations: [],
    suggestedActions: [],
    payload: null,
  });
}

describe("conversationRecoveryFromError", () => {
  it("keeps message-send failures concise while preserving exact technical detail", () => {
    const recovery = conversationRecoveryFromError(
      "composer",
      apiError(500, "provider_unavailable", "Request failed with status 500"),
      { retryable: true },
    );

    expect(recovery).toEqual({
      scope: "composer",
      title: "Response could not be submitted",
      message: "Your message is still here. Try sending it again.",
      technicalDetail: "provider_unavailable: Request failed with status 500",
      action: "retry",
    });
    expect(`${recovery.title} ${recovery.message}`).not.toMatch(/Request failed|Invalid|\[\d+\]/i);
  });

  it("offers refresh for a timeline read failure", () => {
    expect(conversationRecoveryFromError(
      "timeline",
      new Error("Invalid chatTimeline.presentation_items[0]"),
    )).toMatchObject({
      scope: "timeline",
      title: "Conversation could not be refreshed",
      action: "refresh",
      technicalDetail: "Invalid chatTimeline.presentation_items[0]",
    });
  });

  it("does not invent retries for permission and contract failures", () => {
    expect(conversationRecoveryFromError(
      "workflow",
      apiError(403, "forbidden", "Not allowed"),
    )).toMatchObject({ action: "none" });
    expect(conversationRecoveryFromError(
      "workflow",
      apiError(422, "workflow_contract_invalid", "Invalid workflow.nodes[0]"),
    )).toMatchObject({ action: "none" });
  });

  it("asks the user to review refreshed authority after a stale response", () => {
    expect(conversationRecoveryFromError(
      "workflow",
      apiError(409, "guided_interaction_stale", "Revision no longer current"),
    )).toMatchObject({
      action: "review",
      title: "Conversation state changed",
    });
  });
});
