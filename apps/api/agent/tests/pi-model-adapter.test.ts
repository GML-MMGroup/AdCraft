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
  thinkingFormatForCredential,
  toolChoiceForRequest,
  toolsForRequest,
} from "../src/pi-model-adapter.js";

describe("Pi model adapter", () => {
  it("uses the immutable policy thinking format", () => {
    expect(
      thinkingFormatForCredential({
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
        execution_policy: proposalPolicy(),
      }),
    ).toBe("zai");
  });

  it("does not derive thinking format from provider identity", () => {
    expect(
      thinkingFormatForCredential({
        ...siliconFlowCredential(),
        provider: "another-openai-compatible-provider",
        base_url: "https://example.invalid/v1",
      }),
    ).toBe("zai");
  });

  it("rejects unsupported streamed tools instead of buffering a stream", () => {
    expect(() =>
      modelStreamForCredential(
        arkModel(),
        arkContext(),
        { apiKey: "test-key" },
        {
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
          execution_policy: {
            ...proposalPolicy(),
            model_ref: "volcengine_ark:configured-model",
          },
        },
      ),
    ).toThrow("agent_model_capability_mismatch");
  });

  it("reassembles Ark fragmented structured tool calls", async () => {
    const submission = {
      assistant_message: "I will prepare the requested canvas draft.",
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
      agent_name: "video_agent",
      operation: "command_replan",
      deadline_at: "2026-07-29T12:10:00Z",
      model_policy_id: "video_agent.command_replan.v1",
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

  it("includes validated lean context in turn-intent prompts", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_guidance_context",
      request_id: "req_guidance_context",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_guidance",
      agent_name: "video_agent",
      operation: "decide_turn_intent",
      deadline_at: "2026-07-31T12:10:00Z",
      model_policy_id: "video_agent.decide_turn_intent.v1",
      contract_name: "TurnIntentDecisionV1",
      context: {
        workflow_id: "adwf_v2_context",
        workflow_revision: 2,
        conversation_id: "conversation_context",
        user_input: "Create a complete smartphone advertisement.",
        session_exists: false,
        mentioned_node_ids: [],
        mentioned_image_asset_ids: [],
      },
      contract_schema: {
        type: "object",
        properties: { action: { type: "string" } },
      },
    } satisfies AgentRunRequest;

    const prompt = promptInputForRequest(request);

    expect(prompt).toContain("Create a complete smartphone advertisement.");
    expect(prompt).toContain('"session_exists":false');
    expect(prompt).not.toContain("topic_ownership");
    expect(prompt).not.toContain("contract_schema");
  });

  it("uses the creative goal as the Quick Media materialization request", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_materialize_quick_media",
      request_id: "req_materialize_quick_media",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_materialize_quick_media",
      agent_name: "video_agent",
      operation: "materialize_quick_media",
      deadline_at: "2026-08-08T12:10:00Z",
      model_policy_id: "video_agent.materialize_quick_media.v1",
      contract_name: "QuickMediaMaterializationResultV1",
      context: {
        context_kind: "capability_materialization",
        workflow_id: "adwf_v2_materialization",
        conversation_id: "conversation_materialization",
        capability_id: "quick_media",
        selected_option: {
          option_id: "option_product_one",
          title: "Refreshing ritual",
          public_summary: "Present the bottled tea as a crisp daily reset.",
          key_decisions: ["Keep the bottle label legible."],
        },
        creative_goal: "Create a concise bottled-tea advertisement.",
      },
    } satisfies AgentRunRequest;

    const prompt = promptInputForRequest(request);

    expect(prompt).toContain(
      "User request:\nCreate a concise bottled-tea advertisement.",
    );
    expect(prompt).toContain('"context_kind":"capability_materialization"');
    expect(prompt).toContain('"option_id":"option_product_one"');
  });

  it("uses direct video parameter sources as the compilation request", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_video_parameters",
      request_id: "req_video_parameters",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_video_parameters",
      agent_name: "video_agent",
      operation: "compile_video_parameters",
      deadline_at: "2026-08-08T12:10:00Z",
      model_policy_id: "video_agent.compile_video_parameters.v1",
      contract_name: "VideoParameterIntentV2",
      context: {
        context_kind: "video_parameter_intent",
        workflow_id: "adwf_v2_parameters",
        target_node_id: "node_video",
        target_node_revision: 1,
        selected_model_ref: "volcengine_ark:seedance",
        sources: [
          {
            source_kind: "node_prompt",
            source_node_id: "node_video",
            source_revision: 1,
            text: "Render for five seconds at 16:9.",
          },
        ],
        capability: {
          supported_parameters: ["duration_seconds", "aspect_ratio"],
          supported_aspect_ratios: ["16:9"],
          supports_native_audio: true,
          capability_revision: 1,
        },
      },
    } satisfies AgentRunRequest;

    const prompt = promptInputForRequest(request);

    expect(prompt).toContain("User request:\nRender for five seconds at 16:9.");
    expect(prompt).toContain('"context_kind":"video_parameter_intent"');
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

  it("limits every operation to structured result submission", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_targeted",
      request_id: "req_targeted",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_targeted",
      agent_name: "video_agent",
      operation: "propose_character_options",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "video_agent.propose_character_options.v1",
      contract_name: "CharacterProposalResultV1",
      context: {
        context_kind: "capability_operation",
        workflow_id: "adwf_v2_context",
        conversation_id: "conversation_context",
        capability_id: "character_design",
        objective: "Create Character options.",
        context_snapshot_id: "snapshot_character",
        context_snapshot_digest: "b".repeat(64),
        approved_reference_ids: [],
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
    const defaultRequest = { ...request, audit_metadata: {} };
    expect(toolsForRequest(defaultRequest)).toEqual(["submit_structured_result"]);
    expect(
      toolChoiceForRequest(defaultRequest),
    ).toEqual({
      type: "function",
      function: { name: "submit_structured_result" },
    });
  });

  it("uses the requested contract schema for structured submission", () => {
    const request = {
      protocol_version: "1",
      run_id: "arun_contract",
      request_id: "req_contract",
      contract_digest: "a".repeat(64),
      context_snapshot_id: "context_contract",
      agent_name: "video_agent",
      operation: "decide_turn_intent",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "video_agent.decide_turn_intent.v1",
      contract_name: "TurnIntentDecisionV1",
      context: {
        operation: "decide_turn_intent",
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
      agent_name: "video_agent",
      operation: "decide_turn_intent",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "video_agent.decide_turn_intent.v1",
      contract_name: "TurnIntentDecisionV1",
      context: {
        workflow_id: "adwf_v2_context",
        workflow_revision: 1,
        conversation_id: "conversation_context",
        user_input: "Create an ad.",
        session_exists: false,
        mentioned_node_ids: [],
        mentioned_image_asset_ids: [],
      },
    } satisfies AgentRunRequest;

    expect(promptAuditForRequest(request)).toMatchObject({
      prompt_id: "adcraft.video_agent.decide_turn_intent.v1",
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
      agent_name: "video_agent",
      operation: "propose_character_options",
      deadline_at: "2026-07-24T12:10:00Z",
      model_policy_id: "video_agent.propose_character_options.v1",
      contract_name: "CharacterProposalResultV1",
      context: {
        context_kind: "capability_operation",
        workflow_id: "adwf_v2_context",
        conversation_id: "conversation_context",
        capability_id: "character_design",
        objective: "Create a Character brief.",
        context_snapshot_id: "snapshot_character",
        context_snapshot_digest: "b".repeat(64),
        approved_reference_ids: [],
      },
    } satisfies AgentRunRequest;

    const audit = agentRuntimeAuditForRequest(request, {
        protocol_version: "1",
        provider: "OpenAI Compatible",
        model_ref: "volcengine_ark:actual-character-model",
        model_id: "actual-character-model",
        model_policy_id: "video_agent.propose_character_options.v1",
        base_url: "https://llm.example/v1",
        api_key: "private-key",
        supports_tool_calls: true,
        supports_strict_structured_output: true,
        supports_streaming: true,
        supports_streamed_tool_calls: false,
        supports_reasoning_controls: false,
        execution_policy: {
          ...proposalPolicy(),
          model_ref: "volcengine_ark:actual-character-model",
        },
      }, [
        {
          skill_id: "video_agent_character_design",
          version: "1",
          sha256: "a".repeat(64),
          content: "private skill content",
        },
      ], 2);

    expect(audit).toMatchObject({
      provider: "OpenAI Compatible",
      model_id: "actual-character-model",
      model_policy_id: "video_agent.propose_character_options.v1",
      prompt_id: "adcraft.video_agent.propose_character_options.v1",
      structured_attempts: 2,
      repair_stage: "repair",
      skills: [
        {
          skill_id: "video_agent_character_design",
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

function siliconFlowCredential() {
  return {
    protocol_version: "1" as const,
    provider: "siliconflow",
    model_ref: "siliconflow:zai-org/GLM-5.2",
    model_id: "zai-org/GLM-5.2",
    model_policy_id: "video_agent.propose_character_options.v1",
    base_url: "https://api.siliconflow.cn/v1",
    api_key: "private-key",
    supports_tool_calls: true,
    supports_strict_structured_output: true,
    supports_streaming: true,
    supports_streamed_tool_calls: false,
    supports_reasoning_controls: false,
    execution_policy: proposalPolicy(),
  };
}

function proposalPolicy() {
  return {
    model_ref: "siliconflow:zai-org/GLM-5.2",
    operation: "propose_character_options",
    operation_class: "proposal" as const,
    thinking_format: "zai" as const,
    reasoning_control: "provider_default" as const,
    structured_transport: "non_streaming_tool_call" as const,
    supports_tool_calls: true,
    supports_streamed_tool_calls: false,
    deadline_seconds: 300,
    max_output_tokens: 3072,
    transport_retry_limit: 1,
    structured_repair_limit: 1,
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
