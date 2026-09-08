import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/agentCanvasApi.ts";
import {
  decisionDockIssueFromError,
  isDecisionDockStaleError,
  productSourceDecisionDockIssueFromCode,
  productSourceDecisionDockIssueFromError,
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

function apiErrorWithDetails(status: number, details: Record<string, unknown>) {
  return new V2ApiError({
    status,
    message: "Request rejected",
    details,
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

  it.each([
    [409, "revision_conflict"],
    [412, "precondition_failed"],
    [422, "interaction_revision_mismatch"],
  ])("recognizes status-based revision conflicts (%s)", (status, code) => {
    expect(isDecisionDockStaleError(apiError(status, code, "The submitted revision is no longer current."))).toBe(true);
    expect(decisionDockIssueFromError(apiError(status, code, "The submitted revision is no longer current.")))
      .toMatchObject({ retryable: true, fieldId: null });
  });

  it("recognizes an optimistic-lock payload when the gateway omits conflict text", () => {
    expect(isDecisionDockStaleError(apiErrorWithDetails(412, {
      expected_revision: 3,
      current_revision: 4,
    }))).toBe(true);
  });

  it("maps Product count and unreadable AssetVersion errors inside the Product Dock", () => {
    expect(productSourceDecisionDockIssueFromError(apiError(
      422,
      "guided_product_multiview_count_invalid",
      "Expected 2 through 8 images.",
    ))).toMatchObject({
      summary: "Select the required number of Product images and try again.",
      retryable: true,
    });
    expect(productSourceDecisionDockIssueFromError(apiError(
      422,
      "guided_product_asset_unreadable",
      "The selected AssetVersion is not Ready.",
    ))).toMatchObject({
      summary: "One of the selected Product images is unavailable. Replace it and try again.",
      retryable: true,
    });
  });

  it("maps Product compiler failures without discarding uploaded assets", () => {
    expect(productSourceDecisionDockIssueFromCode(
      "guided_product_multiview_compilation_failed",
    )).toEqual({
      summary: "The Product views could not be compiled. Your uploaded images are still available.",
      detail: "guided_product_multiview_compilation_failed",
      fieldId: null,
      retryable: true,
    });
    expect(productSourceDecisionDockIssueFromCode(
      "guided_product_ffmpeg_unavailable",
    ).summary).toContain("uploaded images are still available");
  });
});
