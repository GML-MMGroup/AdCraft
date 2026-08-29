import { describe, expect, it } from "vitest";

import type {
  AgentRunRequest,
  AgentStructuredFallbackAuditV1,
} from "../src/generated/agent-runtime.js";
import {
  PiStructuredTransportRouter,
} from "../src/pi-structured-transport.js";

const fallbackAudit: AgentStructuredFallbackAuditV1 = {
  contract_name: "CompactTurnIntentDecisionV3",
  error_code: "agent_structured_fallback_applied",
  failure_codes: ["requirement_source_quote_invalid"],
  validation_paths: ["requirement_patch.controls_to_set.duration_seconds.source_quote"],
  submission_attempt: 2,
  used_model_message: true,
  reason: "validation_exhausted",
};

function input(
  execute: (request: unknown) => Promise<unknown>,
  submit: (value: Readonly<Record<string, unknown>>, attempt: number, toolCallId: string) =>
    Promise<{
      readonly status: string;
      readonly error_code?: string | null;
      readonly result?: Readonly<Record<string, unknown>>;
    }>,
  overrides: Partial<AgentRunRequest> = {},
) {
  const request = {
    protocol_version: "1",
    run_id: "run-1",
    request_id: "request-1",
    contract_digest: "a".repeat(64),
    context_snapshot_id: "snapshot-1",
    agent_name: "video_agent",
    operation: "decide_turn_intent",
    contract_name: "CompactTurnIntentDecisionV3",
    model_policy_id: "policy-1",
    model_ref: "model-1",
    deadline_at: new Date(Date.now() + 30_000).toISOString(),
    policy: {
      operation_policy_id: "policy-1",
      operation_class: "routing",
      timeout_seconds: 30,
      primary_timeout_seconds: 10,
      recovery_timeout_seconds: 10,
      persistence_reserve_seconds: 10,
      max_output_tokens: 128,
    },
    context: { operation: "decide_turn_intent", user_input: "hello" },
    ...overrides,
  } as unknown as AgentRunRequest;
  return {
    credential: {
      protocol_version: "1" as const,
      provider: "provider",
      model_ref: "model-1",
      model_id: "model-1",
      model_policy_id: "policy-1",
      base_url: "https://example.test/v1",
      supports_tool_calls: false,
      supports_strict_structured_output: true,
      supports_streaming: false,
      supports_streamed_tool_calls: false,
      supports_reasoning_controls: false,
      execution_policy: {
        model_ref: "model-1",
        operation: "decide_turn_intent",
        operation_class: "routing" as const,
        thinking_format: "none" as const,
        reasoning_control: "none" as const,
        reasoning_mode: "low" as const,
        enable_thinking: false,
        structured_transport: "non_streaming_json_object" as const,
        supports_tool_calls: false,
        supports_streamed_tool_calls: false,
        deadline_seconds: 30,
        primary_timeout_seconds: 10,
        recovery_timeout_seconds: 10,
        persistence_reserve_seconds: 10,
        max_model_submissions: 2 as const,
        recovery_mode: "structured_repair_only" as const,
        max_output_tokens: 128,
        transport_retry_limit: 0,
        structured_repair_limit: 1,
      },
      api_key: "secret",
    },
    request,
    systemPrompt: "system prompt",
    userPrompt: "user prompt",
    schema: { type: "object" },
    signal: new AbortController().signal,
    submit,
    execute,
  };
}

function response(content: string) {
  return { choices: [{ message: { content }, finish_reason: "stop" }] };
}

function rejected() {
  return {
    status: "failed",
    error_code: "agent_structured_output_invalid",
    result: {
      accepted: false,
      repair_allowed: true,
      violations: [{ path: "$.objective", code: "invalid", message: "invalid" }],
    },
  };
}

describe("Pi structured transport safe intake fallback", () => {
  it("returns a normally accepted repaired result", async () => {
    const submissions: Array<Readonly<Record<string, unknown>>> = [];
    let call = 0;
    const router = new PiStructuredTransportRouter({
      execute: async () => {
        call += 1;
        return response(call === 1 ? '{"mode":"ordinary_conversation","objective":"x"}' : '{"mode":"ordinary_conversation","objective":"repaired"}');
      },
    });
    const result = await router.run(input(async () => response("{}"), async (value, attempt, toolCallId) => {
      submissions.push({ value, attempt, toolCallId });
      return attempt === 1 ? rejected() : { status: "completed", result: { accepted: true, value } };
    }));
    expect(result.value).toEqual({ mode: "ordinary_conversation", objective: "repaired" });
    expect(submissions).toHaveLength(2);
  });

  it("uses the trusted Python fallback returned by a rejected second submission", async () => {
    const router = new PiStructuredTransportRouter({
      execute: async (request) => response(JSON.stringify({ mode: "ordinary_conversation", objective: request ? "candidate" : "" })),
    });
    const result = await router.run(input(async () => response("{}"), async (_value, attempt) => {
      if (attempt === 1) return rejected();
      return {
        status: "completed",
        result: { accepted: true, value: { mode: "ordinary_conversation", objective: "fallback", assistant_message: "safe" }, fallback_audit: fallbackAudit },
      };
    }));
    expect(result.value.objective).toBe("fallback");
    expect(result.audit.structured_fallback).toEqual(fallbackAudit);
  });

  it("submits a canonical fallback when the repaired JSON is malformed for intake", async () => {
    const calls: Array<{ value: Readonly<Record<string, unknown>>; attempt: number; toolCallId: string }> = [];
    let modelCall = 0;
    const router = new PiStructuredTransportRouter({
      execute: async () => {
        modelCall += 1;
        return response(modelCall === 1 ? JSON.stringify({ mode: "ordinary_conversation", objective: "x", assistant_message: "我们将开始执行计划并修改你的项目" }) : "{malformed");
      },
    });
    const result = await router.run(input(async () => response("{}"), async (value, attempt, toolCallId) => {
      calls.push({ value, attempt, toolCallId });
      return attempt === 1 ? rejected() : { status: "completed", result: { accepted: true, value, fallback_audit: { ...fallbackAudit, failure_codes: [], validation_paths: [], used_model_message: true, reason: "repair_json_invalid" } } };
    }));
    expect(calls[1]).toEqual({
      attempt: 2,
      toolCallId: "call_structured_fallback",
      value: {
        mode: "ordinary_conversation",
        objective: "Preserve a safe conversational response after structured validation failed.",
        assistant_message: "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。",
      },
    });
    expect(result.value.assistant_message).toBe("已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。");
    expect(result.audit.structured_fallback).toMatchObject({ reason: "repair_json_invalid", used_model_message: false });
  });

  it("does not fallback for malformed repairs on other contracts", async () => {
    let submissions = 0;
    let modelCall = 0;
    const router = new PiStructuredTransportRouter({
      execute: async () => {
        modelCall += 1;
        return response(modelCall === 1 ? '{"mode":"ordinary_conversation","objective":"x"}' : "{malformed");
      },
    });
    await expect(router.run(input(async () => response('{"mode":"ordinary_conversation","objective":"x"}'), async () => {
      submissions += 1;
      return rejected();
    }, { operation: "workflow_creation", contract_name: "OtherContract" }))).rejects.toThrow("agent_structured_output_invalid");
    expect(submissions).toBe(1);
  });

  it("keeps audit metadata bounded and excludes model text, prompts, and candidates", async () => {
    const candidate = "secret-candidate";
    let modelCall = 0;
    const router = new PiStructuredTransportRouter({
      execute: async () => {
        modelCall += 1;
        return response(modelCall === 1 ? JSON.stringify({ mode: "ordinary_conversation", objective: candidate, assistant_message: candidate }) : "{malformed");
      },
    });
    const result = await router.run(input(async () => response(JSON.stringify({ mode: "ordinary_conversation", objective: candidate, assistant_message: candidate })), async (value, attempt) =>
      attempt === 1 ? rejected() : { status: "completed", result: { accepted: true, value, fallback_audit: { ...fallbackAudit, failure_codes: [], validation_paths: [], used_model_message: false, reason: "repair_json_invalid" } } },
    ));
    expect(JSON.stringify(result.audit)).not.toContain(candidate);
    expect(JSON.stringify(result.audit)).not.toContain("system prompt");
    expect(JSON.stringify(result.audit)).not.toContain("user prompt");
    expect(result.audit.structured_fallback).toBeDefined();
    expect(result.value.assistant_message).toBe("已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。");
  });
});
