import { describe, expect, it } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import {
  providerBalanceNoticeFromError,
  providerBalanceNoticeFromNode,
  providerBalanceNoticeFromNodeRuntime,
  providerBalanceNoticeFromRuntimeEvent,
  providerBalanceNoticeFromText,
} from "./providerBalanceNotice.ts";

function runtimeEvent(
  eventType: string,
  payload: Record<string, unknown>,
): CanvasRuntimeEventV2 {
  return {
    seq: 1,
    workflow_id: "adwf_test",
    event_type: eventType,
    project_id: null,
    execution_id: null,
    node_id: "node_1",
    asset_id: null,
    binding_id: null,
    conversation_id: null,
    turn_id: null,
    action_id: null,
    trace_id: null,
    span_id: null,
    transition_key: null,
    attempt: null,
    created_at: "2026-09-17T00:00:00Z",
    payload,
  };
}

describe("providerBalanceNotice", () => {
  it("labels the provider behind a model ref", () => {
    const notice = providerBalanceNoticeFromNode({
      model_ref: "volcengine_ark:doubao-seedream-4-5-251128",
      error: null,
      latest_attempt: {
        error: {
          code: "provider_request_failed",
          message: "The account is in arrears, please recharge.",
          retryable: false,
        },
      },
    });

    expect(notice?.providerLabel).toBe("火山方舟");
    expect(notice?.dedupeKey).toBe("provider-balance:volcengine_ark");
    expect(notice?.detail).toContain("arrears");
  });

  it("reads a Chinese balance rejection from the node error message", () => {
    const notice = providerBalanceNoticeFromNode({
      error: {
        code: "provider_generation_failed",
        message: "账户余额不足，请先充值后再试。",
        retryable: false,
      },
      model_summary: { provider_id: "openrouter" },
    });

    expect(notice?.providerId).toBe("openrouter");
    expect(notice?.providerLabel).toBe("OpenRouter");
  });

  it("accepts the quota codes the backend already emits", () => {
    expect(providerBalanceNoticeFromNode({
      error: {
        code: "bgm_provider_quota_exhausted",
        message: "BGM provider quota exhausted.",
        retryable: false,
      },
    })).not.toBeNull();
  });

  it("reports the live runtime error projection", () => {
    const notice = providerBalanceNoticeFromNodeRuntime(
      { model_ref: "minimax:music-1" },
      {
        code: "provider_task_failed",
        message: "Insufficient balance",
        retryable: false,
      },
    );

    expect(notice?.providerLabel).toBe("MiniMax");
  });

  it("reads a provider task failure event", () => {
    const notice = providerBalanceNoticeFromRuntimeEvent(runtimeEvent("provider_task_failed", {
      provider: "volcengine_ark",
      error_code: "provider_request_failed",
      error_message: "AccountOverdueError: the account is in arrears.",
    }));

    expect(notice?.providerLabel).toBe("火山方舟");
  });

  it("reads a failed node status event and ignores non-failed ones", () => {
    expect(providerBalanceNoticeFromRuntimeEvent(runtimeEvent("node_status_changed", {
      status: "failed",
      error_code: "provider_task_failed",
      error: "Your credit balance is insufficient.",
    }))).not.toBeNull();

    expect(providerBalanceNoticeFromRuntimeEvent(runtimeEvent("node_status_changed", {
      status: "completed",
      error: "Your credit balance is insufficient.",
    }))).toBeNull();
  });

  it("maps a 402 API rejection without provider text", () => {
    const notice = providerBalanceNoticeFromError(new V2ApiError({
      status: 402,
      code: "provider_request_failed",
      message: "Payment required.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));

    expect(notice?.dedupeKey).toBe("provider-balance:unknown");
    expect(notice?.providerLabel).toBe("模型供应商");
  });

  it("does not treat ordinary provider failures as billing failures", () => {
    expect(providerBalanceNoticeFromText(
      "The provider rate limit or quota was hit. Wait a moment and retry.",
    )).toBeNull();
    expect(providerBalanceNoticeFromText("Invalid API key")).toBeNull();
    expect(providerBalanceNoticeFromText("Provider generation failed.")).toBeNull();
    expect(providerBalanceNoticeFromNode({
      error: {
        code: "provider_request_failed",
        message: "The model is not activated on this account.",
        retryable: false,
      },
    })).toBeNull();
    expect(providerBalanceNoticeFromError(new V2ApiError({
      status: 429,
      code: "provider_rate_limited",
      message: "Too many requests.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }))).toBeNull();
  });
});
