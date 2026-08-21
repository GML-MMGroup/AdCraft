import { describe, expect, it } from "vitest";

import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import {
  AgentEventProjection,
  acceptedStructuredValue,
  agentRuntimeAuditForRequest,
  promptAuditForRequest,
  structuredToolParameters,
  toolChoiceForRequest,
  toolsForRequest,
} from "../src/pi-model-adapter.js";

describe("Pi model adapter", () => {
  it("captures asynchronous event projection failures without an unhandled rejection", async () => {
    let aborted = false;
    const projection = new AgentEventProjection(() => {
      aborted = true;
    });

    projection.add(Promise.reject(new Error("agent_run_budget_exceeded")));

    await expect(projection.settle()).rejects.toThrow(
      "agent_run_budget_exceeded",
    );
    expect(aborted).toBe(true);
  });

  it("unwraps the normalized business value from an accepted submission", () => {
    expect(
      acceptedStructuredValue({
        accepted: true,
        normalized_result_id: "normalized-one",
        value: {
          intent: "workflow_creation",
          should_start_workflow: true,
        },
        repair_allowed: false,
      }),
    ).toEqual({
      intent: "workflow_creation",
      should_start_workflow: true,
    });
  });

  it("limits structured-only specialist calls to result submission", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_targeted",
      request_id: "req_targeted",
      agent_name: "character_designer",
      operation: "targeted_revision",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "character_designer.targeted_revision.v1",
      contract_name: "SpecialistResult",
      context: {
        operation: "targeted_revision",
        user_input: "Refine only the selected Character.",
      },
      audit_metadata: {
        tool_mode: "structured_only",
      },
    } satisfies AgentRunRequest;

    expect(toolsForRequest(request)).toEqual(["submit_structured_result"]);
    expect(toolChoiceForRequest(request)).toEqual({
      type: "function",
      function: { name: "submit_structured_result" },
    });
    expect(
      toolsForRequest({
        ...request,
        audit_metadata: {},
      }),
    ).toContain("read_target_context");
    expect(
      toolChoiceForRequest({
        ...request,
        audit_metadata: {},
      }),
    ).toBeUndefined();
  });

  it("uses the requested contract schema for structured submission", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_contract",
      request_id: "req_contract",
      agent_name: "front_desk",
      operation: "workflow_creation",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "front_desk.workflow_creation.v1",
      contract_name: "FrontDeskIntentOutput",
      context: {
        operation: "workflow_creation",
        user_input: "Create an ad.",
        contract_schema: {
          type: "object",
          properties: {
            intent: { type: "string" },
            reply: { type: "string" },
          },
          required: ["intent", "reply"],
          additionalProperties: false,
        },
      },
      credential_ref: "llm-default",
    } satisfies AgentRunRequest;

    expect(structuredToolParameters(request)).toMatchObject({
      type: "object",
      required: ["intent", "reply"],
      additionalProperties: false,
    });
  });

  it("records the resolved planning prompt identity in terminal audit", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_audit",
      request_id: "req_audit",
      agent_name: "front_desk",
      operation: "workflow_creation",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "front_desk.workflow_creation.v1",
      contract_name: "FrontDeskIntentOutput",
      context: {
        operation: "workflow_creation",
        user_input: "Create an ad.",
      },
    } satisfies AgentRunRequest;

    expect(promptAuditForRequest(request)).toMatchObject({
      prompt_id: "adcraft.front_desk.workflow_creation.v1",
      prompt_version: "1",
      prompt_digest: expect.stringMatching(/^[a-f0-9]{64}$/),
    });
  });

  it("records the model policy and actual provider call identity", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_model_audit",
      request_id: "req_model_audit",
      agent_name: "character_designer",
      operation: "character_expert_brief",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "character_designer.character_expert_brief.v1",
      contract_name: "V2CharacterExpertPlan",
      context: {
        operation: "character_expert_brief",
        user_input: "Create a Character brief.",
      },
    } satisfies AgentRunRequest;

    const audit = agentRuntimeAuditForRequest(request, {
        protocol_version: "1",
        provider: "OpenAI Compatible",
        model_id: "actual-character-model",
        model_policy_id: "character_designer.character_expert_brief.v1",
        base_url: "https://llm.example/v1",
        api_key: "private-key",
      }, [
        {
          skill_id: "character_spec_extraction",
          version: "1",
          sha256: "a".repeat(64),
          content: "private skill content",
        },
      ], 2);

    expect(audit).toMatchObject({
      provider: "OpenAI Compatible",
      model_id: "actual-character-model",
      model_policy_id: "character_designer.character_expert_brief.v1",
      prompt_id: "adcraft.character_designer.expert_brief.v1",
      structured_attempts: 2,
      repair_stage: "repair",
      skills: [
        {
          skill_id: "character_spec_extraction",
          version: "1",
          sha256: "a".repeat(64),
        },
      ],
    });
    expect(JSON.stringify(audit)).not.toContain("private-key");
    expect(JSON.stringify(audit)).not.toContain("private skill content");
  });
});
