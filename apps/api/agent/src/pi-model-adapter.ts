import { Agent, type AgentEvent, type AgentTool } from "@earendil-works/pi-agent-core";
import { Type, type Model } from "@earendil-works/pi-ai";
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
import {
  structuredRepairPrompt,
  structuredSubmissionPrompt,
} from "./prompts/agents.js";
import {
  getPromptDescriptor,
  isPlanningOperation,
} from "./prompts/registry.js";
import {
  getAgentDefinition,
  getOperationDescriptor,
  toolsForOperation,
  type AgentToolName,
} from "./registry.js";
import { loadRequiredSkills, type LoadedSkill } from "./skills.js";

const structuredValueSchema = Type.Record(Type.String(), Type.Unknown());

export class PiModelAdapter implements AgentModelAdapter {
  constructor(private readonly python: PythonInternalClient) {}

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
    const promptDescriptor = isPlanningOperation(request.operation)
      ? getPromptDescriptor(
          request.agent_name,
          request.operation,
          request.contract_name ?? "",
        )
      : undefined;
    const credential = await this.python.credential(
      request.credential_ref ?? "llm-default",
      request.agent_name,
      request.operation,
      request.model_policy_id,
    );
    const operationDescriptor = getOperationDescriptor(
      request.agent_name,
      request.operation,
    );
    const skills = await loadRequiredSkills(operationDescriptor);
    const skillContext = skills
      .map(
        (skill) =>
          `Skill: ${skill.skill_id}\nDigest: ${skill.sha256}\n\n${skill.content}`,
      )
      .join("\n\n---\n\n");
    const model: Model<"openai-completions"> = {
      id: credential.model_id,
      name: credential.model_id,
      api: "openai-completions",
      provider: credential.provider,
      baseUrl: credential.base_url,
      reasoning: true,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 128_000,
      maxTokens: 8_192,
      compat: {
        supportsDeveloperRole: false,
        supportsReasoningEffort: false,
        supportsUsageInStreaming: true,
        supportsStrictMode: true,
        maxTokensField: "max_tokens",
        thinkingFormat: "zai",
      },
    };
    let acceptedResult: Record<string, unknown> | undefined;
    let attempts = 0;
    const structuredTool: AgentTool<typeof structuredValueSchema> = {
      name: "submit_structured_result",
      label: "Submit structured result",
      description: "Submit the final validated result for this operation.",
      parameters: structuredToolParameters(request),
      execute: async (toolCallId, params) => {
        budget?.consumeToolCall();
        attempts += 1;
        if (attempts > 2) throw new Error("agent_structured_output_invalid");
        const result = await this.python.executeTool({
          protocol_version: "1",
          run_id: request.run_id,
          tool_call_id: toolCallId,
          idempotency_key: `${request.run_id}:structured:${attempts}`,
          tool_name: "submit_structured_result",
          arguments: {
            protocol_version: "1",
            run_id: request.run_id,
            submission_id: `${request.run_id}:submission:${attempts}`,
            contract_name: request.contract_name ?? "SpecialistDraft",
            value: params,
            attempt: attempts,
          },
        });
        await emit(
          event(request, 0, "tool_result", {
            tool_call_id: toolCallId,
            status: result.status,
            error_code: result.error_code,
          }),
        );
        if (result.status === "completed") {
          acceptedResult = acceptedStructuredValue(result.result);
        } else if (
          attempts >= 2 &&
          result.error_code === "agent_structured_output_invalid"
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
    const agent = new Agent({
      initialState: {
        systemPrompt: [
          promptDescriptor?.system_prompt ?? definition.system_prompt,
          skillContext ? `Trusted skill context:\n\n${skillContext}` : "",
          structuredSubmissionPrompt,
          structuredRepairPrompt,
          `Required contract: ${request.contract_name ?? "SpecialistDraft"}.`,
          `JSON Schema: ${JSON.stringify(contractSchema(request))}`,
        ]
          .filter(Boolean)
          .join("\n\n"),
        model,
        tools,
        thinkingLevel: "off",
      },
      streamFn: (selectedModel, context, options) => {
        const streamOptions = {
          ...options,
          apiKey: credential.api_key,
          ...(toolChoice ? { toolChoice } : {}),
        };
        return streamSimple(
          selectedModel as Model<"openai-completions">,
          context,
          streamOptions,
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
        await agent.prompt(promptInput(request));
      } catch (error) {
        promptError = error;
      }
      await eventProjection.settle();
      if (promptError) throw promptError;
    } finally {
      signal.removeEventListener("abort", abort);
      unsubscribe();
    }
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

export function toolsForRequest(
  request: AgentRunRequest,
): ReadonlyArray<AgentToolName> {
  if (request.audit_metadata?.tool_mode === "structured_only") {
    return ["submit_structured_result"];
  }
  return toolsForOperation(request.agent_name, request.operation);
}

export function toolChoiceForRequest(
  request: AgentRunRequest,
):
  | {
      readonly type: "function";
      readonly function: { readonly name: "submit_structured_result" };
    }
  | undefined {
  return request.audit_metadata?.tool_mode === "structured_only"
    ? {
        type: "function",
        function: { name: "submit_structured_result" },
      }
    : undefined;
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
  if (!isPlanningOperation(request.operation)) return {};
  const descriptor = getPromptDescriptor(
    request.agent_name,
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

function promptInput(request: AgentRunRequest): string {
  if ("user_input" in request.context) return request.context.user_input;
  if ("user_instruction" in request.context) {
    return request.context.user_instruction;
  }
  throw new Error("agent_context_input_missing");
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
