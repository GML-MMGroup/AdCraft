import { describe, expect, it, vi } from "vitest";

import { PythonInternalClient } from "../src/python-internal-client.js";

describe("PythonInternalClient", () => {
  it("uses internal auth and no-store config retrieval", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: "1",
          provider: "OpenAI Compatible",
          model_ref: "volcengine_ark:configured-model",
          model_id: "configured-model",
          model_policy_id: "video_agent.character_expert_brief.v1",
          base_url: "https://llm.example/v1",
          api_key: "private-key",
          supports_tool_calls: true,
          supports_strict_structured_output: true,
          supports_streaming: true,
          supports_streamed_tool_calls: false,
          supports_reasoning_controls: false,
          execution_policy: {
            model_ref: "volcengine_ark:configured-model",
            operation: "character_expert_brief",
            operation_class: "routing",
            thinking_format: "none",
            reasoning_control: "none",
            structured_transport: "non_streaming_tool_call",
            supports_tool_calls: true,
            supports_streamed_tool_calls: false,
            deadline_seconds: 120,
            max_output_tokens: 1024,
            transport_retry_limit: 1,
            structured_repair_limit: 1,
          },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = new PythonInternalClient({
      baseUrl: "http://backend:8000",
      internalToken: "internal-token",
      fetchImpl,
    });

    const snapshot = await client.credential(
      "llm-default",
      "arun_character",
      "video_agent",
      "character_expert_brief",
      "video_agent.character_expert_brief.v1",
      "volcengine_ark:configured-model",
    );

    expect(snapshot.model_id).toBe("configured-model");
    expect(snapshot.model_policy_id).toBe(
      "video_agent.character_expert_brief.v1",
    );
    expect(snapshot.supports_streamed_tool_calls).toBe(false);
    expect(snapshot.execution_policy.structured_transport).toBe(
      "non_streaming_tool_call",
    );
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://backend:8000/internal/v1/agent-runtime-config/llm-default?run_id=arun_character&agent_name=video_agent&operation=character_expert_brief&model_policy_id=video_agent.character_expert_brief.v1&model_ref=volcengine_ark%3Aconfigured-model",
      expect.objectContaining({
        headers: expect.objectContaining({
          authorization: "Bearer internal-token",
          "cache-control": "no-store",
        }),
      }),
    );
  });

  it.each([
    ["missing", undefined],
    [
      "unknown enum",
      {
        model_ref: "volcengine_ark:configured-model",
        operation: "workflow_conversation",
        operation_class: "routing",
        thinking_format: "other",
        reasoning_control: "none",
        structured_transport: "non_streaming_tool_call",
        supports_tool_calls: true,
        supports_streamed_tool_calls: false,
        deadline_seconds: 120,
        max_output_tokens: 1024,
        transport_retry_limit: 1,
        structured_repair_limit: 1,
      },
    ],
    [
      "contradictory transport",
      {
        model_ref: "volcengine_ark:configured-model",
        operation: "workflow_conversation",
        operation_class: "routing",
        thinking_format: "none",
        reasoning_control: "none",
        structured_transport: "streamed_tool_call",
        supports_tool_calls: true,
        supports_streamed_tool_calls: false,
        deadline_seconds: 120,
        max_output_tokens: 1024,
        transport_retry_limit: 1,
        structured_repair_limit: 1,
      },
    ],
  ])("rejects %s execution policy before dispatch", async (_label, executionPolicy) => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: "1",
          provider: "OpenAI Compatible",
          model_ref: "volcengine_ark:configured-model",
          model_id: "configured-model",
          model_policy_id: "video_agent.workflow_conversation.v1",
          base_url: "https://llm.example/v1",
          api_key: "private-key",
          supports_tool_calls: true,
          supports_strict_structured_output: true,
          supports_streaming: true,
          supports_streamed_tool_calls: false,
          supports_reasoning_controls: false,
          ...(executionPolicy === undefined
            ? {}
            : { execution_policy: executionPolicy }),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = new PythonInternalClient({
      baseUrl: "http://backend:8000",
      internalToken: "internal-token",
      fetchImpl,
    });

    await expect(
      client.credential(
        "llm-default",
        "arun_director",
        "video_agent",
        "workflow_conversation",
        "video_agent.workflow_conversation.v1",
        "volcengine_ark:configured-model",
      ),
    ).rejects.toThrow("agent_protocol_mismatch");
  });

  it("forwards only canonical tool calls", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          protocol_version: "1",
          run_id: "arun_one",
          tool_call_id: "call_one",
          status: "completed",
          result: { accepted: true },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = new PythonInternalClient({
      baseUrl: "http://backend:8000",
      internalToken: "internal-token",
      fetchImpl,
    });

    const result = await client.executeTool({
      protocol_version: "1",
      run_id: "arun_one",
      tool_call_id: "call_one",
      idempotency_key: "idem_one",
      tool_name: "submit_structured_result",
      arguments: {},
    });

    expect(result.status).toBe("completed");
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("preserves a structured broker failure instead of collapsing it", async () => {
    const client = new PythonInternalClient({
      baseUrl: "http://backend:8000",
      internalToken: "internal-token",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "provider_credentials_missing",
              message: "The selected provider text credential is not configured.",
            },
          }),
          { status: 503, headers: { "content-type": "application/json" } },
        ),
      ),
    });

    await expect(
      client.credential(
        "llm-default",
        "arun_director",
        "video_agent",
        "workflow_conversation",
        "video_agent.workflow_conversation.v1",
        "volcengine_ark:doubao-seed-2-0-mini-260428",
      ),
    ).rejects.toThrow("provider_credentials_missing");
  });
});
