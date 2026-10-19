import { createHash } from "node:crypto";

import OpenAI from "openai";

import {
  chatCompletionChunkFailure,
  normalizeChatCompletionChunk,
  sanitizeChatCompletionChunk,
} from "./chat-completion-chunk-normalizer.js";
import {
  buildWorkflowModelCallSkillContext,
  workflowModelCallCapture,
  modelCallFailure,
  type WorkflowModelCallClient,
} from "./workflow-model-calls.js";
import type {
  AgentRunRequest,
  AgentModelTraceStreamingChunkV1,
  AgentStructuredValidationAttemptAuditV1,
  AgentTransportAttemptMetadataV1,
} from "./generated/agent-runtime.js";
import {
  AgentOperationFailure,
  isProviderBalanceFailure,
  isProviderTimeoutFailure,
  PROVIDER_INSUFFICIENT_BALANCE_MESSAGE,
} from "./operation-recovery.js";
import {
  isAcceptanceReplaySource,
  type AgentCredentialSnapshot,
  type AgentRuntimeTransportSource,
} from "./python-internal-client.js";
import { modelAttemptTimeoutMs, type ModelAttemptStage } from "./run-budget.js";
import {
  claimAgentModelTraceOutcome,
  isAgentModelTraceFailure,
  recordAgentModelTraceOutcome,
  type AgentModelTraceClient,
} from "./model-trace.js";
import type { LoadedSkill } from "./skills.js";
import { intakeRepairPolicy } from "./prompts/intake-repair.js";
import { treatmentRepairPolicy } from "./prompts/treatment-repair.js";
import {
  brandFormRepairPolicy,
  brandFormSupplementalRepairPolicy,
  brandTreatmentReviewRepairPolicy,
} from "./prompts/brand-form-repair.js";


interface StructuredCompletionRequestBase {
  readonly thinking?: { readonly type: "enabled" | "disabled" };
  readonly model: string;
  readonly messages: ReadonlyArray<Readonly<Record<string, unknown>>>;
  readonly max_tokens: number;
  readonly enable_thinking?: boolean;
  readonly thinking_budget?: number;
  readonly reasoning_effort?: "minimal" | "low" | "medium" | "high";
  readonly provider?: {
    readonly only: ReadonlyArray<"openai">;
    readonly require_parameters: true;
    readonly allow_fallbacks: false;
  };
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
  readonly response_format?:
    | { readonly type: "json_object" }
    | {
      readonly type: "json_schema";
      readonly json_schema: {
        readonly name: "agent_structured_result";
        readonly strict: true;
        readonly schema: Readonly<Record<string, unknown>>;
      };
    };
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
  readonly normalized_chunks?: ReadonlyArray<AgentModelTraceStreamingChunkV1>;
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
    readonly idleTimeoutMs?: number;
    readonly onChunk?: (chunk: unknown) => void;
    readonly onPresentation?: (segment: PresentationSegment, text: string) => void;
    readonly presentationAnswerKey?: string | null;
    readonly attempt?: number;
    readonly attemptStage?: ModelAttemptStage;
  },
) => Promise<StructuredCompletionResponse>;

export type PresentationSegment = "reasoning" | "answer";

// Live answer extraction is currently disabled for every operation; only
// reasoning streams live. A chat turn can span several Agent calls and the
// engine may author the final message, and node prompts are rendered by the
// engine from structured brief fields, so neither `assistant_message` nor
// `editable_prompt` is reliably the text the user ends up seeing. Python
// publishes the committed text as the answer instead.
export const PRESENTATION_ANSWER_KEYS: Readonly<Record<string, string>> = Object.freeze({});

export function presentationAnswerKeyForOperation(operation: string): string | null {
  return PRESENTATION_ANSWER_KEYS[operation] ?? null;
}

export type PresentationDeltaSink = (
  segment: PresentationSegment,
  text: string,
  attempt: number,
) => void;

interface StructuredValidationResult {
  readonly status: string;
  readonly error_code?: string | null;
  readonly result?: Readonly<Record<string, unknown>>;
}

export interface StructuredTransportRunInput {
  readonly credential: AgentRuntimeTransportSource;
  readonly request: AgentRunRequest;
  readonly systemPrompt: string;
  readonly userPrompt: string;
  readonly schema: Readonly<Record<string, unknown>>;
  readonly loadedSkills?: ReadonlyArray<LoadedSkill>;
  readonly traceClient?: AgentModelTraceClient & WorkflowModelCallClient;
  readonly signal: AbortSignal;
  readonly onPresentation?: PresentationDeltaSink;
  readonly presentationAnswerKey?: string | null;
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
      policy.structured_transport !== "non_streaming_json_schema" &&
      policy.structured_transport !== "streaming_json_object"
    ) {
      throw new AgentOperationFailure(
        "agent_model_capability_mismatch",
        "agent_model_capability_mismatch",
        false,
      );
    }
    const startedAt = this.#now().toISOString();
    const presentationAttempt = { value: 0 };
    const primaryRequest = buildPrimaryStructuredCompletionRequest(input);
    const primary = await this.#executeWithRetry(
      primaryRequest,
      input,
      () => ++presentationAttempt.value,
    );
    let structuredAttempts = 1;
    const validationAttempts: AgentStructuredValidationAttemptAuditV1[] = [];
    let value = primaryValue(input, primary.response);
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
        roleContractFailureCode(input.request, validation) ??
          validation.error_code ??
          "agent_structured_output_invalid",
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
    if ((primary.capabilityFallbackCount ?? 0) > 0) {
      throw structuredFailure(
        "capability_fallback",
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
      repairPayload(input, validation, value, primary.response.choices?.[0]?.message?.content),
      input,
      "structured_repair",
      ++presentationAttempt.value,
    );
    value = repairContent(repair.response);
    if (value === undefined) {
      const malformedRepair = malformedJsonValidation(false);
      validationAttempts.push(
        validationAttemptAudit(malformedRepair, 2, "structured_repair"),
      );
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
      const roleContractCode = roleContractFailureCode(input.request, repaired);
      if (roleContractCode) {
        throw terminalValidationFailure(
          roleContractCode,
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
    return resultFor(accepted, input, repair, {
      startedAt,
      structuredAttempts,
      validationAttempts,
    });
  }

  async #executeWithRetry(
    request: StructuredCompletionRequest,
    input: StructuredTransportRunInput,
    nextAttempt: () => number,
  ): Promise<CompletionAttempt> {
    try {
      return await this.#executeOnce(request, input, "initial", nextAttempt());
    } catch (error) {
      if (isAgentModelTraceFailure(error)) throw error;
      if (isCertifiedJsonObjectCapabilityFallback(error, input)) {
        const fallback = await this.#executeOnce(
          jsonObjectCapabilityFallbackRequest(request),
          input,
          "capability_fallback",
          nextAttempt(),
        );
        return { ...fallback, capabilityFallbackCount: 1 };
      }
      if (
        input.credential.execution_policy.transport_retry_limit < 1 ||
        !isRetryablePreActivityFailure(error)
      ) {
        throw normalizeTransportFailure(error, input.signal);
      }
      await this.#sleep(250);
      const retry = await this.#executeOnce(
        request,
        input,
        "transport_retry",
        nextAttempt(),
      );
      return { ...retry, retryCount: 1 };
    }
  }

  async #executeOnce(
    request: StructuredCompletionRequest,
    input: StructuredTransportRunInput,
    stage: ModelAttemptStage,
    attempt: number,
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
    const capture = workflowModelCallCapture(
      input.traceClient, input.credential, input.request, stage,
      request.stream ? "sdk_stream_chunks" : "sdk_response",
      input.loadedSkills ?? [],
    );
    capture?.begin({
      agent_request: input.request, system_prompt: input.systemPrompt,
      user_prompt: input.userPrompt, output_schema: input.schema,
      loaded_skills: input.loadedSkills ?? [], provider_request: request,
      skill_context: buildWorkflowModelCallSkillContext(input.request, input.loadedSkills ?? []),
      provider: input.credential.provider, model_ref: input.credential.model_ref,
      execution_policy: input.credential.execution_policy, effective_timeout_ms: timeoutMs,
      transport_options: { timeout_ms: timeoutMs, max_retries: 0, max_output_bytes: input.request.policy?.max_output_bytes ?? 262_144 },
      ...(!isAcceptanceReplaySource(input.credential) ? { base_url: input.credential.base_url } : {}),
    });
    const presentationEnabled = Boolean(
      input.onPresentation &&
      input.request.presentation_stream_id &&
      input.request.presentation_channel &&
      input.credential.execution_policy.structured_transport === "streaming_json_object" &&
      request.stream,
    );
    try {
      const response = isAcceptanceReplaySource(input.credential)
        ? await claimAgentModelTraceOutcome(
          {
            ...input,
            loadedSkills: input.loadedSkills ?? [],
          },
          request,
          stage,
        )
        : await this.#execute(request, {
          apiKey: input.credential.api_key,
          baseUrl: input.credential.base_url,
          signal: input.signal,
          timeoutMs,
          maxOutputBytes: input.request.policy?.max_output_bytes ?? 262_144,
          idleTimeoutMs: 90_000,
          ...(capture ? { onChunk: (chunk: unknown) => capture.chunk(chunk) } : {}),
          ...(presentationEnabled
            ? {
              onPresentation: (segment: PresentationSegment, text: string) => {
                input.onPresentation?.(segment, text, attempt);
              },
            }
            : {}),
          ...(presentationEnabled && input.presentationAnswerKey !== undefined
            ? { presentationAnswerKey: input.presentationAnswerKey }
            : {}),
          attempt,
          attemptStage: stage,
        });
      capture?.finish({ response });
      await recordAgentModelTraceOutcome(
        {
          ...input,
          loadedSkills: input.loadedSkills ?? [],
        },
        request,
        stage,
        response,
        true,
      );
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
      capture?.finish({ error: modelCallFailure(error) }, true, false);
      if (isAgentModelTraceFailure(error)) throw error;
      const normalized = normalizeTransportFailure(
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
      try {
        await recordAgentModelTraceOutcome(
          {
            ...input,
            loadedSkills: input.loadedSkills ?? [],
          },
          request,
          stage,
          normalized,
          false,
        );
      } catch {
        // Trace capture is secondary to the owning Provider failure boundary.
      }
      throw normalized;
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
  readonly capabilityFallbackCount?: number;
}

export async function executeOpenAICompletion(
  request: StructuredCompletionRequest,
  options: {
    readonly apiKey: string;
    readonly baseUrl: string;
    readonly signal: AbortSignal;
    readonly timeoutMs: number;
    readonly maxOutputBytes?: number;
    readonly idleTimeoutMs?: number;
    readonly onChunk?: (chunk: unknown) => void;
    readonly onPresentation?: (segment: PresentationSegment, text: string) => void;
    readonly presentationAnswerKey?: string | null;
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
      ...(options.idleTimeoutMs !== undefined
        ? { idleTimeoutMs: options.idleTimeoutMs }
        : {}),
      ...(options.onChunk ? { onChunk: options.onChunk } : {}),
      ...(options.onPresentation
        ? { onPresentation: options.onPresentation }
        : {}),
      ...(options.presentationAnswerKey !== undefined
        ? { answerKey: options.presentationAnswerKey }
        : {}),
    });
  } finally {
    clearTimeout(timer);
    options.signal.removeEventListener("abort", abortFromCaller);
  }
}

// Time-led batching keeps live typing smooth while bounding per-event envelope
// overhead against the runtime stream byte budget.
const PRESENTATION_FLUSH_INTERVAL_MS = 250;
const PRESENTATION_FLUSH_CHARACTERS = 1024;

class PresentationBatcher {
  readonly #emit: (segment: PresentationSegment, text: string) => void;
  readonly #buffers: Record<PresentationSegment, string> = {
    reasoning: "",
    answer: "",
  };
  readonly #timers: Partial<Record<PresentationSegment, ReturnType<typeof setTimeout>>> = {};

  constructor(emit: (segment: PresentationSegment, text: string) => void) {
    this.#emit = emit;
  }

  push(segment: PresentationSegment, text: string): void {
    if (text.length === 0) return;
    this.#buffers[segment] += text;
    if (this.#timers[segment] === undefined) {
      this.#timers[segment] = setTimeout(
        () => this.flush(segment),
        PRESENTATION_FLUSH_INTERVAL_MS,
      );
    }
    if (Array.from(this.#buffers[segment]).length >= PRESENTATION_FLUSH_CHARACTERS) {
      this.flush(segment);
    }
  }

  flush(segment: PresentationSegment): void {
    const timer = this.#timers[segment];
    if (timer !== undefined) clearTimeout(timer);
    delete this.#timers[segment];
    const text = this.#buffers[segment];
    this.#buffers[segment] = "";
    if (text.length === 0) return;
    let part = "";
    for (const character of text) {
      const candidate = part + character;
      if (Buffer.byteLength(candidate, "utf8") > 4096 && part.length > 0) {
        this.#safeEmit(segment, part);
        part = character;
      } else {
        part = candidate;
      }
    }
    if (part.length > 0) this.#safeEmit(segment, part);
  }

  flushAll(): void {
    this.flush("reasoning");
    this.flush("answer");
  }

  #safeEmit(segment: PresentationSegment, text: string): void {
    try {
      this.#emit(segment, text);
    } catch {
      // Presentation is best effort and cannot affect structured parsing.
    }
  }
}

class AnswerStringScanner {
  readonly #answerKey: string;
  readonly #onText: (text: string) => void;
  #state:
    | "normal"
    | "key_string"
    | "key_escape"
    | "after_key"
    | "after_colon"
    | "skip_value_string"
    | "skip_value_escape"
    | "answer_string"
    | "answer_escape"
    | "answer_unicode" = "normal";
  #keyText = "";
  #keyCandidate = "";
  #answerUnicode = "";
  #pendingHighSurrogate: number | undefined;
  #found = false;

  constructor(answerKey: string, onText: (text: string) => void) {
    this.#answerKey = answerKey;
    this.#onText = onText;
  }

  feed(content: string): void {
    for (const character of content) this.#consume(character);
  }

  #consume(character: string): void {
    switch (this.#state) {
      case "normal":
        if (character === '"') {
          this.#keyText = "";
          this.#state = "key_string";
        }
        return;
      case "key_string":
        if (character === '"') {
          this.#keyCandidate = decodeJsonString(this.#keyText);
          this.#state = "after_key";
        } else if (character === "\\") {
          this.#keyText += character;
          this.#state = "key_escape";
        } else {
          this.#keyText += character;
        }
        return;
      case "key_escape":
        this.#keyText += character;
        this.#state = character === "u" ? "key_string" : "key_string";
        return;
      case "after_key":
        if (/\s/.test(character)) return;
        if (character === ":") {
          this.#state = "after_colon";
        } else {
          this.#state = "normal";
          this.#consume(character);
        }
        return;
      case "after_colon":
        if (/\s/.test(character)) return;
        if (character !== '"') {
          this.#state = "normal";
          this.#consume(character);
          return;
        }
        if (!this.#found && this.#keyCandidate === this.#answerKey) {
          this.#found = true;
          this.#answerUnicode = "";
          this.#pendingHighSurrogate = undefined;
          this.#state = "answer_string";
        } else {
          this.#state = "skip_value_string";
        }
        return;
      case "skip_value_string":
        if (character === "\\") this.#state = "skip_value_escape";
        else if (character === '"') this.#state = "normal";
        return;
      case "skip_value_escape":
        this.#state = "skip_value_string";
        return;
      case "answer_string":
        if (character === '"') {
          this.#flushPendingHighSurrogate();
          this.#state = "normal";
        } else if (character === "\\") {
          this.#state = "answer_escape";
        } else {
          this.#flushPendingHighSurrogate();
          this.#emit(character);
        }
        return;
      case "answer_escape":
        if (character === "u") {
          this.#answerUnicode = "";
          this.#state = "answer_unicode";
          return;
        }
        this.#flushPendingHighSurrogate();
        const escaped = ({
          '"': '"',
          "\\": "\\",
          "/": "/",
          b: "\b",
          f: "\f",
          n: "\n",
          r: "\r",
          t: "\t",
        } as Record<string, string>)[character];
        if (escaped !== undefined) this.#emit(escaped);
        this.#state = "answer_string";
        return;
      case "answer_unicode":
        this.#answerUnicode += character;
        if (this.#answerUnicode.length < 4) return;
        const codeUnit = Number.parseInt(this.#answerUnicode, 16);
        if (Number.isNaN(codeUnit)) {
          this.#state = "answer_string";
          return;
        }
        if (this.#pendingHighSurrogate !== undefined) {
          if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
            this.#emit(String.fromCodePoint(
              0x10000 + ((this.#pendingHighSurrogate - 0xd800) << 10) + codeUnit - 0xdc00,
            ));
            this.#pendingHighSurrogate = undefined;
          } else {
            this.#emit(String.fromCharCode(this.#pendingHighSurrogate));
            this.#pendingHighSurrogate = undefined;
            this.#consumeUnicodeCodeUnit(codeUnit);
          }
        } else {
          this.#consumeUnicodeCodeUnit(codeUnit);
        }
        this.#answerUnicode = "";
        this.#state = "answer_string";
        return;
    }
  }

  #consumeUnicodeCodeUnit(codeUnit: number): void {
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      this.#pendingHighSurrogate = codeUnit;
    } else {
      this.#emit(String.fromCharCode(codeUnit));
    }
  }

  #flushPendingHighSurrogate(): void {
    if (this.#pendingHighSurrogate !== undefined) {
      this.#emit(String.fromCharCode(this.#pendingHighSurrogate));
      this.#pendingHighSurrogate = undefined;
    }
  }

  #emit(text: string): void {
    if (text.length > 0) this.#onText(text);
  }
}

function decodeJsonString(raw: string): string {
  try {
    return JSON.parse(`"${raw}"`) as string;
  } catch {
    return raw;
  }
}

export async function aggregateStreamingJsonCompletion(
  stream: AsyncIterable<unknown>,
  options: {
    readonly signal: AbortSignal;
    readonly maxOutputBytes: number;
    readonly idleTimeoutMs?: number;
    readonly now?: () => Date;
    readonly onChunk?: (chunk: unknown) => void;
    readonly onPresentation?: (segment: PresentationSegment, text: string) => void;
    readonly answerKey?: string | null;
  },
): Promise<StructuredCompletionResponse> {
  const now = options.now ?? (() => new Date());
  const iterator = stream[Symbol.asyncIterator]();
  const streamController = new AbortController();
  const abortFromCaller = () => streamController.abort(options.signal.reason);
  options.signal.addEventListener("abort", abortFromCaller, { once: true });
  if (options.signal.aborted) streamController.abort(options.signal.reason);
  const idleTimeoutMs = Math.max(1, options.idleTimeoutMs ?? 90_000);
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let stallError: Error | undefined;
  const resetIdleTimer = () => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      stallError = streamingStallFailure();
      streamController.abort();
    }, idleTimeoutMs);
  };
  let content = "";
  let responseBytes = 0;
  let responseActivityObserved = false;
  let firstContentAt: string | null = null;
  let lastActivityAt: string | null = null;
  let finishReason: string | null = null;
  let providerTraceId: string | null = null;
  let terminal = false;
  const normalizedChunks: AgentModelTraceStreamingChunkV1[] = [];
  const presentationBatcher = options.onPresentation
    ? new PresentationBatcher(options.onPresentation)
    : undefined;
  const answerScanner =
    presentationBatcher !== undefined && options.answerKey
      ? new AnswerStringScanner(options.answerKey, (text) => {
        presentationBatcher.push("answer", text);
      })
      : undefined;
  try {
    resetIdleTimer();
    while (true) {
      let item: IteratorResult<unknown>;
      try {
        item = await abortableNext(iterator, streamController.signal);
      } catch (error) {
        if (stallError !== undefined) throw stallError;
        throw error;
      }
      if (stallError !== undefined) throw stallError;
      if (item.done) break;
      try {
        options.onChunk?.(sanitizeChatCompletionChunk(item.value));
      } catch { /* Diagnostic observers cannot affect parsing. */ }
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
        answerScanner?.feed(parsed.content);
      }
      if (parsed.reasoningContent !== null && parsed.reasoningContent.length > 0) {
        presentationBatcher?.push("reasoning", parsed.reasoningContent);
      }
      if (parsed.content !== null || parsed.finishReason !== null) {
        normalizedChunks.push({
          sequence_no: normalizedChunks.length + 1,
          ...(parsed.content !== null ? { content: parsed.content } : {}),
          ...(parsed.finishReason !== null
            ? { finish_reason: parsed.finishReason }
            : {}),
        });
      }
      if (parsed.finishReason !== null) {
        finishReason = parsed.finishReason;
        terminal = true;
      }
      if (
        (parsed.content !== null && parsed.content.length > 0) ||
        parsed.reasoningContentPresent ||
        parsed.finishReason !== null
      ) {
        resetIdleTimer();
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
    presentationBatcher?.flushAll();
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
        normalized_chunks: normalizedChunks,
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
    presentationBatcher?.flushAll();
    if (idleTimer !== undefined) clearTimeout(idleTimer);
    options.signal.removeEventListener("abort", abortFromCaller);
    try {
      const close = iterator.return?.();
      if (close !== undefined) {
        if (stallError !== undefined) {
          void close.catch(() => undefined);
        } else {
          await close;
        }
      }
    } catch {
      // Stream cleanup cannot replace the authoritative transport outcome.
    }
  }
}

function streamingStallFailure(): Error {
  return Object.assign(new Error("Agent provider stream stalled."), {
    name: "TimeoutError",
    code: "agent_provider_timeout",
    stall_detected: true,
  });
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
    StructuredTransportRunInput,
    "credential" | "systemPrompt" | "userPrompt" | "schema"
  >,
): StructuredCompletionRequest {
  if (
    isJsonObjectTransport(input.credential.execution_policy.structured_transport)
  ) {
    const openrouter = openrouterRequestProjection(input.credential);
    const common = {
      model: input.credential.model_id,
      messages: [
        {
          role: "system" as const,
          content: [
            input.systemPrompt,
            "Return exactly one JSON object matching the supplied schema.",
            `JSON Schema: ${JSON.stringify(input.schema)}`,
          ].join("\n\n"),
        },
        { role: "user" as const, content: input.userPrompt },
      ],
      max_tokens: input.credential.execution_policy.max_output_tokens,
      ...reasoningPayload(input.credential.execution_policy),
      ...openrouter,
    };
    if (
      input.credential.execution_policy.structured_transport ===
      "streaming_json_object"
    ) {
      return { ...common, stream: true, response_format: { type: "json_object" } };
    }
    return {
      ...common,
      stream: false,
      response_format: structuredResponseFormat(input.credential, input.schema),
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
  invalidContent?: string | null,
): StructuredCompletionRequest {
  const boundedInvalidValue = boundedInvalidResult(invalidValue);
  const currentUserInput = "user_input" in input.request.context
    ? input.request.context.user_input : undefined;
  const isIntake = input.request.operation === "decide_turn_intent" &&
    input.request.contract_name === "CompactTurnIntentDecisionV3" &&
    typeof currentUserInput === "string";
  const isTreatment = input.request.operation === "brand_treatment_step" &&
    input.request.contract_name === "CreativeTreatmentOutputV1";
  const isBrandTreatmentReview = input.request.operation === "brand_treatment_review" &&
    input.request.validation_profile === "brand_treatment_review_sources_v1";
  const isSupplementalBrandForm = input.request.operation === "brand_slot_form" &&
    input.request.validation_profile === "brand_form_supplemental_novelty_v1";
  const isBrandForm = input.request.operation === "brand_slot_form" &&
    input.request.validation_profile === "brand_form_slots_v1";
  const violations = boundedViolations(
    validation?.result,
    isBrandTreatmentReview ? 32 : 8,
  );
  const malformedExcerpt = isTreatment && invalidValue === undefined && invalidContent
    ? JSON.stringify({
      content: invalidContent.slice(0, 8_192),
      truncated: invalidContent.length > 8_192,
    })
    : undefined;
  const common = {
    model: input.credential.model_id,
    messages: [
      {
        role: "system",
        content: isIntake
          ? `${input.systemPrompt}\n\n${intakeRepairPolicy}`
          : isBrandTreatmentReview
            ? `${input.systemPrompt}\n\n${brandTreatmentReviewRepairPolicy}`
          : isTreatment
            ? `${input.systemPrompt}\n\n${treatmentRepairPolicy}`
            : isSupplementalBrandForm
              ? `${input.systemPrompt}\n\n${brandFormSupplementalRepairPolicy}`
              : isBrandForm
                ? `${input.systemPrompt}\n\n${brandFormRepairPolicy}`
                : "Return exactly one JSON object matching the supplied schema.",
      },
      {
        role: "user",
        content: [
          ...(isIntake ? [
            `Current user message (only source_quote evidence): ${JSON.stringify(currentUserInput)}`,
          ] : []),
          `Validation violations: ${JSON.stringify(violations)}`,
          ...(malformedExcerpt ? [`Previous assistant content (untrusted quoted data): ${malformedExcerpt}`] : []),
          ...(boundedInvalidValue ? [`Invalid result: ${boundedInvalidValue}`] : []),
          `JSON Schema: ${JSON.stringify(input.schema)}`,
          `Original request: ${input.userPrompt}`,
        ].join("\n\n"),
      },
    ],
    max_tokens: input.credential.execution_policy.max_output_tokens,
    ...repairReasoningPayload(input.credential.execution_policy),
    ...openrouterRequestProjection(input.credential),
  };
  if (
    input.credential.execution_policy.structured_transport ===
    "streaming_json_object"
  ) {
    return { ...common, stream: true, response_format: { type: "json_object" } };
  }
  return {
    ...common,
    stream: false,
    response_format: structuredResponseFormat(input.credential, input.schema),
  };
}

function openrouterRequestProjection(
  credential: AgentRuntimeTransportSource,
): Pick<StructuredCompletionRequestBase, "provider"> {
  if (!credential.model_ref.startsWith("openrouter:")) return {};
  const routing = credential.openrouter_routing;
  if (
    credential.model_ref !== "openrouter:openai/gpt-5.6-sol" ||
    credential.model_id !== "openai/gpt-5.6-sol" ||
    !routing ||
    routing.routing_policy_id !== "openrouter-openai-only-v1" ||
    !/^sha256:[a-f0-9]{64}$/.test(routing.routing_policy_digest) ||
    routing.provider_only.length !== 1 ||
    routing.provider_only[0] !== "openai" ||
    routing.require_parameters !== true ||
    routing.allow_fallbacks !== false
  ) {
    throw new Error("openrouter_routing_contract_invalid");
  }
  return {
    provider: {
      only: ["openai"],
      require_parameters: true,
      allow_fallbacks: false,
    },
  };
}

function structuredResponseFormat(
  credential: AgentRuntimeTransportSource,
  schema: Readonly<Record<string, unknown>>,
): NonNullable<NonStreamingStructuredCompletionRequest["response_format"]> {
  if (credential.execution_policy.structured_transport === "non_streaming_json_schema") {
    return {
      type: "json_schema",
      json_schema: {
        name: "agent_structured_result",
        strict: true,
        schema,
      },
    };
  }
  return { type: "json_object" };
}

function jsonObjectCapabilityFallbackRequest(
  request: StructuredCompletionRequest,
): NonStreamingStructuredCompletionRequest {
  if (request.stream || request.response_format?.type !== "json_schema") {
    throw new Error("agent_model_capability_mismatch");
  }
  return {
    ...request,
    response_format: { type: "json_object" },
  };
}

function isCertifiedJsonObjectCapabilityFallback(
  error: unknown,
  input: StructuredTransportRunInput,
): boolean {
  if (
    input.credential.model_ref !== "openrouter:openai/gpt-5.6-sol" ||
    input.credential.execution_policy.structured_transport !==
      "non_streaming_json_schema" ||
    input.credential.execution_policy.json_object_fallback_certified !== true ||
    input.credential.execution_policy.max_model_submissions !== 2 ||
    !(error instanceof AgentOperationFailure)
  ) {
    return false;
  }
  const metadata = error.attemptMetadata;
  return (
    metadata?.attempt_stage === "initial" &&
    (metadata.http_status === 400 || metadata.http_status === 422) &&
    (metadata.safe_error_code === "response_format_unsupported" ||
      metadata.safe_error_code === "json_schema_unsupported")
  );
}

function reasoningPayload(policy: AgentCredentialSnapshot["execution_policy"]): {
  readonly thinking?: { readonly type: "enabled" | "disabled" };
  readonly enable_thinking?: boolean;
  readonly thinking_budget?: number;
  readonly reasoning_effort?: "minimal" | "low" | "medium" | "high";
} {
  if (policy.reasoning_control === "ark_thinking") {
    return { thinking: { type: policy.enable_thinking ? "enabled" : "disabled" } };
  }
  if (policy.reasoning_control === "reasoning_effort") {
    if (policy.reasoning_effort == null) {
      throw new Error("agent_model_capability_mismatch");
    }
    return { reasoning_effort: policy.reasoning_effort };
  }
  return {
    enable_thinking: policy.enable_thinking,
    ...(typeof policy.thinking_budget_tokens === "number"
      ? { thinking_budget: policy.thinking_budget_tokens }
      : {}),
  };
}

function repairReasoningPayload(
  policy: AgentCredentialSnapshot["execution_policy"],
): {
  readonly thinking?: { readonly type: "disabled" };
  readonly enable_thinking?: boolean;
  readonly reasoning_effort?: "minimal";
} {
  if (policy.reasoning_control === "ark_thinking") {
    return { thinking: { type: "disabled" } };
  }
  if (policy.reasoning_control === "reasoning_effort") {
    return { reasoning_effort: "minimal" };
  }
  return { enable_thinking: false };
}

function isJsonObjectTransport(transport: string): boolean {
  return transport === "non_streaming_json_object" ||
    transport === "non_streaming_json_schema" ||
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

function parseObject(value: string | undefined | null) {
  if (!value) return undefined;
  const candidate = fencedJsonContent(value) ?? value.trim();
  if (!candidate) return undefined;
  try {
    const parsed: unknown = JSON.parse(candidate);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Readonly<Record<string, unknown>>)
      : undefined;
  } catch {
    return undefined;
  }
}

function fencedJsonContent(value: string): string | undefined {
  const match = value.trim().match(/^```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*$/i);
  return match?.[1]?.trim() || undefined;
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
    ),
  };
}

function auditForAttempt(
  input: StructuredTransportRunInput,
  attempt: CompletionAttempt,
  startedAt: string,
  structuredAttempts: number,
  validationAttempts: ReadonlyArray<AgentStructuredValidationAttemptAuditV1> = [],
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
    reasoning_effort:
      input.credential.execution_policy.reasoning_effort ?? null,
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
    capability_fallback_count: attempt.capabilityFallbackCount ?? 0,
    structured_attempt_count: structuredAttempts,
    structured_validation_attempts: validationAttempts.slice(0, 2),
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
  const categories: string[] = [];
  let pathOverflow = false;
  let codeOverflow = false;
  for (const item of rawViolations) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const violation = item as Readonly<Record<string, unknown>>;
    const path = boundedViolationText(violation.path ?? violation.field_path, 512);
    const code = boundedViolationText(violation.code, 160);
    const category = roleViolationCategory(code, violation.actual);
    if (path && !paths.includes(path)) {
      if (paths.length < 32) paths.push(path);
      else pathOverflow = true;
    }
    if (code && !codes.includes(code)) {
      if (codes.length < 32) codes.push(code);
      else codeOverflow = true;
    }
    if (category && !categories.includes(category) && categories.length < 32) {
      categories.push(category);
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
    ...(categories.length > 0 ? { violation_categories: categories } : {}),
    repair_allowed: validation.result?.repair_allowed === true,
    truncated: Array.isArray(candidate) &&
      (candidate.length > 128 || pathOverflow || codeOverflow),
  };
}

function roleContractFailureCode(
  request: AgentRunRequest,
  validation: StructuredValidationResult,
): string | undefined {
  if (request.validation_profile !== "role_prompt_contract_v1") return undefined;
  const violations = validation.result?.violations;
  return Array.isArray(violations) && violations.some(
    (item) =>
      item &&
      typeof item === "object" &&
      !Array.isArray(item) &&
      (item as Readonly<Record<string, unknown>>).code ===
        "node_prompt_role_contract_invalid",
  )
    ? "node_prompt_role_contract_invalid"
    : undefined;
}

function roleViolationCategory(
  code: string | undefined,
  actual: unknown,
): string | undefined {
  if (code !== "node_prompt_role_contract_invalid" || typeof actual !== "string") {
    return undefined;
  }
  return [
    "cross_role_content",
    "narrative_progression",
    "positive_character",
    "positive_product",
    "positive_prop",
  ].includes(actual)
    ? actual
    : undefined;
}

function boundedViolations(
  result: Readonly<Record<string, unknown>> | undefined,
  maxViolations = 8,
) {
  const candidate = result?.violations;
  if (!Array.isArray(candidate)) return [];
  return candidate.slice(0, maxViolations).flatMap((item) => {
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
  if (isProviderBalanceFailure(error)) {
    return new AgentOperationFailure(
      "agent_provider_insufficient_balance",
      PROVIDER_INSUFFICIENT_BALANCE_MESSAGE,
      false,
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
  const stallDetected = isStallDetected(attemptMetadata);
  const retryable = manualRetryable ||
    (recoveryAllowed &&
      stage === "initial" &&
      (attemptMetadata?.response_activity_observed === false || stallDetected) &&
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
  const metadata: AgentTransportAttemptMetadataV1 = {
    provider: input.credential.provider,
    model_ref: input.credential.model_ref,
    structured_transport: input.credential.execution_policy.structured_transport,
    thinking_format: input.credential.execution_policy.thinking_format,
    reasoning_control: input.credential.execution_policy.reasoning_control,
    reasoning_mode: input.credential.execution_policy.reasoning_mode,
    reasoning_effort:
      input.credential.execution_policy.reasoning_effort ?? null,
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
    capability_fallback_count: stage === "capability_fallback" ? 1 : 0,
    structured_attempt_count: stage === "structured_repair" ? 2 : 1,
    ...(shape.safeExceptionClass
      ? { safe_exception_class: shape.safeExceptionClass }
      : {}),
    ...(shape.safeErrorCode ? { safe_error_code: shape.safeErrorCode } : {}),
    ...(shape.httpStatus ? { http_status: shape.httpStatus } : {}),
    ...(shape.providerTraceId ? { provider_trace_id: shape.providerTraceId } : {}),
    ...safeActivityTimes(error),
  };
  if (isStallDetected(error)) {
    Object.assign(metadata, { stall_detected: true });
  }
  return metadata;
}

function isStallDetected(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === "object" &&
      (error as { readonly stall_detected?: unknown }).stall_detected === true,
  );
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
