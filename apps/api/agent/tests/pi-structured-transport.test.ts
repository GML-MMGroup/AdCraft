import { describe, expect, it, vi } from "vitest";

import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import type { AgentCredentialSnapshot } from "../src/python-internal-client.js";
import {
  PiStructuredTransportRouter,
  type StructuredCompletionExecutor,
} from "../src/pi-structured-transport.js";

describe("PiStructuredTransportRouter", () => {
  it("uses one non-streaming forced function request with the schema only in parameters", async () => {
    const execute = vi.fn<StructuredCompletionExecutor>().mockResolvedValue(
      toolResponse({ intent: "workflow_creation" }),
    );
    const submit = vi.fn().mockResolvedValue({
      status: "completed",
      result: { accepted: true, value: { intent: "workflow_creation" } },
    });

    const result = await new PiStructuredTransportRouter({ execute }).run({
      credential: glmCredential(),
      request: runRequest(),
      systemPrompt: "Call submit_structured_result with the final result.",
      userPrompt: "Create an advertisement.",
      schema: contractSchema,
      signal: new AbortController().signal,
      submit,
    });

    expect(result.value).toEqual({ intent: "workflow_creation" });
    expect(execute).toHaveBeenCalledOnce();
    const payload = execute.mock.calls[0]?.[0];
    expect(payload).toMatchObject({
      stream: false,
      max_tokens: 3072,
      tool_choice: {
        type: "function",
        function: { name: "submit_structured_result" },
      },
    });
    expect(payload?.tools?.[0]?.function.parameters).toEqual(contractSchema);
    expect(JSON.stringify(payload?.messages)).not.toContain(JSON.stringify(contractSchema));
    expect(payload).not.toHaveProperty("enable_thinking");
    expect(payload).not.toHaveProperty("thinking_budget");
    expect(payload).not.toHaveProperty("reasoning_effort");
    expect(submit).toHaveBeenCalledOnce();
    expect(result.audit).toMatchObject({
      structured_transport: "non_streaming_tool_call",
      thinking_format: "zai",
      reasoning_control: "provider_default",
      provider_trace_id: "chatcmpl_primary",
      finish_reason: "tool_calls",
      transport_retry_count: 0,
      structured_attempt_count: 1,
      input_tokens: 12,
      output_tokens: 8,
    });
    expect(JSON.stringify(result.audit)).not.toContain("private-key");
    expect(JSON.stringify(result.audit)).not.toContain("workflow_creation");
  });

  it("uses exactly one JSON Object repair and the same validator after a missing tool call", async () => {
    const execute = vi
      .fn<StructuredCompletionExecutor>()
      .mockResolvedValueOnce(textResponse("I omitted the tool."))
      .mockResolvedValueOnce(jsonResponse({ intent: "workflow_creation" }));
    const submit = vi.fn().mockResolvedValue({
      status: "completed",
      result: { accepted: true, value: { intent: "workflow_creation" } },
    });

    const result = await new PiStructuredTransportRouter({ execute }).run({
      credential: glmCredential(),
      request: runRequest(),
      systemPrompt: "Call the required function.",
      userPrompt: "Create an advertisement.",
      schema: contractSchema,
      signal: new AbortController().signal,
      submit,
    });

    expect(result.value).toEqual({ intent: "workflow_creation" });
    expect(execute).toHaveBeenCalledTimes(2);
    expect(execute.mock.calls[1]?.[0]).toMatchObject({
      stream: false,
      response_format: { type: "json_object" },
    });
    expect(execute.mock.calls[1]?.[0]).not.toHaveProperty("tools");
    expect(String(execute.mock.calls[1]?.[0].messages[1]?.content)).toContain(
      JSON.stringify(contractSchema),
    );
    expect(submit).toHaveBeenCalledOnce();
    expect(result.audit.structured_attempt_count).toBe(2);
  });

  it("does not issue a third model request when repair validation fails", async () => {
    const execute = vi
      .fn<StructuredCompletionExecutor>()
      .mockResolvedValueOnce(textResponse("Missing function call."))
      .mockResolvedValueOnce(jsonResponse({ intent: 1 }));
    const submit = vi.fn().mockResolvedValue({
      status: "failed",
      error_code: "agent_structured_output_invalid",
      result: { repair_allowed: false },
    });

    await expect(
      new PiStructuredTransportRouter({ execute }).run({
        credential: glmCredential(),
        request: runRequest(),
        systemPrompt: "Call the required function.",
        userPrompt: "Create an advertisement.",
        schema: contractSchema,
        signal: new AbortController().signal,
        submit,
      }),
    ).rejects.toThrow("agent_structured_output_invalid");

    expect(execute).toHaveBeenCalledTimes(2);
    expect(submit).toHaveBeenCalledOnce();
  });

  it("retries one pre-activity connection failure without changing run identity", async () => {
    const connectionError = Object.assign(new Error("connection reset"), {
      code: "ECONNRESET",
    });
    const execute = vi
      .fn<StructuredCompletionExecutor>()
      .mockRejectedValueOnce(connectionError)
      .mockResolvedValueOnce(toolResponse({ intent: "workflow_creation" }));

    const result = await new PiStructuredTransportRouter({
      execute,
      sleep: async () => undefined,
    }).run({
      credential: glmCredential(),
      request: runRequest(),
      systemPrompt: "Call the required function.",
      userPrompt: "Create an advertisement.",
      schema: contractSchema,
      signal: new AbortController().signal,
      submit: async () => ({
        status: "completed",
        result: { accepted: true, value: { intent: "workflow_creation" } },
      }),
    });

    expect(execute).toHaveBeenCalledTimes(2);
    expect(execute.mock.calls[0]?.[0]).toEqual(execute.mock.calls[1]?.[0]);
    expect(result.audit.transport_retry_count).toBe(1);
  });

  it("does not retry a connection failure after response activity", async () => {
    const error = Object.assign(new Error("connection reset"), {
      code: "ECONNRESET",
      response_started: true,
    });
    const execute = vi.fn<StructuredCompletionExecutor>().mockRejectedValue(error);

    await expect(
      new PiStructuredTransportRouter({ execute }).run({
        credential: glmCredential(),
        request: runRequest(),
        systemPrompt: "Call the required function.",
        userPrompt: "Create an advertisement.",
        schema: contractSchema,
        signal: new AbortController().signal,
        submit: vi.fn(),
      }),
    ).rejects.toThrow("agent_provider_transport_failed");

    expect(execute).toHaveBeenCalledOnce();
  });

  it("classifies an abort deadline without repair", async () => {
    const execute = vi.fn<StructuredCompletionExecutor>().mockRejectedValue(
      new DOMException("Timed out.", "TimeoutError"),
    );

    await expect(
      new PiStructuredTransportRouter({ execute }).run({
        credential: glmCredential(),
        request: runRequest(),
        systemPrompt: "Call the required function.",
        userPrompt: "Create an advertisement.",
        schema: contractSchema,
        signal: new AbortController().signal,
        submit: vi.fn(),
      }),
    ).rejects.toThrow("agent_provider_timeout");
    expect(execute).toHaveBeenCalledOnce();
  });
});

const contractSchema = {
  type: "object",
  properties: { intent: { type: "string" } },
  required: ["intent"],
  additionalProperties: false,
} as const;

function runRequest(): AgentRunRequest {
  return {
    protocol_version: "1",
    run_id: "arun_transport",
    request_id: "req_transport",
    contract_digest: "a".repeat(64),
    context_snapshot_id: "context_transport",
    agent_name: "video_agent",
    operation: "propose_product_options",
    deadline_at: "2026-08-09T16:00:00Z",
    model_policy_id: "video_agent.propose_product_options.v1",
    model_ref: "siliconflow:zai-org/GLM-5.2",
    contract_name: "ProductProposalResultV1",
    context: {
      context_kind: "capability_operation",
      workflow_id: "adwf_v2_transport",
      conversation_id: "conversation_transport",
      capability_id: "product_design",
      objective: "Create product options.",
      context_snapshot_id: "snapshot_transport",
      context_snapshot_digest: "b".repeat(64),
      approved_reference_ids: [],
    },
  };
}

function glmCredential(): AgentCredentialSnapshot {
  return {
    protocol_version: "1",
    provider: "siliconflow",
    model_ref: "siliconflow:zai-org/GLM-5.2",
    model_id: "zai-org/GLM-5.2",
    model_policy_id: "video_agent.propose_product_options.v1",
    base_url: "https://api.siliconflow.cn/v1",
    api_key: "private-key",
    supports_tool_calls: true,
    supports_strict_structured_output: true,
    supports_streaming: true,
    supports_streamed_tool_calls: false,
    supports_reasoning_controls: false,
    execution_policy: {
      model_ref: "siliconflow:zai-org/GLM-5.2",
      operation: "propose_product_options",
      operation_class: "proposal",
      thinking_format: "zai",
      reasoning_control: "provider_default",
      structured_transport: "non_streaming_tool_call",
      supports_tool_calls: true,
      supports_streamed_tool_calls: false,
      deadline_seconds: 300,
      max_output_tokens: 3072,
      transport_retry_limit: 1,
      structured_repair_limit: 1,
    },
  };
}

function toolResponse(value: Record<string, unknown>) {
  return {
    id: "chatcmpl_primary",
    choices: [
      {
        finish_reason: "tool_calls",
        message: {
          content: null,
          tool_calls: [
            {
              id: "call_primary",
              type: "function",
              function: {
                name: "submit_structured_result",
                arguments: JSON.stringify(value),
              },
            },
          ],
        },
      },
    ],
    usage: { prompt_tokens: 12, completion_tokens: 8, total_tokens: 20 },
  };
}

function textResponse(content: string) {
  return {
    id: "chatcmpl_missing",
    choices: [{ finish_reason: "stop", message: { content } }],
  };
}

function jsonResponse(value: Record<string, unknown>) {
  return {
    id: "chatcmpl_repair",
    choices: [
      { finish_reason: "stop", message: { content: JSON.stringify(value) } },
    ],
  };
}
