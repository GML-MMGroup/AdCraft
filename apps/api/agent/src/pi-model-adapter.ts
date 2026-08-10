import { Agent, type AgentEvent, type AgentTool } from "@earendil-works/pi-agent-core";
import {
  Type,
  type AssistantMessageEventStream,
  type Context,
  type Model,
  type SimpleStreamOptions,
} from "@earendil-works/pi-ai";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";

import type {
  AgentRunRequest,
  AgentRuntimeEvent,
} from "./generated/agent-runtime.js";
import type { RunBudget } from "./run-budget.js";
import type { AgentModelAdapter, EventSink } from "./runtime.js";
import { event } from "./runtime.js";
import {
  PythonInternalClient,
  type AgentCredentialSnapshot,
} from "./python-internal-client.js";
import { runWithOneTransportRetry } from "./operation-recovery.js";
import { PiStructuredTransportRouter } from "./pi-structured-transport.js";
import {
  structuredRepairPrompt,
  structuredSubmissionPrompt,
} from "./prompts/agents.js";
import { getPromptDescriptor } from "./prompts/registry.js";
import {
  getAgentDefinition,
  getOperationDescriptor,
  toolsForOperation,
  type AgentToolName,
} from "./registry.js";
import { loadRequiredSkills, type LoadedSkill } from "./skills.js";

const structuredValueSchema = Type.Record(Type.String(), Type.Unknown());

export class PiModelAdapter implements AgentModelAdapter {
  constructor(
    private readonly python: PythonInternalClient,
    private readonly structuredTransport = new PiStructuredTransportRouter(),
  ) {}

  async run(
    request: AgentRunRequest,
    signal: AbortSignal,
    emit: EventSink,
    budget?: RunBudget,
  ): Promise<Record<string, unknown>> {
    budget?.consumeTurn();
    const definition = getAgentDefinition(request.agent_name);
    if (!definition.operations.includes(request.operation)) {
      throw new Error("agent_operation_not_allowed");
    }
    const promptDescriptor = getPromptDescriptor(
      request.operation,
      request.contract_name ?? "",
    );
    if (!request.model_ref) throw new Error("agent_protocol_mismatch");
    const credential = await this.python.credential(
      request.credential_ref ?? "llm-default",
      request.run_id,
      request.agent_name,
      request.operation,
      request.model_policy_id,
      request.model_ref,
    );
    validateCredentialExecutionPolicy(request, credential);
    const operationDescriptor = getOperationDescriptor(request.operation);
    const skills = await loadRequiredSkills(operationDescriptor);
    const skillContext = skills
      .map(
        (skill) =>
          `Skill: ${skill.skill_id}\nDigest: ${skill.sha256}\n\n${skill.content}`,
      )
      .join("\n\n---\n\n");
    let acceptedResult: Record<string, unknown> | undefined;
    let attempts = 0;
    const maximumStructuredAttempts =
      1 + credential.execution_policy.structured_repair_limit;
    const submitStructured = async (
      params: Readonly<Record<string, unknown>>,
      attempt: number,
      toolCallId: string,
    ) => {
      budget?.consumeToolCall();
      attempts = Math.max(attempts, attempt);
      if (attempt > maximumStructuredAttempts) {
        throw new Error("agent_structured_output_invalid");
      }
      const result = await this.python.executeTool({
        protocol_version: "1",
        run_id: request.run_id,
        tool_call_id: toolCallId,
        idempotency_key: `${request.run_id}:structured:${attempt}`,
        tool_name: "submit_structured_result",
        arguments: {
          protocol_version: "1",
          run_id: request.run_id,
          submission_id: `${request.run_id}:submission:${attempt}`,
          contract_name: request.contract_name ?? "SpecialistDraft",
          value: params,
          attempt,
        },
      });
      await emit(
        event(request, 0, "tool_result", {
          tool_call_id: toolCallId,
          status: result.status,
          error_code: result.error_code,
        }),
      );
      return result;
    };
    const systemPrompt = [
      promptDescriptor.system_prompt,
      skillContext ? `Trusted skill context:\n\n${skillContext}` : "",
      structuredSubmissionPrompt,
      structuredRepairPrompt,
      `Required contract: ${request.contract_name ?? "SpecialistDraft"}.`,
    ]
      .filter(Boolean)
      .join("\n\n");
    if (credential.execution_policy.structured_transport === "non_streaming_tool_call") {
      const result = await this.structuredTransport.run({
        credential,
        request,
        systemPrompt,
        userPrompt: promptInputForRequest(request),
        schema: contractSchema(request),
        signal,
        submit: submitStructured,
      });
      return {
        ...result.value,
        agent_runtime_audit: {
          ...agentRuntimeAuditForRequest(request, credential, skills, attempts),
          ...result.audit,
        },
      };
    }
    if (
      credential.execution_policy.structured_transport !== "streamed_tool_call" ||
      !credential.execution_policy.supports_streamed_tool_calls
    ) {
      throw new Error("agent_model_capability_mismatch");
    }
    const thinkingFormat = thinkingFormatForCredential(credential);
    const model: Model<"openai-completions"> = {
      id: credential.model_id,
      name: credential.model_id,
      api: "openai-completions",
      provider: credential.provider,
      baseUrl: credential.base_url,
      reasoning: credential.execution_policy.thinking_format !== "none",
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 128_000,
      maxTokens: credential.execution_policy.max_output_tokens,
      compat: {
        supportsDeveloperRole: false,
        supportsReasoningEffort: false,
        supportsUsageInStreaming: true,
        supportsStrictMode: true,
        maxTokensField: "max_tokens",
        ...(thinkingFormat ? { thinkingFormat } : {}),
      },
    };
    const structuredTool: AgentTool<typeof structuredValueSchema> = {
      name: "submit_structured_result",
      label: "Submit structured result",
      description: "Submit the final validated result for this operation.",
      parameters: structuredToolParameters(request),
      execute: async (toolCallId, params) => {
        attempts += 1;
        const result = await submitStructured(params, attempts, toolCallId);
        if (result.status === "completed") {
          acceptedResult = acceptedStructuredValue(result.result);
        } else if (
          result.error_code === "agent_structured_output_invalid" &&
          (attempts >= maximumStructuredAttempts ||
            result.result?.repair_allowed !== true)
        ) {
          throw new Error("agent_structured_output_invalid");
        }
        return {
          content: [{ type: "text", text: JSON.stringify(result.result) }],
          details: result.result,
          terminate: result.status === "completed",
        };
      },
    };
    const tools: Array<AgentTool<typeof structuredValueSchema>> = [structuredTool];
    const toolChoice = toolChoiceForRequest(request);
    const runAttempt = async (): Promise<void> => {
      const agent = new Agent({
        initialState: {
          systemPrompt,
          model,
          tools,
        },
        streamFn: (selectedModel, context, options) => {
          const streamOptions = {
            ...options,
            apiKey: credential.api_key,
            ...(toolChoice ? { toolChoice } : {}),
          };
          return modelStreamForCredential(
            selectedModel as Model<"openai-completions">,
            context,
            streamOptions,
            credential,
          );
        },
      });
      const eventProjection = new AgentEventProjection(() => agent.abort());
      const unsubscribe = agent.subscribe((agentEvent) => {
        eventProjection.add(projectOutputDelta(request, agentEvent, emit));
      });
      const abort = () => agent.abort();
      signal.addEventListener("abort", abort, { once: true });
      try {
        let promptError: unknown;
        try {
          await agent.prompt(promptInputForRequest(request));
        } catch (error) {
          promptError = error;
        }
        await eventProjection.settle();
        if (promptError) throw promptError;
      } finally {
        signal.removeEventListener("abort", abort);
        unsubscribe();
      }
    };
    await runWithOneTransportRetry(runAttempt, {
      deadlineEpochMs: Date.parse(request.deadline_at),
    });
    if (!acceptedResult) throw new Error("agent_structured_output_invalid");
    return {
      ...acceptedResult,
      agent_runtime_audit: agentRuntimeAuditForRequest(
        request,
        credential,
        skills,
        attempts,
      ),
    };
  }

}

export function validateCredentialExecutionPolicy(
  request: AgentRunRequest,
  credential: AgentCredentialSnapshot,
): void {
  const runPolicy = request.policy;
  const executionPolicy = credential.execution_policy;
  if (
    credential.model_policy_id !== request.model_policy_id ||
    credential.model_ref !== request.model_ref ||
    executionPolicy.model_ref !== request.model_ref ||
    executionPolicy.operation !== request.operation ||
    !runPolicy?.operation_policy_id ||
    executionPolicy.operation_class !== runPolicy.operation_class ||
    executionPolicy.deadline_seconds !== runPolicy.timeout_seconds ||
    executionPolicy.transport_retry_limit !== runPolicy.transport_retry_limit ||
    executionPolicy.structured_repair_limit !== runPolicy.structured_repair_limit ||
    typeof runPolicy.max_output_tokens !== "number" ||
    executionPolicy.max_output_tokens > runPolicy.max_output_tokens ||
    !Number.isFinite(Date.parse(request.deadline_at))
  ) {
    throw new Error("agent_protocol_mismatch");
  }
}

export function thinkingFormatForCredential(
  credential: AgentCredentialSnapshot,
): "qwen" | "zai" | undefined {
  const format = credential.execution_policy.thinking_format;
  return format === "none" ? undefined : format;
}

export function modelStreamForCredential(
  model: Model<"openai-completions">,
  context: Context,
  options: SimpleStreamOptions,
  credential: AgentCredentialSnapshot,
  sourceFactory?: () => AssistantMessageEventStream,
): AssistantMessageEventStream {
  if (
    credential.execution_policy.structured_transport !== "streamed_tool_call" ||
    !credential.execution_policy.supports_streamed_tool_calls
  ) {
    throw new Error("agent_model_capability_mismatch");
  }
  return sourceFactory?.() ?? streamSimple(model, context, options);
}

export function toolsForRequest(
  request: AgentRunRequest,
): ReadonlyArray<AgentToolName> {
  return toolsForOperation(request.operation);
}

export function toolChoiceForRequest(
  request: AgentRunRequest,
):
  | {
      readonly type: "function";
      readonly function: { readonly name: "submit_structured_result" };
    }
  | undefined {
  return {
    type: "function",
    function: { name: "submit_structured_result" },
  };
}

export class AgentEventProjection {
  readonly #tasks = new Set<Promise<void>>();
  #failure: unknown;

  constructor(private readonly abort: () => void) {}

  add(task: Promise<void>): void {
    let tracked: Promise<void>;
    tracked = task
      .catch((error: unknown) => {
        if (this.#failure === undefined) this.#failure = error;
        this.abort();
      })
      .finally(() => {
        this.#tasks.delete(tracked);
      });
    this.#tasks.add(tracked);
  }

  async settle(): Promise<void> {
    await Promise.all(this.#tasks);
    if (this.#failure !== undefined) throw this.#failure;
  }
}

export function promptAuditForRequest(
  request: AgentRunRequest,
): Readonly<Record<string, string>> {
  const descriptor = getPromptDescriptor(
    request.operation,
    request.contract_name ?? "",
  );
  return {
    prompt_id: descriptor.prompt_id,
    prompt_version: descriptor.prompt_version,
    prompt_digest: descriptor.prompt_digest,
  };
}

export function agentRuntimeAuditForRequest(
  request: AgentRunRequest,
  credential: AgentCredentialSnapshot,
  skills: ReadonlyArray<LoadedSkill> = [],
  structuredAttempts = 0,
): Readonly<Record<string, unknown>> {
  return {
    ...promptAuditForRequest(request),
    provider: credential.provider,
    model_id: credential.model_id,
    model_policy_id: credential.model_policy_id,
    structured_attempts: structuredAttempts,
    repair_stage: structuredAttempts > 1 ? "repair" : "initial",
    skills: skills.map((skill) => ({
      skill_id: skill.skill_id,
      version: skill.version,
      sha256: skill.sha256,
    })),
  };
}

export function acceptedStructuredValue(
  result: Readonly<Record<string, unknown>> | undefined,
): Record<string, unknown> {
  if (!result || result.accepted !== true) {
    throw new Error("agent_structured_output_invalid");
  }
  const value = result.value ?? result.normalized_value;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("agent_structured_output_invalid");
  }
  return { ...value } as Record<string, unknown>;
}

export function structuredToolParameters(
  request: AgentRunRequest,
): typeof structuredValueSchema {
  const schema = contractSchema(request);
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    return structuredValueSchema;
  }
  return Type.Unsafe<Record<string, unknown>>(
    schema,
  ) as unknown as typeof structuredValueSchema;
}

function contractSchema(request: AgentRunRequest): Readonly<Record<string, unknown>> {
  if (
    request.contract_schema &&
    typeof request.contract_schema === "object" &&
    !Array.isArray(request.contract_schema)
  ) {
    return request.contract_schema;
  }
  return "contract_schema" in request.context &&
    request.context.contract_schema &&
    typeof request.context.contract_schema === "object" &&
    !Array.isArray(request.context.contract_schema)
    ? request.context.contract_schema
    : {};
}

export function promptInputForRequest(request: AgentRunRequest): string {
  const context = request.context as Readonly<Record<string, unknown>>;
  let primaryInput = [
    "user_input",
    "user_instruction",
    "original_user_intent",
    "objective",
    "creative_goal",
  ]
    .map((key) => context[key])
    .find((value): value is string => typeof value === "string" && value.length > 0);
  if (
    !primaryInput &&
    context.context_kind === "video_parameter_intent" &&
    Array.isArray(context.sources)
  ) {
    primaryInput = context.sources
      .map((source) =>
        source && typeof source === "object" && "text" in source
          ? (source as Readonly<Record<string, unknown>>).text
          : undefined,
      )
      .filter((value): value is string => typeof value === "string" && value.length > 0)
      .join("\n\n");
  }
  if (!primaryInput) throw new Error("agent_context_input_missing");
  const hasTypedOperationContext =
    "context_kind" in request.context ||
    "session_exists" in request.context ||
    "capability_id" in request.context ||
    "policy" in request.context;
  if (!hasTypedOperationContext) return primaryInput;

  const typedContext = Object.fromEntries(
    Object.entries(request.context).filter(([key]) => key !== "contract_schema"),
  );
  return [
    `User request:\n${primaryInput}`,
    `Validated typed operation context:\n${JSON.stringify(typedContext)}`,
  ].join("\n\n");
}

async function projectOutputDelta(
  request: AgentRunRequest,
  agentEvent: AgentEvent,
  emit: EventSink,
): Promise<void> {
  if (
    agentEvent.type === "message_update" &&
    agentEvent.assistantMessageEvent.type === "text_delta" &&
    agentEvent.assistantMessageEvent.delta
  ) {
    const runtimeEvent: AgentRuntimeEvent = event(request, 0, "output_delta", {
      text: agentEvent.assistantMessageEvent.delta,
    });
    await emit(runtimeEvent);
  }
}
