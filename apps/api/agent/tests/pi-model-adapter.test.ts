import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import type { Context, Model } from "@earendil-works/pi-ai";
import { describe, expect, it, vi } from "vitest";

import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import {
  AgentEventProjection,
  acceptedStructuredValue,
  agentRuntimeAuditForRequest,
  modelStreamForCredential,
  promptInputForRequest,
  promptAuditForRequest,
  structuredToolParameters,
  toolChoiceForRequest,
  toolsForRequest,
} from "../src/pi-model-adapter.js";

describe("Pi model adapter", () => {
  it("buffers structured tool events when streamed tool calls are unreliable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        arkToolCallResponse({ assistant_message: "Accepted." }),
      ),
    );
    try {
      const buffered = modelStreamForCredential(
        arkModel(),
        arkContext(),
        { apiKey: "test-key" },
        {
          protocol_version: "1",
          provider: "OpenAI Compatible",
          model_ref: "volcengine_ark:configured-model",
          model_id: "configured-model",
          model_policy_id: "director.conversation_turn.v1",
          base_url: "https://llm.example/v1",
          api_key: "private-key",
          supports_tool_calls: true,
          supports_strict_structured_output: true,
          supports_streaming: true,
          supports_streamed_tool_calls: false,
          supports_reasoning_controls: false,
        },
      );

      const events = await collectStream(buffered);

      expect(events.some((candidate) => candidate.type === "toolcall_end")).toBe(true);
      expect(events.at(-1)?.type).toBe("done");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("reassembles Ark fragmented structured tool calls", async () => {
    const submission = {
      assistant_message: "I will prepare the requested canvas draft.",
      specialist_handoff: "script_writer",
      proposal: null,
      command_plan: null,
      auto_continue_requested: false,
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      arkToolCallResponse(submission),
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      const events = await collectStream(
        streamSimple(arkModel(), arkContext(), { apiKey: "test-key" }),
      );
      const structuredCallbacks = events.filter(
        (candidate) => candidate.type === "toolcall_end",
      );
      const terminals = events.filter((candidate) => candidate.type === "done");

      expect(structuredCallbacks).toHaveLength(1);
      expect(structuredCallbacks[0]).toMatchObject({
        toolCall: {
          id: "call_ark_fragmented",
          name: "submit_structured_result",
          arguments: submission,
        },
      });
      expect(terminals).toHaveLength(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("uses original intent with the bounded command replan context", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_replan",
      request_id: "req_replan",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_replan",
      agent_name: "director",
      operation: "command_replan",
      deadline_at: "2026-07-29T12:10:00Z",
      model_policy_id: "director.command_replan.v1",
      contract_name: "AgentCommandPlanDraftV2",
      context: {
        context_kind: "agent_command_replan",
        workflow_id: "adwf_v2_context",
        workflow_revision: 2,
        conversation_id: "conversation_context",
        original_user_intent: "Create one Hero image Draft.",
        original_plan_summary: "create_draft_node:create_hero",
        current_target_summaries: [],
        conflict_code: "workflow_revision_conflict",
      },
    } satisfies AgentRunRequest;

    const prompt = promptInputForRequest(request);

    expect(prompt).toContain("User request:\nCreate one Hero image Draft.");
    expect(prompt).toContain('"context_kind":"agent_command_replan"');
    expect(prompt).toContain('"conflict_code":"workflow_revision_conflict"');
  });

  it("includes validated typed context in progressive guidance prompts", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_guidance_context",
      request_id: "req_guidance_context",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_guidance",
      agent_name: "director",
      operation: "decide_next_guidance_step",
      deadline_at: "2026-07-31T12:10:00Z",
      model_policy_id: "director.decide_next_guidance_step.v1",
      contract_name: "NextGuidanceDecisionV2",
      context: {
        context_kind: "director_guidance",
        workflow_id: "adwf_v2_context",
        workflow_revision: 2,
        conversation_id: "conversation_context",
        user_input: "Create a complete smartphone advertisement.",
        conversation_summary: "The user wants one complete advertisement.",
        element_decisions: [],
        nodes: [],
        bindings: [],
        mentioned_node_ids: [],
        image_references: [],
        model_capabilities: {},
      },
      contract_schema: {
        type: "object",
        properties: { action: { type: "string" } },
      },
    } satisfies AgentRunRequest;

    const prompt = promptInputForRequest(request);

    expect(prompt).toContain("Create a complete smartphone advertisement.");
    expect(prompt).toContain('"context_kind":"director_guidance"');
    expect(prompt).toContain('"conversation_summary"');
    expect(prompt).not.toContain("contract_schema");
  });

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
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_targeted",
      agent_name: "character_designer",
      operation: "materialize_draft",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "character_designer.materialize_draft.v1",
      contract_name: "AgentActionEnvelopeV2",
      context: {
        operation: "materialize_draft",
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
    expect(toolsForRequest({ ...request, audit_metadata: {} })).toEqual([
      "submit_structured_result",
    ]);
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
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_contract",
      agent_name: "director",
      operation: "conversation_turn",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "director.conversation_turn.v1",
      contract_name: "AgentActionEnvelopeV2",
      context: {
        operation: "conversation_turn",
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
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_audit",
      agent_name: "director",
      operation: "conversation_turn",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "director.conversation_turn.v1",
      contract_name: "AgentActionEnvelopeV2",
      context: {
        operation: "conversation_turn",
        user_input: "Create an ad.",
      },
    } satisfies AgentRunRequest;

    expect(promptAuditForRequest(request)).toMatchObject({
      prompt_id: "adcraft.director.conversation_turn.v1",
      prompt_version: "1",
      prompt_digest: expect.stringMatching(/^[a-f0-9]{64}$/),
    });
  });

  it("records the model policy and actual provider call identity", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_model_audit",
      request_id: "req_model_audit",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_model_audit",
      agent_name: "character_designer",
      operation: "propose_concepts",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "character_designer.propose_concepts.v1",
      contract_name: "ConceptProposalDraftV2",
      context: {
        operation: "propose_concepts",
        user_input: "Create a Character brief.",
      },
    } satisfies AgentRunRequest;

    const audit = agentRuntimeAuditForRequest(request, {
        protocol_version: "1",
        provider: "OpenAI Compatible",
        model_ref: "volcengine_ark:actual-character-model",
        model_id: "actual-character-model",
        model_policy_id: "character_designer.propose_concepts.v1",
        base_url: "https://llm.example/v1",
        api_key: "private-key",
        supports_tool_calls: true,
        supports_strict_structured_output: true,
        supports_streaming: true,
        supports_streamed_tool_calls: false,
        supports_reasoning_controls: false,
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
      model_policy_id: "character_designer.propose_concepts.v1",
      prompt_id: "adcraft.character_designer.propose_concepts.v1",
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

function arkModel(): Model<"openai-completions"> {
  return {
    id: "ark-compatible-test-model",
    name: "Ark compatible test model",
    api: "openai-completions",
    provider: "ark-compatible-test",
    baseUrl: "https://ark.example/v1",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 16_384,
    maxTokens: 1_024,
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsUsageInStreaming: true,
      supportsStrictMode: true,
      maxTokensField: "max_tokens",
      thinkingFormat: "zai",
    },
  };
}

function arkContext(): Context {
  return {
    systemPrompt: "Return one complete AgentActionEnvelopeV2 through the required tool.",
    messages: [
      {
        role: "user",
        content: "Create a script draft.",
        timestamp: 0,
      },
    ],
    tools: [
      {
        name: "submit_structured_result",
        description: "Submit an AgentActionEnvelopeV2.",
        parameters: {
          type: "object",
          additionalProperties: false,
          required: ["assistant_message"],
          properties: {
            assistant_message: { type: "string" },
            specialist_handoff: { type: ["string", "null"] },
            proposal: { type: ["object", "null"] },
            command_plan: { type: ["object", "null"] },
            auto_continue_requested: { type: "boolean" },
          },
        },
      },
    ],
  };
}

function arkToolCallResponse(
  submission: Readonly<Record<string, unknown>>,
): Response {
  const chunks = [
    {
      id: "chatcmpl_ark_fragmented",
      model: "ark-compatible-test-model",
      choices: [
        {
          index: 0,
          delta: {
            tool_calls: [
              {
                index: 0,
                id: "call_ark_fragmented",
                type: "function",
                function: { name: "submit_structured_" },
              },
            ],
          },
        },
      ],
    },
    {
      id: "chatcmpl_ark_fragmented",
      model: "ark-compatible-test-model",
      choices: [
        {
          index: 0,
          delta: {
            tool_calls: [
              {
                index: 0,
                function: {
                  name: "result",
                  arguments: JSON.stringify(submission).slice(0, 67),
                },
              },
            ],
          },
        },
      ],
    },
    {
      id: "chatcmpl_ark_fragmented",
      model: "ark-compatible-test-model",
      choices: [
        {
          index: 0,
          delta: {
            tool_calls: [
              {
                index: 0,
                function: {
                  arguments: JSON.stringify(submission).slice(67),
                },
              },
            ],
          },
        },
      ],
    },
    {
      id: "chatcmpl_ark_fragmented",
      model: "ark-compatible-test-model",
      choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
    },
  ];
  const body = [
    ...chunks.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`),
    "data: [DONE]\n\n",
  ].join("");
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

async function collectStream<T>(stream: AsyncIterable<T>): Promise<T[]> {
  const events: T[] = [];
  for await (const event of stream) events.push(event);
  return events;
}
