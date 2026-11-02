import { describe, expect, it, vi } from "vitest";

import { modelIdForCredential } from "../src/pi-model-adapter.js";
import { buildPrimaryStructuredCompletionRequest } from "../src/pi-structured-transport.js";
import {
  PythonInternalClient,
  type AgentCredentialSnapshot,
} from "../src/python-internal-client.js";

function credential(modelId: string): AgentCredentialSnapshot {
  return {
    protocol_version: "1",
    source_kind: "provider",
    provider: "volcengine_ark",
    model_ref: "volcengine_ark:selected-model",
    model_id: modelId,
    model_policy_id: "video_agent.decide_turn_intent.v1",
    base_url: "https://unused.invalid/v1",
    api_key: "test-key",
    trace_mode: "disabled",
    supports_tool_calls: true,
    supports_strict_structured_output: false,
    supports_streaming: false,
    supports_streamed_tool_calls: false,
    supports_reasoning_controls: false,
    execution_policy: {
      model_ref: "volcengine_ark:selected-model",
      operation: "decide_turn_intent",
      operation_class: "routing",
      thinking_format: "none",
      reasoning_control: "none",
      reasoning_mode: "low",
      enable_thinking: false,
      thinking_budget_tokens: null,
      reasoning_effort: null,
      structured_transport: "non_streaming_tool_call",
      supports_tool_calls: true,
      supports_streamed_tool_calls: false,
      deadline_seconds: 5,
      primary_timeout_seconds: 4,
      recovery_timeout_seconds: 0,
      persistence_reserve_seconds: 1,
      max_model_submissions: 1,
      recovery_mode: "none",
      max_output_tokens: 32,
      transport_retry_limit: 0,
      structured_repair_limit: 0,
    },
  };
}

function loadSource(payload: Record<string, unknown>) {
  const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify(payload)),
  );
  const client = new PythonInternalClient({
    baseUrl: "https://unused.invalid",
    internalToken: "test-token",
    fetchImpl,
  });
  return client.runtimeSource(
    "test-credential",
    "test-run",
    "video_agent",
    "decide_turn_intent",
    "video_agent.decide_turn_intent.v1",
    "volcengine_ark:selected-model",
  );
}

describe("runtime model identity", () => {
  it.each([undefined, null, "", " ", "\t\n"])(
    "rejects absent or blank provider model_id %j",
    async (modelId) => {
      await expect(loadSource({
        ...credential("selected-model"),
        model_id: modelId,
      })).rejects.toThrow("agent_protocol_mismatch");
    },
  );

  it.each(["", " \t\n"])(
    "does not use a gateway alias to replace blank provider model_id %j",
    async (modelId) => {
      await expect(loadSource({
        ...credential(modelId),
        transport_kind: "litellm_chat",
        adapter_id: "test-adapter",
        adapter_revision: "1",
        capability_revision: "1",
        gateway_id: "test-gateway",
        model_alias: "valid-gateway-alias",
        projection_digest: `sha256:${"a".repeat(64)}`,
      })).rejects.toThrow("agent_protocol_mismatch");
    },
  );

  it.each([
    "doubao-seed-2-1-pro",
    "doubao-seed-2-1-pro-260628",
    "ep-custom-endpoint",
    "  exact-nonempty-id\t",
  ])("passes the nonempty explicit model ID through unchanged: %j", async (modelId) => {
    const source = await loadSource({ ...credential(modelId) });
    expect(source.model_id).toBe(modelId);
    expect(modelIdForCredential(credential(modelId))).toBe(modelId);
    expect(buildPrimaryStructuredCompletionRequest({
      credential: source,
      systemPrompt: "Test prompt",
      userPrompt: "Test input",
      schema: { type: "object" },
    }).model).toBe(modelId);
  });
});
