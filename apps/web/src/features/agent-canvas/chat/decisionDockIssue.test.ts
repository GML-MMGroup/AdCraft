import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/agentCanvasApi.ts";
import {
  decisionDockIssueFromError,
  isDecisionDockStaleError,
} from "./decisionDockIssue.ts";

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

describe("decisionDockIssueFromError", () => {
  it("maps duration validation to its field without exposing the code in summary", () => {
    const issue = decisionDockIssueFromError(apiError(
      422,
      "guided_duration_value_invalid",
      "Invalid questionnaire.answers[0].value",
    ));

    expect(issue).toEqual({
      summary: "Choose one of the supported duration values.",
      detail: "guided_duration_value_invalid: Invalid questionnaire.answers[0].value",
      fieldId: "production_duration_seconds",
      retryable: true,
    });
  });

  it("uses concise copy for generic validation and server failures", () => {
    expect(decisionDockIssueFromError(apiError(422, "guided_interaction_invalid", "Invalid field path")))
      .toMatchObject({ summary: "Review this response and try again.", retryable: true });
    expect(decisionDockIssueFromError(apiError(500, undefined, "Request failed with status 500")))
      .toMatchObject({
        summary: "The agent could not submit this response. Try again.",
        retryable: true,
      });
  });

  it("recognizes a network failure by its API error name", () => {
    const error = Object.assign(new Error("Failed to fetch"), { name: "V2NetworkError" });

    expect(decisionDockIssueFromError(error)).toMatchObject({
      summary: "Connection interrupted. Check your connection and try again.",
      retryable: true,
    });
  });

  it("classifies stale Guided Interaction authority", () => {
    expect(isDecisionDockStaleError(apiError(409, "guided_interaction_stale", "Stale"))).toBe(true);
    expect(isDecisionDockStaleError(apiError(409, "guidance_revision_conflict", "Conflict"))).toBe(true);
    expect(isDecisionDockStaleError(apiError(422, "guided_interaction_invalid", "Invalid"))).toBe(false);
  });
});
