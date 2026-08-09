import OpenAI from "openai";

import type {
  AgentRunRequest,
  AgentTransportAttemptMetadataV1,
} from "./generated/agent-runtime.js";
import { AgentOperationFailure } from "./operation-recovery.js";
import type { AgentCredentialSnapshot } from "./python-internal-client.js";

export interface StructuredCompletionRequest {
  readonly model: string;
  readonly messages: ReadonlyArray<Readonly<Record<string, unknown>>>;
  readonly stream: false;
  readonly max_tokens: number;
  readonly tools?: ReadonlyArray<{
    readonly type: "function";
    readonly function: {
      readonly name: "submit_structured_result";
      readonly description: string;
      readonly parameters: Readonly<Record<string, unknown>>;
    };
  }>;
  readonly tool_choice?: {
    readonly type: "function";
    readonly function: { readonly name: "submit_structured_result" };
  };
  readonly response_format?: { readonly type: "json_object" };
}

export interface StructuredCompletionResponse {
  readonly id?: string | null;
  readonly choices?: ReadonlyArray<{
    readonly finish_reason?: string | null;
    readonly message?: {
      readonly content?: string | null;
      readonly tool_calls?: ReadonlyArray<{
        readonly id?: string;
        readonly type?: string;
        readonly function?: { readonly name?: string; readonly arguments?: string };
      }>;
    };
  }>;
  readonly usage?: {
    readonly prompt_tokens?: number;
    readonly completion_tokens?: number;
    readonly total_tokens?: number;
    readonly completion_tokens_details?: { readonly reasoning_tokens?: number };
  } | null;
}

export type StructuredCompletionExecutor = (
  request: StructuredCompletionRequest,
  options: {
    readonly apiKey: string;
    readonly baseUrl: string;
    readonly signal: AbortSignal;
    readonly timeoutMs: number;
  },
) => Promise<StructuredCompletionResponse>;

interface StructuredValidationResult {
  readonly status: string;
  readonly error_code?: string | null;
  readonly result?: Readonly<Record<string, unknown>>;
}

interface StructuredTransportRunInput {
  readonly credential: AgentCredentialSnapshot;
  readonly request: AgentRunRequest;
  readonly systemPrompt: string;
  readonly userPrompt: string;
  readonly schema: Readonly<Record<string, unknown>>;
  readonly signal: AbortSignal;
  readonly submit: (
    value: Readonly<Record<string, unknown>>,
    attempt: number,
    toolCallId: string,
  ) => Promise<StructuredValidationResult>;
}

export interface StructuredTransportResult {
  readonly value: Record<string, unknown>;
  readonly audit: AgentTransportAttemptMetadataV1;
}

interface RouterOptions {
  readonly execute?: StructuredCompletionExecutor;
  readonly now?: () => Date;
  readonly sleep?: (milliseconds: number) => Promise<void>;
}

export class PiStructuredTransportRouter {
  readonly #execute: StructuredCompletionExecutor;
  readonly #now: () => Date;
  readonly #sleep: (milliseconds: number) => Promise<void>;

  constructor(options: RouterOptions = {}) {
    this.#execute = options.execute ?? executeOpenAICompletion;
    this.#now = options.now ?? (() => new Date());
    this.#sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => {
      setTimeout(resolve, milliseconds);
    }));
  }

  async run(input: StructuredTransportRunInput): Promise<StructuredTransportResult> {
    const policy = input.credential.execution_policy;
    if (policy.structured_transport !== "non_streaming_tool_call") {
      throw new AgentOperationFailure(
        "agent_model_capability_mismatch",
        "agent_model_capability_mismatch",
        false,
      );
    }
    const startedAt = this.#now().toISOString();
    const primaryRequest = primaryPayload(input);
    const primary = await this.#executeWithRetry(primaryRequest, input);
    let structuredAttempts = 1;
    let value = primaryToolArguments(primary.response);
    let validation: StructuredValidationResult | undefined;
    if (value !== undefined) {
      validation = await input.submit(value, 1, primary.toolCallId ?? "call_primary");
      const accepted = acceptedValue(validation);
      if (accepted !== undefined) {
        return resultFor(accepted, input, primary, {
          startedAt,
          structuredAttempts,
        });
      }
      if (validation.error_code === "agent_contract_validation_failed") {
        throw terminalValidationFailure(validation.error_code);
      }
    }
    if (policy.structured_repair_limit < 1 || input.signal.aborted) {
      throw structuredFailure();
    }
    structuredAttempts = 2;
    const repair = await this.#executeOnce(repairPayload(input, validation), input);
    value = repairContent(repair.response);
    if (value === undefined) throw structuredFailure();
    const repaired = await input.submit(value, 2, "call_structured_repair");
    const accepted = acceptedValue(repaired);
    if (accepted === undefined) {
      if (repaired.error_code === "agent_contract_validation_failed") {
        throw terminalValidationFailure(repaired.error_code);
      }
      throw structuredFailure();
    }
    return resultFor(accepted, input, repair, { startedAt, structuredAttempts });
  }

  async #executeWithRetry(
    request: StructuredCompletionRequest,
    input: StructuredTransportRunInput,
  ): Promise<CompletionAttempt> {
    try {
      return await this.#executeOnce(request, input);
    } catch (error) {
      if (
        input.credential.execution_policy.transport_retry_limit < 1 ||
        !isRetryablePreActivityFailure(error)
      ) {
        throw normalizeTransportFailure(error, input.signal);
      }
      await this.#sleep(250);
      const retry = await this.#executeOnce(request, input).catch((candidate) => {
        throw normalizeTransportFailure(candidate, input.signal, "transport_retry");
      });
      return { ...retry, retryCount: 1 };
    }
  }

  async #executeOnce(
    request: StructuredCompletionRequest,
    input: StructuredTransportRunInput,
  ): Promise<CompletionAttempt> {
    if (input.signal.aborted) throw providerTimeout();
    const firstResponseAt = this.#now().toISOString();
    try {
      const response = await this.#execute(request, {
        apiKey: input.credential.api_key,
        baseUrl: input.credential.base_url,
        signal: input.signal,
        timeoutMs: input.credential.execution_policy.deadline_seconds * 1_000,
      });
      const finishedAt = this.#now().toISOString();
      const toolCallId = matchingToolCall(response)?.id;
      return {
        response,
        firstResponseAt,
        finishedAt,
        ...(toolCallId ? { toolCallId } : {}),
        retryCount: 0,
      };
    } catch (error) {
      throw normalizeTransportFailure(error, input.signal);
    }
  }
}

interface CompletionAttempt {
  readonly response: StructuredCompletionResponse;
  readonly firstResponseAt: string;
  readonly finishedAt: string;
  readonly toolCallId?: string;
  readonly retryCount: number;
}

async function executeOpenAICompletion(
  request: StructuredCompletionRequest,
  options: {
    readonly apiKey: string;
    readonly baseUrl: string;
    readonly signal: AbortSignal;
    readonly timeoutMs: number;
  },
): Promise<StructuredCompletionResponse> {
  const client = new OpenAI({
    apiKey: options.apiKey,
    baseURL: options.baseUrl,
    maxRetries: 0,
    timeout: options.timeoutMs,
  });
  return await client.chat.completions.create(
    request as unknown as OpenAI.Chat.Completions.ChatCompletionCreateParamsNonStreaming,
    { signal: options.signal },
  );
}

function primaryPayload(input: StructuredTransportRunInput): StructuredCompletionRequest {
  return {
    model: input.credential.model_id,
    messages: [
      { role: "system", content: input.systemPrompt },
      { role: "user", content: input.userPrompt },
    ],
    stream: false,
    max_tokens: input.credential.execution_policy.max_output_tokens,
    tools: [
      {
        type: "function",
        function: {
          name: "submit_structured_result",
          description: "Submit the final validated result for this operation.",
          parameters: input.schema,
        },
      },
    ],
    tool_choice: {
      type: "function",
      function: { name: "submit_structured_result" },
    },
  };
}

function repairPayload(
  input: StructuredTransportRunInput,
  validation: StructuredValidationResult | undefined,
): StructuredCompletionRequest {
  const violations = boundedViolations(validation?.result);
  return {
    model: input.credential.model_id,
    messages: [
      {
        role: "system",
        content: "Return exactly one JSON object matching the supplied schema.",
      },
      {
        role: "user",
        content: [
          `Validation violations: ${JSON.stringify(violations)}`,
          `JSON Schema: ${JSON.stringify(input.schema)}`,
          `Original request: ${input.userPrompt}`,
        ].join("\n\n"),
      },
    ],
    stream: false,
    max_tokens: input.credential.execution_policy.max_output_tokens,
    response_format: { type: "json_object" },
  };
}

function matchingToolCall(response: StructuredCompletionResponse) {
  const calls = response.choices?.[0]?.message?.tool_calls?.filter(
    (candidate) =>
      candidate.type === "function" &&
      candidate.function?.name === "submit_structured_result",
  ) ?? [];
  return calls.length === 1 ? calls[0] : undefined;
}

function primaryToolArguments(
  response: StructuredCompletionResponse,
): Readonly<Record<string, unknown>> | undefined {
  const value = matchingToolCall(response)?.function?.arguments;
  return parseObject(value);
}

function repairContent(
  response: StructuredCompletionResponse,
): Readonly<Record<string, unknown>> | undefined {
  return parseObject(response.choices?.[0]?.message?.content ?? undefined);
}

function parseObject(value: string | undefined | null) {
  if (!value) return undefined;
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Readonly<Record<string, unknown>>)
      : undefined;
  } catch {
    return undefined;
  }
}

function acceptedValue(
  validation: StructuredValidationResult,
): Record<string, unknown> | undefined {
  if (validation.status !== "completed" || validation.result?.accepted !== true) {
    return undefined;
  }
  const value = validation.result.value ?? validation.result.normalized_value;
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Readonly<Record<string, unknown>>) }
    : undefined;
}

function resultFor(
  value: Record<string, unknown>,
  input: StructuredTransportRunInput,
  attempt: CompletionAttempt,
  details: { readonly startedAt: string; readonly structuredAttempts: number },
): StructuredTransportResult {
  const choice = attempt.response.choices?.[0];
  const usage = attempt.response.usage;
  return {
    value,
    audit: {
      provider: input.credential.provider,
      model_ref: input.credential.model_ref,
      structured_transport: input.credential.execution_policy.structured_transport,
      thinking_format: input.credential.execution_policy.thinking_format,
      reasoning_control: input.credential.execution_policy.reasoning_control,
      deadline_seconds: input.credential.execution_policy.deadline_seconds,
      max_output_tokens: input.credential.execution_policy.max_output_tokens,
      started_at: details.startedAt,
      first_response_at: attempt.firstResponseAt,
      last_activity_at: attempt.finishedAt,
      finished_at: attempt.finishedAt,
      finish_reason: choice?.finish_reason ?? null,
      provider_trace_id: attempt.response.id ?? null,
      input_tokens: usage?.prompt_tokens ?? null,
      output_tokens: usage?.completion_tokens ?? null,
      reasoning_tokens: usage?.completion_tokens_details?.reasoning_tokens ?? null,
      transport_retry_count: attempt.retryCount,
      structured_attempt_count: details.structuredAttempts,
    },
  };
}

function boundedViolations(result: Readonly<Record<string, unknown>> | undefined) {
  const candidate = result?.violations;
  if (!Array.isArray(candidate)) return [];
  return candidate.slice(0, 8).map((item) => String(item).slice(0, 240));
}

function isPreActivityConnectionFailure(error: unknown): boolean {
  const candidate = error as {
    readonly code?: unknown;
    readonly message?: unknown;
    readonly response_started?: unknown;
  };
  if (candidate?.response_started === true) return false;
  const code = String(candidate?.code ?? "").toUpperCase();
  const message = String(candidate?.message ?? error ?? "").toLowerCase();
  return new Set(["ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "ENOTFOUND"]).has(code) ||
    message.includes("connection reset") ||
    message.includes("connect failed");
}

function isRetryablePreActivityFailure(error: unknown): boolean {
  return (
    isPreActivityConnectionFailure(error) ||
    (error instanceof AgentOperationFailure &&
      error.code === "agent_provider_transport_failed" &&
      error.retryable)
  );
}

function normalizeTransportFailure(
  error: unknown,
  signal: AbortSignal,
  stage: "initial" | "transport_retry" = "initial",
): AgentOperationFailure {
  if (
    signal.aborted ||
    (error instanceof DOMException &&
      (error.name === "AbortError" || error.name === "TimeoutError")) ||
    (error instanceof Error && error.name === "APIConnectionTimeoutError")
  ) {
    return providerTimeout(stage);
  }
  if (error instanceof AgentOperationFailure) return error;
  return new AgentOperationFailure(
    "agent_provider_transport_failed",
    "agent_provider_transport_failed",
    isPreActivityConnectionFailure(error),
    stage,
  );
}

function providerTimeout(
  stage: "initial" | "transport_retry" = "initial",
): AgentOperationFailure {
  return new AgentOperationFailure(
    "agent_provider_timeout",
    "agent_provider_timeout",
    false,
    stage,
  );
}

function structuredFailure() {
  return new AgentOperationFailure(
    "agent_structured_output_invalid",
    "agent_structured_output_invalid",
    false,
    "structured_repair",
  );
}

function terminalValidationFailure(code: string) {
  return new AgentOperationFailure(code, code, false, "initial");
}
