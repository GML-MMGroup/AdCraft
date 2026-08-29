import { createHash } from "node:crypto";

import OpenAI from "openai";

import {
  chatCompletionChunkFailure,
  normalizeChatCompletionChunk,
} from "./chat-completion-chunk-normalizer.js";
import type {
  AgentRunRequest,
  AgentStructuredFallbackAuditV1,
  AgentStructuredValidationAttemptAuditV1,
  AgentTransportAttemptMetadataV1,
} from "./generated/agent-runtime.js";
import {
  AgentOperationFailure,
  isProviderTimeoutFailure,
} from "./operation-recovery.js";
import type { AgentCredentialSnapshot } from "./python-internal-client.js";
import { modelAttemptTimeoutMs, type ModelAttemptStage } from "./run-budget.js";
import type { PreparedStructuredModelInput } from "./structured-model-input.js";


interface StructuredCompletionRequestBase {
  readonly model: string;
  readonly messages: ReadonlyArray<Readonly<Record<string, unknown>>>;
  readonly max_tokens: number;
  readonly enable_thinking: boolean;
  readonly thinking_budget?: number;
}

export interface NonStreamingStructuredCompletionRequest
  extends StructuredCompletionRequestBase {
  readonly stream: false;
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

export interface StreamingJsonCompletionRequest
  extends StructuredCompletionRequestBase {
  readonly stream: true;
  readonly response_format: { readonly type: "json_object" };
  readonly tools?: never;
  readonly tool_choice?: never;
}

export type StructuredCompletionRequest =
  | NonStreamingStructuredCompletionRequest
  | StreamingJsonCompletionRequest;

export interface StreamingJsonTransportMetadata {
  readonly response_activity_observed: boolean;
  readonly first_content_at: string | null;
  readonly last_activity_at: string | null;
  readonly completed_at: string;
  readonly response_bytes: number;
  readonly finish_reason: string | null;
  readonly provider_trace_id: string | null;
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
  readonly transport_metadata?: StreamingJsonTransportMetadata;
}

export type StructuredCompletionExecutor = (
  request: StructuredCompletionRequest,
  options: {
    readonly apiKey: string;
    readonly baseUrl: string;
    readonly signal: AbortSignal;
    readonly timeoutMs: number;
    readonly maxOutputBytes?: number;
  },
) => Promise<StructuredCompletionResponse>;

interface StructuredValidationResult {
  readonly status: string;
  readonly error_code?: string | null;
  readonly result?: Readonly<Record<string, unknown>>;
}

export const SAFE_CONVERSATION_FALLBACK_MESSAGE =
  "已收到你的请求，但本轮结构化解析未能安全完成。你的项目没有被修改，请重试或换一种表达。";

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
    if (
      policy.structured_transport !== "non_streaming_tool_call" &&
      policy.structured_transport !== "non_streaming_json_object" &&
      policy.structured_transport !== "streaming_json_object"
    ) {
      throw new AgentOperationFailure(
        "agent_model_capability_mismatch",
        "agent_model_capability_mismatch",
        false,
      );
    }
    const startedAt = this.#now().toISOString();
    const primaryRequest = buildPrimaryStructuredCompletionRequest(input);
    const primary = await this.#executeWithRetry(primaryRequest, input);
    let structuredAttempts = 1;
    const validationAttempts: AgentStructuredValidationAttemptAuditV1[] = [];
    const primaryCandidate = primaryValue(input, primary.response);
    let value = primaryCandidate;
    let validation: StructuredValidationResult | undefined;
    if (value !== undefined) {
      validation = await input.submit(value, 1, primary.toolCallId ?? "call_primary");
      const accepted = acceptedValue(validation);
      if (accepted !== undefined) {
        return resultFor(accepted, input, primary, {
          startedAt,
          structuredAttempts,
          validationAttempts,
        });
      }
    } else if (isJsonObjectTransport(policy.structured_transport)) {
      validation = malformedJsonValidation();
    } else {
      validation = missingStructuredResultValidation();
    }
    validationAttempts.push(validationAttemptAudit(validation, 1, "initial"));
    if (validation.result?.repair_allowed === false) {
      throw terminalValidationFailure(
        validation.error_code ?? "agent_structured_output_invalid",
        auditForAttempt(
          input,
          primary,
          startedAt,
          structuredAttempts,
          validationAttempts,
        ),
        isManualRetryableIntake(input),
      );
    }
    if (policy.structured_repair_limit < 1 || input.signal.aborted) {
      throw structuredFailure(
        primary.attemptStage ?? "initial",
        auditForAttempt(
          input,
          primary,
          startedAt,
          structuredAttempts,
          validationAttempts,
        ),
        isManualRetryableIntake(input),
      );
    }
    if (primary.retryCount > 0) {
      throw structuredFailure(
        "transport_retry",
        auditForAttempt(
          input,
          primary,
          startedAt,
          structuredAttempts,
          validationAttempts,
        ),
      );
    }
    structuredAttempts = 2;
    const repair = await this.#executeOnce(
      repairPayload(input, validation, value),
      input,
      "structured_repair",
    );
    value = repairContent(repair.response);
    if (value === undefined) {
      const malformedRepair = malformedJsonValidation(false);
      validationAttempts.push(
        validationAttemptAudit(malformedRepair, 2, "structured_repair"),
      );
      if (supportsSafeConversationFallback(input)) {
        const fallbackMessage = safeConversationFallbackMessage(primaryCandidate);
        const fallbackValue = {
          mode: "ordinary_conversation" as const,
          objective:
            "Preserve a safe conversational response after structured validation failed.",
          assistant_message: fallbackMessage.message,
        };
        const fallbackValidation = await input.submit(
          fallbackValue,
          2,
          "call_structured_fallback",
        );
        const acceptedFallback = acceptedValue(fallbackValidation);
        if (acceptedFallback !== undefined) {
          return resultFor(acceptedFallback, input, repair, {
            startedAt,
            structuredAttempts,
            validationAttempts,
            structuredFallback: {
              contract_name: "CompactTurnIntentDecisionV3",
              error_code: "agent_structured_fallback_applied",
              failure_codes: [],
              validation_paths: [],
              submission_attempt: 2,
              used_model_message: fallbackMessage.usedModelMessage,
              reason: "repair_json_invalid",
            },
          });
        }
        validationAttempts.push(
          validationAttemptAudit(fallbackValidation, 2, "structured_repair"),
        );
        if (fallbackValidation.error_code === "agent_contract_validation_failed") {
          throw terminalValidationFailure(
            fallbackValidation.error_code,
            auditForAttempt(
              input,
              repair,
              startedAt,
              structuredAttempts,
              validationAttempts,
            ),
            isManualRetryableIntake(input),
          );
        }
      }
      throw structuredFailure(
        "structured_repair",
        auditForAttempt(
          input,
          repair,
          startedAt,
          structuredAttempts,
          validationAttempts,
        ),
        isManualRetryableIntake(input),
      );
    }
    const repaired = await input.submit(value, 2, "call_structured_repair");
    const accepted = acceptedValue(repaired);
    if (accepted === undefined) {
      validationAttempts.push(
        validationAttemptAudit(repaired, 2, "structured_repair"),
      );
      if (repaired.error_code === "agent_contract_validation_failed") {
        throw terminalValidationFailure(
          repaired.error_code,
          auditForAttempt(
            input,
            repair,
            startedAt,
            structuredAttempts,
            validationAttempts,
          ),
          isManualRetryableIntake(input),
        );
      }
      throw structuredFailure(
        "structured_repair",
        auditForAttempt(
          input,
          repair,
          startedAt,
          structuredAttempts,
          validationAttempts,
        ),
        isManualRetryableIntake(input),
      );
    }
    const repairedFallbackAudit = boundedStructuredFallbackAudit(
      repaired.result?.fallback_audit,
    );
    return resultFor(accepted, input, repair, {
      startedAt,
      structuredAttempts,
      validationAttempts,
      ...(repairedFallbackAudit
        ? { structuredFallback: repairedFallbackAudit }
        : {}),
    });
  }

  async #executeWithRetry(
    request: StructuredCompletionRequest,
    input: StructuredTransportRunInput,
  ): Promise<CompletionAttempt> {
    try {
      return await this.#executeOnce(request, input, "initial");
    } catch (error) {
      if (
        input.credential.execution_policy.transport_retry_limit < 1 ||
        !isRetryablePreActivityFailure(error)
      ) {
        throw normalizeTransportFailure(error, input.signal);
      }
      await this.#sleep(250);
      const retry = await this.#executeOnce(request, input, "transport_retry");
      return { ...retry, retryCount: 1 };
    }
  }

  async #executeOnce(
    request: StructuredCompletionRequest,
    input: StructuredTransportRunInput,
    stage: ModelAttemptStage,
  ): Promise<CompletionAttempt> {
    const startedAt = this.#now().toISOString();
    const timeoutMs = modelAttemptTimeoutMs(
      input.credential.execution_policy,
      Date.parse(input.request.deadline_at),
      stage,
      this.#now().getTime(),
    );
    if (input.signal.aborted) {
      throw providerTimeout(
        stage,
        failureMetadata(input, startedAt, this.#now().toISOString(), 0, stage, {
          name: "AbortError",
          code: "ABORT_ERR",
        }),
        false,
        isManualRetryableIntake(input),
      );
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
      throw providerTimeout(
        stage,
        failureMetadata(input, startedAt, this.#now().toISOString(), 0, stage),
        false,
        isManualRetryableIntake(input),
      );
    }
    try {
      const response = await this.#execute(request, {
        apiKey: input.credential.api_key,
        baseUrl: input.credential.base_url,
        signal: input.signal,
        timeoutMs,
        maxOutputBytes: input.request.policy?.max_output_bytes ?? 262_144,
      });
      const firstResponseAt =
        response.transport_metadata?.first_content_at ?? this.#now().toISOString();
      const finishedAt =
        response.transport_metadata?.completed_at ?? this.#now().toISOString();
      const toolCallId = matchingToolCall(response)?.id;
      return {
        response,
        firstResponseAt,
        finishedAt,
        ...(toolCallId ? { toolCallId } : {}),
        retryCount: 0,
        effectiveTimeoutMs: timeoutMs,
        attemptStage: stage,
      };
    } catch (error) {
      throw normalizeTransportFailure(
        error,
        input.signal,
        stage,
        failureMetadata(
          input,
          startedAt,
          this.#now().toISOString(),
          timeoutMs,
          stage,
          error,
        ),
        isManualRetryableIntake(input),
      );
    }
  }
}

interface CompletionAttempt {
  readonly response: StructuredCompletionResponse;
  readonly firstResponseAt: string;
  readonly finishedAt: string;
  readonly toolCallId?: string;
  readonly retryCount: number;
  readonly effectiveTimeoutMs?: number;
  readonly attemptStage?: ModelAttemptStage;
}

export async function executeOpenAICompletion(
  request: StructuredCompletionRequest,
  options: {
    readonly apiKey: string;
    readonly baseUrl: string;
    readonly signal: AbortSignal;
    readonly timeoutMs: number;
    readonly maxOutputBytes?: number;
  },
): Promise<StructuredCompletionResponse> {
  const client = new OpenAI({
    apiKey: options.apiKey,
    baseURL: options.baseUrl,
    maxRetries: 0,
    timeout: options.timeoutMs,
  });
  if (!request.stream) {
    return await client.chat.completions.create(
      request as unknown as OpenAI.Chat.Completions.ChatCompletionCreateParamsNonStreaming,
      { signal: options.signal },
    );
  }
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(options.signal.reason);
  options.signal.addEventListener("abort", abortFromCaller, { once: true });
  const timer = setTimeout(
    () => controller.abort(new DOMException("Agent provider request timed out.", "TimeoutError")),
    options.timeoutMs,
  );
  try {
    const stream = await client.chat.completions.create(
      request as unknown as OpenAI.Chat.Completions.ChatCompletionCreateParamsStreaming,
      { signal: controller.signal },
    );
    return await aggregateStreamingJsonCompletion(stream as AsyncIterable<unknown>, {
      signal: controller.signal,
      maxOutputBytes: options.maxOutputBytes ?? 262_144,
    });
  } finally {
    clearTimeout(timer);
    options.signal.removeEventListener("abort", abortFromCaller);
  }
}

export async function aggregateStreamingJsonCompletion(
  stream: AsyncIterable<unknown>,
  options: {
    readonly signal: AbortSignal;
    readonly maxOutputBytes: number;
    readonly now?: () => Date;
  },
): Promise<StructuredCompletionResponse> {
  const now = options.now ?? (() => new Date());
  const iterator = stream[Symbol.asyncIterator]();
  let content = "";
  let responseBytes = 0;
  let responseActivityObserved = false;
  let firstContentAt: string | null = null;
  let lastActivityAt: string | null = null;
  let finishReason: string | null = null;
  let providerTraceId: string | null = null;
  let terminal = false;
  try {
    while (true) {
      const item = await abortableNext(iterator, options.signal);
      if (item.done) break;
      responseActivityObserved = true;
      const observedAt = now().toISOString();
      lastActivityAt = observedAt;
      if (terminal) {
        throw chatCompletionChunkFailure(
          "agent_provider_transport_failed",
          "stream_chunk_after_terminal",
        );
      }
      const parsed = normalizeChatCompletionChunk(item.value);
      providerTraceId =
        boundedProviderTrace(parsed.providerTraceId) ?? providerTraceId;
      if (responseBytes + parsed.responseBytes > options.maxOutputBytes) {
        throw chatCompletionChunkFailure(
          "agent_provider_transport_failed",
          "stream_response_bytes_exceeded",
        );
      }
      responseBytes += parsed.responseBytes;
      if (parsed.content !== null) {
        if (firstContentAt === null && parsed.content.length > 0) {
          firstContentAt = observedAt;
        }
        content += parsed.content;
      }
      if (parsed.finishReason !== null) {
        finishReason = parsed.finishReason;
        terminal = true;
      }
    }
    if (!terminal) {
      throw chatCompletionChunkFailure(
        "agent_provider_transport_failed",
        "stream_terminal_missing",
      );
    }
    if (content.length === 0) {
      throw chatCompletionChunkFailure(
        "agent_structured_output_invalid",
        "stream_content_missing",
      );
    }
    const completedAt = now().toISOString();
    return {
      id: providerTraceId,
      choices: [{ finish_reason: finishReason, message: { content } }],
      transport_metadata: {
        response_activity_observed: responseActivityObserved,
        first_content_at: firstContentAt,
        last_activity_at: lastActivityAt,
        completed_at: completedAt,
        response_bytes: responseBytes,
        finish_reason: finishReason,
        provider_trace_id: providerTraceId,
      },
    };
  } catch (error) {
    if (error && typeof error === "object") {
      Object.assign(error, {
        response_started: responseActivityObserved,
        first_response_at: firstContentAt,
        last_activity_at: lastActivityAt,
        response_bytes: responseBytes,
        provider_trace_id: providerTraceId,
      });
    }
    throw error;
  } finally {
    try {
      await iterator.return?.();
    } catch {
      // Stream cleanup cannot replace the authoritative transport outcome.
    }
  }
}

async function abortableNext(
  iterator: AsyncIterator<unknown>,
  signal: AbortSignal,
): Promise<IteratorResult<unknown>> {
  if (signal.aborted) throw signal.reason ?? new DOMException("Aborted", "AbortError");
  return await new Promise<IteratorResult<unknown>>((resolve, reject) => {
    const onAbort = () => reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", onAbort, { once: true });
    void iterator.next().then(resolve, reject).finally(() => {
      signal.removeEventListener("abort", onAbort);
    });
  });
}

function boundedProviderTrace(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value.slice(0, 160) : null;
}

export function buildPrimaryStructuredCompletionRequest(
  input: Pick<
    PreparedStructuredModelInput,
    "credential" | "systemPrompt" | "userPrompt" | "schema"
  >,
): StructuredCompletionRequest {
  if (
    isJsonObjectTransport(input.credential.execution_policy.structured_transport)
  ) {
    return {
      model: input.credential.model_id,
      messages: [
        {
          role: "system",
          content: [
            input.systemPrompt,
            "Return exactly one JSON object matching the supplied schema.",
            `JSON Schema: ${JSON.stringify(input.schema)}`,
          ].join("\n\n"),
        },
        { role: "user", content: input.userPrompt },
      ],
      stream:
        input.credential.execution_policy.structured_transport ===
        "streaming_json_object",
      max_tokens: input.credential.execution_policy.max_output_tokens,
      ...reasoningPayload(input.credential.execution_policy),
      response_format: { type: "json_object" },
    };
  }
  return {
    model: input.credential.model_id,
    messages: [
      { role: "system", content: input.systemPrompt },
      { role: "user", content: input.userPrompt },
    ],
    stream: false,
    max_tokens: input.credential.execution_policy.max_output_tokens,
    ...reasoningPayload(input.credential.execution_policy),
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

export function canonicalRequestSha256(
  request: StructuredCompletionRequest,
): string {
  return createHash("sha256")
    .update(JSON.stringify(canonicalJsonValue(request)), "utf8")
    .digest("hex");
}

function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Readonly<Record<string, unknown>>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalJsonValue(item)]),
  );
}

function primaryValue(
  input: StructuredTransportRunInput,
  response: StructuredCompletionResponse,
): Readonly<Record<string, unknown>> | undefined {
  return isJsonObjectTransport(
    input.credential.execution_policy.structured_transport,
  )
    ? repairContent(response)
    : primaryToolArguments(response);
}

function malformedJsonValidation(repairAllowed = true): StructuredValidationResult {
  return {
    status: "failed",
    error_code: "agent_structured_output_invalid",
    result: {
      accepted: false,
      repair_allowed: repairAllowed,
      violations: [
        {
          path: "$",
          code: "json_parse_failed",
          message: "Return exactly one valid JSON object.",
        },
      ],
    },
  };
}

function missingStructuredResultValidation(): StructuredValidationResult {
  return {
    status: "failed",
    error_code: "agent_structured_output_invalid",
    result: {
      accepted: false,
      repair_allowed: true,
      violations: [
        {
          path: "$",
          code: "structured_result_missing",
          message: "Return exactly one structured result.",
        },
      ],
    },
  };
}

function repairPayload(
  input: StructuredTransportRunInput,
  validation: StructuredValidationResult | undefined,
  invalidValue: Readonly<Record<string, unknown>> | undefined,
): StructuredCompletionRequest {
  const violations = boundedViolations(validation?.result);
  const boundedInvalidValue = boundedInvalidResult(invalidValue);
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
          ...(boundedInvalidValue ? [`Invalid result: ${boundedInvalidValue}`] : []),
          `JSON Schema: ${JSON.stringify(input.schema)}`,
          `Original request: ${input.userPrompt}`,
        ].join("\n\n"),
      },
    ],
    stream:
      input.credential.execution_policy.structured_transport ===
      "streaming_json_object",
    max_tokens: input.credential.execution_policy.max_output_tokens,
    enable_thinking: false,
    response_format: { type: "json_object" },
  };
}

function reasoningPayload(policy: AgentCredentialSnapshot["execution_policy"]): {
  readonly enable_thinking: boolean;
  readonly thinking_budget?: number;
} {
  return {
    enable_thinking: policy.enable_thinking,
    ...(typeof policy.thinking_budget_tokens === "number"
      ? { thinking_budget: policy.thinking_budget_tokens }
      : {}),
  };
}

function isJsonObjectTransport(transport: string): boolean {
  return transport === "non_streaming_json_object" ||
    transport === "streaming_json_object";
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

export function supportsSafeConversationFallback(
  input: Pick<StructuredTransportRunInput, "request">,
): boolean {
  return input.request.operation === "decide_turn_intent" &&
    input.request.contract_name === "CompactTurnIntentDecisionV3";
}

function safeConversationFallbackMessage(
  candidate: Readonly<Record<string, unknown>> | undefined,
): { readonly message: string; readonly usedModelMessage: boolean } {
  const rawMessage = candidate?.assistant_message;
  if (typeof rawMessage === "string" && Array.from(rawMessage).length <= 2_000) {
    const cleanedMessage = Array.from(rawMessage)
      .filter(
        (character) =>
          character === "\n" ||
          character === "\t" ||
          !/[\p{Cc}\p{Cf}]/u.test(character),
      )
      .join("")
      .trim();
    if (cleanedMessage && Array.from(cleanedMessage).length <= 2_000) {
      return { message: cleanedMessage, usedModelMessage: true };
    }
  }
  return {
    message: SAFE_CONVERSATION_FALLBACK_MESSAGE,
    usedModelMessage: false,
  };
}

function boundedStructuredFallbackAudit(
  value: unknown,
): AgentStructuredFallbackAuditV1 | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const candidate = value as Readonly<Record<string, unknown>>;
  if (
    candidate.contract_name !== "CompactTurnIntentDecisionV3" ||
    candidate.error_code !== "agent_structured_fallback_applied" ||
    candidate.submission_attempt !== 2 ||
    typeof candidate.used_model_message !== "boolean" ||
    (candidate.reason !== "repair_json_invalid" &&
      candidate.reason !== "validation_exhausted")
  ) {
    return undefined;
  }
  const boundedCodes = boundedFallbackList(candidate.failure_codes, 160);
  const boundedPaths = boundedFallbackList(candidate.validation_paths, 512);
  return {
    contract_name: "CompactTurnIntentDecisionV3",
    error_code: "agent_structured_fallback_applied",
    ...(boundedCodes ? { failure_codes: boundedCodes } : {}),
    validation_paths: boundedPaths ?? [],
    submission_attempt: 2,
    used_model_message: candidate.used_model_message,
    reason: candidate.reason,
  };
}

function boundedFallbackList(
  value: unknown,
  maximumItemLength: number,
): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") continue;
    const bounded = item.slice(0, maximumItemLength);
    if (bounded && !result.includes(bounded)) {
      result.push(bounded);
      if (result.length >= 32) break;
    }
  }
  return result;
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
  details: {
    readonly startedAt: string;
    readonly structuredAttempts: number;
    readonly validationAttempts: ReadonlyArray<AgentStructuredValidationAttemptAuditV1>;
    readonly structuredFallback?: AgentStructuredFallbackAuditV1;
  },
): StructuredTransportResult {
  return {
    value,
    audit: auditForAttempt(
      input,
      attempt,
      details.startedAt,
      details.structuredAttempts,
      details.validationAttempts,
      details.structuredFallback,
    ),
  };
}

function auditForAttempt(
  input: StructuredTransportRunInput,
  attempt: CompletionAttempt,
  startedAt: string,
  structuredAttempts: number,
  validationAttempts: ReadonlyArray<AgentStructuredValidationAttemptAuditV1> = [],
  structuredFallback?: AgentStructuredFallbackAuditV1,
): AgentTransportAttemptMetadataV1 {
  const choice = attempt.response.choices?.[0];
  const usage = attempt.response.usage;
  return {
    provider: input.credential.provider,
    model_ref: input.credential.model_ref,
    structured_transport: input.credential.execution_policy.structured_transport,
    thinking_format: input.credential.execution_policy.thinking_format,
    reasoning_control: input.credential.execution_policy.reasoning_control,
    reasoning_mode: input.credential.execution_policy.reasoning_mode,
    enable_thinking: input.credential.execution_policy.enable_thinking,
    thinking_budget_tokens:
      input.credential.execution_policy.thinking_budget_tokens ?? null,
    deadline_seconds: input.credential.execution_policy.deadline_seconds,
    max_output_tokens: input.credential.execution_policy.max_output_tokens,
    operation_policy_id: input.request.policy?.operation_policy_id ?? "agent.unknown.v1",
    operation_class:
      input.request.policy?.operation_class ??
      input.credential.execution_policy.operation_class,
    effective_timeout_ms: attempt.effectiveTimeoutMs ?? 0,
    request_bytes: requestByteCount(input),
    schema_bytes: schemaByteCount(input),
    response_bytes: attempt.response.transport_metadata?.response_bytes ?? null,
    response_activity_observed:
      attempt.response.transport_metadata?.response_activity_observed ?? true,
    attempt_stage: attempt.attemptStage ?? "initial",
    started_at: startedAt,
    first_response_at: attempt.firstResponseAt,
    last_activity_at:
      attempt.response.transport_metadata?.last_activity_at ?? attempt.finishedAt,
    finished_at: attempt.finishedAt,
    duration_ms: elapsedMilliseconds(startedAt, attempt.finishedAt),
    finish_reason:
      attempt.response.transport_metadata?.finish_reason ?? choice?.finish_reason ?? null,
    provider_trace_id:
      attempt.response.transport_metadata?.provider_trace_id ?? attempt.response.id ?? null,
    input_tokens: usage?.prompt_tokens ?? null,
    output_tokens: usage?.completion_tokens ?? null,
    reasoning_tokens: usage?.completion_tokens_details?.reasoning_tokens ?? null,
    transport_retry_count: attempt.retryCount,
    structured_attempt_count: structuredAttempts,
    structured_validation_attempts: validationAttempts.slice(0, 2),
    ...(structuredFallback ? { structured_fallback: structuredFallback } : {}),
  };
}

function validationAttemptAudit(
  validation: StructuredValidationResult,
  attempt: 1 | 2,
  attemptStage: "initial" | "structured_repair",
): AgentStructuredValidationAttemptAuditV1 {
  const candidate = validation.result?.violations;
  const rawViolations = Array.isArray(candidate) ? candidate.slice(0, 128) : [];
  const paths: string[] = [];
  const codes: string[] = [];
  let pathOverflow = false;
  let codeOverflow = false;
  for (const item of rawViolations) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const violation = item as Readonly<Record<string, unknown>>;
    const path = boundedViolationText(violation.path ?? violation.field_path, 512);
    const code = boundedViolationText(violation.code, 160);
    if (path && !paths.includes(path)) {
      if (paths.length < 32) paths.push(path);
      else pathOverflow = true;
    }
    if (code && !codes.includes(code)) {
      if (codes.length < 32) codes.push(code);
      else codeOverflow = true;
    }
  }
  if (codes.length === 0) {
    codes.push(validation.error_code ?? "agent_structured_output_invalid");
  }
  return {
    attempt,
    attempt_stage: attemptStage,
    violation_count: Math.max(1, Math.min(128, rawViolations.length)),
    validation_paths: paths,
    violation_codes: codes,
    repair_allowed: validation.result?.repair_allowed === true,
    truncated: Array.isArray(candidate) &&
      (candidate.length > 128 || pathOverflow || codeOverflow),
  };
}

function boundedViolations(result: Readonly<Record<string, unknown>> | undefined) {
  const candidate = result?.violations;
  if (!Array.isArray(candidate)) return [];
  return candidate.slice(0, 8).flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const violation = item as Readonly<Record<string, unknown>>;
    const code = boundedViolationText(violation.code, 160);
    const message = boundedViolationText(violation.message, 240);
    if (!code || !message) return [];
    const path = boundedViolationText(violation.path ?? violation.field_path, 240);
    const expected = boundedViolationValue(violation.expected);
    const actual = boundedViolationValue(violation.actual);
    return [{
      ...(path ? { path } : {}),
      code,
      message,
      ...(expected !== undefined ? { expected } : {}),
      ...(actual !== undefined ? { actual } : {}),
    }];
  });
}

function boundedViolationValue(value: unknown): unknown {
  if (value === undefined) return undefined;
  const canonical = canonicalJsonValue(value);
  return JSON.stringify(canonical).length <= 1_024 ? canonical : undefined;
}

function boundedInvalidResult(
  value: Readonly<Record<string, unknown>> | undefined,
): string | undefined {
  if (value === undefined) return undefined;
  return JSON.stringify(canonicalJsonValue(value)).slice(0, 8_192);
}

function boundedViolationText(value: unknown, limit: number): string | undefined {
  return typeof value === "string" && value.length > 0
    ? value.slice(0, limit)
    : undefined;
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
      (error.code === "agent_provider_transport_failed" ||
        error.code === "agent_provider_timeout") &&
      error.retryable)
  );
}

function normalizeTransportFailure(
  error: unknown,
  signal: AbortSignal,
  stage: ModelAttemptStage = "initial",
  attemptMetadata?: AgentTransportAttemptMetadataV1,
  manualRetryable = false,
): AgentOperationFailure {
  if (
    signal.aborted ||
    (error instanceof DOMException &&
      (error.name === "AbortError" || error.name === "TimeoutError")) ||
    isProviderTimeoutFailure(error)
  ) {
    return providerTimeout(
      stage,
      attemptMetadata,
      !signal.aborted,
      manualRetryable,
    );
  }
  if (
    error &&
    typeof error === "object" &&
    (error as { readonly code?: unknown }).code === "agent_model_capability_mismatch"
  ) {
    return new AgentOperationFailure(
      "agent_model_capability_mismatch",
      "agent_model_capability_mismatch",
      false,
      stage,
      attemptMetadata,
    );
  }
  if (
    error &&
    typeof error === "object" &&
    (error as { readonly code?: unknown }).code === "agent_structured_output_invalid"
  ) {
    return new AgentOperationFailure(
      "agent_structured_output_invalid",
      "agent_structured_output_invalid",
      manualRetryable,
      stage,
      attemptMetadata,
    );
  }
  if (error instanceof AgentOperationFailure) return error;
  return new AgentOperationFailure(
    "agent_provider_transport_failed",
    "agent_provider_transport_failed",
    manualRetryable || isPreActivityConnectionFailure(error),
    stage,
    attemptMetadata,
  );
}

function providerTimeout(
  stage: ModelAttemptStage = "initial",
  attemptMetadata?: AgentTransportAttemptMetadataV1,
  recoveryAllowed = false,
  manualRetryable = false,
): AgentOperationFailure {
  const retryable = manualRetryable ||
    (recoveryAllowed &&
      stage === "initial" &&
      attemptMetadata?.response_activity_observed === false &&
      (attemptMetadata?.effective_timeout_ms ?? 0) > 0);
  return new AgentOperationFailure(
    "agent_provider_timeout",
    "agent_provider_timeout",
    retryable,
    stage,
    attemptMetadata,
  );
}

function failureMetadata(
  input: StructuredTransportRunInput,
  startedAt: string,
  finishedAt: string,
  effectiveTimeoutMs: number,
  stage: ModelAttemptStage,
  error?: unknown,
): AgentTransportAttemptMetadataV1 {
  const shape = safeFailureShape(error);
  return {
    provider: input.credential.provider,
    model_ref: input.credential.model_ref,
    structured_transport: input.credential.execution_policy.structured_transport,
    thinking_format: input.credential.execution_policy.thinking_format,
    reasoning_control: input.credential.execution_policy.reasoning_control,
    reasoning_mode: input.credential.execution_policy.reasoning_mode,
    enable_thinking: input.credential.execution_policy.enable_thinking,
    thinking_budget_tokens:
      input.credential.execution_policy.thinking_budget_tokens ?? null,
    deadline_seconds: input.credential.execution_policy.deadline_seconds,
    max_output_tokens: input.credential.execution_policy.max_output_tokens,
    operation_policy_id: input.request.policy?.operation_policy_id ?? "agent.unknown.v1",
    operation_class:
      input.request.policy?.operation_class ??
      input.credential.execution_policy.operation_class,
    effective_timeout_ms: Math.max(0, Math.round(effectiveTimeoutMs)),
    request_bytes: requestByteCount(input),
    schema_bytes: schemaByteCount(input),
    response_bytes: safeResponseBytes(error),
    response_activity_observed: responseActivityObserved(error),
    attempt_stage: stage,
    started_at: startedAt,
    finished_at: finishedAt,
    duration_ms: elapsedMilliseconds(startedAt, finishedAt),
    transport_retry_count: stage === "transport_retry" ? 1 : 0,
    structured_attempt_count: stage === "structured_repair" ? 2 : 1,
    ...(shape.safeExceptionClass
      ? { safe_exception_class: shape.safeExceptionClass }
      : {}),
    ...(shape.safeErrorCode ? { safe_error_code: shape.safeErrorCode } : {}),
    ...(shape.httpStatus ? { http_status: shape.httpStatus } : {}),
    ...(shape.providerTraceId ? { provider_trace_id: shape.providerTraceId } : {}),
    ...safeActivityTimes(error),
  };
}

function safeResponseBytes(error: unknown): number | null {
  if (!error || typeof error !== "object") return null;
  const value = (error as { readonly response_bytes?: unknown }).response_bytes;
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? Math.min(value, 4_194_304)
    : null;
}

function safeActivityTimes(error: unknown): {
  readonly first_response_at?: string;
  readonly last_activity_at?: string;
} {
  if (!error || typeof error !== "object") return {};
  const value = error as {
    readonly first_response_at?: unknown;
    readonly last_activity_at?: unknown;
  };
  return {
    ...(typeof value.first_response_at === "string"
      ? { first_response_at: value.first_response_at }
      : {}),
    ...(typeof value.last_activity_at === "string"
      ? { last_activity_at: value.last_activity_at }
      : {}),
  };
}

function responseActivityObserved(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as {
    readonly response_started?: unknown;
    readonly response?: { readonly status?: unknown };
  };
  return candidate.response_started === true || boundedStatus(candidate.response?.status) !== undefined;
}

function elapsedMilliseconds(startedAt: string, finishedAt: string): number {
  const elapsed = Date.parse(finishedAt) - Date.parse(startedAt);
  return Math.max(0, Math.min(900_000, Number.isFinite(elapsed) ? elapsed : 0));
}

function requestByteCount(input: StructuredTransportRunInput): number {
  return new TextEncoder().encode(
    JSON.stringify({ system: input.systemPrompt, user: input.userPrompt }),
  ).byteLength;
}

function schemaByteCount(input: StructuredTransportRunInput): number {
  return new TextEncoder().encode(JSON.stringify(input.schema)).byteLength;
}

function safeFailureShape(error: unknown): {
  readonly safeExceptionClass?: string;
  readonly safeErrorCode?: string;
  readonly httpStatus?: number;
  readonly providerTraceId?: string;
} {
  if (!error || typeof error !== "object") return {};
  const candidate = error as {
    readonly name?: unknown;
    readonly code?: unknown;
    readonly status?: unknown;
    readonly statusCode?: unknown;
    readonly request_id?: unknown;
    readonly requestId?: unknown;
    readonly response?: {
      readonly status?: unknown;
      readonly headers?: { readonly get?: (name: string) => string | null };
    };
  };
  const constructorName = (error as { constructor?: { name?: unknown } }).constructor?.name;
  const status = boundedStatus(
    candidate.status ?? candidate.statusCode ?? candidate.response?.status,
  );
  const trace =
    candidate.request_id ??
    candidate.requestId ??
    candidate.response?.headers?.get?.("x-request-id");
  const safeExceptionClass = boundedDiagnostic(
    candidate.name === "Error" && constructorName !== "Error"
      ? constructorName
      : candidate.name ?? constructorName,
    160,
  );
  const safeErrorCode = boundedDiagnostic(candidate.code, 120);
  const providerTraceId = boundedDiagnostic(trace, 320);
  return {
    ...(safeExceptionClass ? { safeExceptionClass } : {}),
    ...(safeErrorCode ? { safeErrorCode } : {}),
    ...(status ? { httpStatus: status } : {}),
    ...(providerTraceId ? { providerTraceId } : {}),
  };
}

function boundedDiagnostic(value: unknown, maximum: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const bounded = value.slice(0, maximum);
  return /^[A-Za-z0-9._:/-]+$/.test(bounded) ? bounded : undefined;
}

function boundedStatus(value: unknown): number | undefined {
  const status = typeof value === "number" ? value : Number(value);
  return Number.isInteger(status) && status >= 100 && status <= 599
    ? status
    : undefined;
}

function structuredFailure(
  stage: ModelAttemptStage = "structured_repair",
  attemptMetadata?: AgentTransportAttemptMetadataV1,
  retryable = false,
) {
  return new AgentOperationFailure(
    "agent_structured_output_invalid",
    "agent_structured_output_invalid",
    retryable,
    stage,
    terminalAttemptMetadata(attemptMetadata, "agent_structured_output_invalid"),
  );
}

function terminalValidationFailure(
  code: string,
  attemptMetadata?: AgentTransportAttemptMetadataV1,
  retryable = false,
) {
  return new AgentOperationFailure(
    code,
    code,
    retryable,
    attemptMetadata?.attempt_stage ?? "initial",
    terminalAttemptMetadata(attemptMetadata, code),
  );
}

function terminalAttemptMetadata(
  attemptMetadata: AgentTransportAttemptMetadataV1 | undefined,
  code: string,
): AgentTransportAttemptMetadataV1 | undefined {
  return attemptMetadata
    ? { ...attemptMetadata, safe_error_code: code.slice(0, 120) }
    : undefined;
}

function isManualRetryableIntake(input: StructuredTransportRunInput): boolean {
  return input.request.operation === "decide_turn_intent";
}
