import { describe, expect, it } from "vitest";

import type { ActionableFailureV1 } from "../../../types-v2.ts";
import {
  canRetryFailureInScope,
  failureUserAction,
  nodeActionableFailure,
} from "./actionableFailure.ts";

const retryTurn: ActionableFailureV1 = {
  failure_class: "transient",
  retry_scope: "turn",
  user_action: "retry",
  retryable: true,
};

describe("actionable failure policy", () => {
  it("authorizes retry only for the exact declared scope", () => {
    expect(canRetryFailureInScope(retryTurn, "turn")).toBe(true);
    expect(canRetryFailureInScope(retryTurn, "execution")).toBe(false);
  });

  it("does not treat the compatibility retryable boolean as authority", () => {
    expect(canRetryFailureInScope(undefined, "turn")).toBe(false);
    expect(canRetryFailureInScope({ ...retryTurn, user_action: "revise" }, "turn")).toBe(false);
  });

  it("preserves non-retry recovery actions for presentation", () => {
    expect(failureUserAction({
      failure_class: "deterministic",
      retry_scope: "none",
      user_action: "redesign",
      retryable: false,
    })).toBe("redesign");
  });

  it("uses the latest Node attempt as the authoritative recovery disposition", () => {
    const revise = {
      failure_class: "stale",
      retry_scope: "none",
      user_action: "revise",
      retryable: false,
    } as const;
    const retryExecution = {
      failure_class: "external",
      retry_scope: "execution",
      user_action: "retry",
      retryable: true,
    } as const;

    expect(nodeActionableFailure({
      error: { actionable_failure: revise },
      latest_attempt: { error: { actionable_failure: retryExecution } },
    })).toEqual(retryExecution);
    expect(nodeActionableFailure({
      error: { actionable_failure: revise },
      latest_attempt: null,
    })).toEqual(revise);
  });
});
