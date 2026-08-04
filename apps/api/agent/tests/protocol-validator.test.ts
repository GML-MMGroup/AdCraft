import { describe, expect, it } from "vitest";

import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import { loadRuntimeManifest } from "../src/manifest.js";
import { validateAgentRunRequest } from "../src/protocol-validator.js";

const request: AgentRunRequest = {
  protocol_version: "1",
  run_id: "arun_protocol",
  request_id: "req_protocol",
  contract_digest: loadRuntimeManifest().contract_digest,
  context_snapshot_id: "context_protocol",
  agent_name: "director",
  operation: "conversation_turn",
  deadline_at: "2026-07-24T12:10:00Z",
  model_policy_id: "director.conversation_turn.v1",
  context: {
    operation: "workflow_creation",
    user_input: "Create a product launch workflow.",
  },
  policy: {
    max_turns: 4,
    max_tool_calls: 4,
    max_handoffs: 1,
    timeout_seconds: 2,
    max_input_bytes: 4096,
    max_output_bytes: 4096,
    max_event_bytes: 4096,
  },
  credential_ref: "llm-default",
};

describe("AgentRunRequest protocol validation", () => {
  it("accepts the complete generated envelope", () => {
    expect(validateAgentRunRequest(structuredClone(request))).toEqual(request);
  });

  it.each([
    ["unknown field", { ...request, unexpected: true }],
    ["protocol mismatch", { ...request, protocol_version: "2" }],
    ["policy bound", { ...request, policy: { ...request.policy, max_turns: 0 } }],
    [
      "missing nested input",
      { ...request, context: { ...request.context, user_input: undefined } },
    ],
    [
      "unknown nested field",
      { ...request, context: { ...request.context, unexpected: true } },
    ],
  ])("rejects %s", (_name, candidate) => {
    expect(() => validateAgentRunRequest(candidate)).toThrow(
      "agent_protocol_mismatch",
    );
  });
});
