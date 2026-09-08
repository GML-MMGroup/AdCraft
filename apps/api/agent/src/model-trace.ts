import { createHash } from "node:crypto";

import {
  createAssistantMessageEventStream,
  type AssistantMessageEvent,
  type AssistantMessageEventStream,
} from "@earendil-works/pi-ai";

import type {
  AgentModelTraceRecordRequestV1,
  AgentModelTraceRequestIdentityV1,
  AgentModelTraceNonStreamingResponseV1,
  AgentModelTraceSafeFailureV1,
  AgentModelTraceStreamingChunkV1,
  AgentModelTraceStreamingResponseV1,
  AgentRunRequest,
} from "./generated/agent-runtime.js";
import { loadRuntimeManifest } from "./manifest.js";
import type {
  StructuredCompletionResponse,
} from "./pi-structured-transport.js";
import {
  isAcceptanceReplaySource,
  type AgentRuntimeTransportSource,
  type PythonInternalClient,
} from "./python-internal-client.js";
import type { ModelAttemptStage } from "./run-budget.js";
import type { LoadedSkill } from "./skills.js";

type AgentModelTraceResponseV1 =
  | AgentModelTraceNonStreamingResponseV1
  | AgentModelTraceStreamingResponseV1
  | AgentModelTraceSafeFailureV1;
type AgentModelTraceProviderRequest = object;

export type AgentModelTraceRecordClient = Pick<
  PythonInternalClient,
  "recordModelTraceAttempt"
>;
export type AgentModelTraceClaimClient = Pick<
  PythonInternalClient,
  "claimModelTraceAttempt"
>;
export type AgentModelTraceClient =
  | AgentModelTraceRecordClient
  | AgentModelTraceClaimClient
  | (AgentModelTraceRecordClient & AgentModelTraceClaimClient);

export interface AgentModelTraceContext {
  readonly credential: AgentRuntimeTransportSource;
  readonly request: AgentRunRequest;
  readonly systemPrompt: string;
  readonly userPrompt: string;
  readonly schema: Readonly<Record<string, unknown>>;
  readonly loadedSkills: ReadonlyArray<LoadedSkill>;
  readonly traceClient?: AgentModelTraceClient;
}

export async function recordAgentModelTraceOutcome(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
  response: StructuredCompletionResponse | unknown,
  succeeded: boolean,
): Promise<void> {
  if (
    isAcceptanceReplaySource(context.credential) ||
    context.credential.trace_mode !== "live_record"
  ) return;
  if (
    !context.credential.trace_session_id ||
    !context.traceClient ||
    !("recordModelTraceAttempt" in context.traceClient)
  ) {
    throw new Error("acceptance_model_trace_invalid");
  }
  const attemptOrdinal = attemptOrdinalForStage(stage);
  const request: AgentModelTraceRecordRequestV1 = {
    protocol_version: "1",
    session_id: context.credential.trace_session_id,
    attempt_id: `${context.request.run_id}:${stage}:${attemptOrdinal}`,
    recorded_agent_run_id: context.request.run_id,
    request_identity: traceRequestIdentity(
      context,
      providerRequest,
      stage,
      attemptOrdinal,
    ),
    response: succeeded
      ? normalizedTraceResponse(response as StructuredCompletionResponse)
      : normalizedTraceFailure(response),
  };
  await context.traceClient.recordModelTraceAttempt(request);
}

export async function claimAgentModelTraceOutcome(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
): Promise<StructuredCompletionResponse> {
  const response = await claimAgentModelTraceResponse(context, providerRequest, stage);
  return replayedCompletionResponse(response);
}

async function claimAgentModelTraceResponse(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
): Promise<AgentModelTraceResponseV1> {
  const source = context.credential;
  if (
    !isAcceptanceReplaySource(source) ||
    !context.traceClient ||
    !("claimModelTraceAttempt" in context.traceClient)
  ) {
    throw new Error("acceptance_model_replay_forbidden");
  }
  const attemptOrdinal = attemptOrdinalForStage(stage);
  const claimed = await context.traceClient.claimModelTraceAttempt({
    protocol_version: "1",
    session_id: source.trace_session_id,
    attempt_id: `${context.request.run_id}:${stage}:${attemptOrdinal}`,
    request_identity: traceRequestIdentity(
      context,
      providerRequest,
      stage,
      attemptOrdinal,
    ),
  });
  return claimed.response;
}

export function recordedAssistantMessageStream(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
  source: AssistantMessageEventStream,
): AssistantMessageEventStream {
  const output = createAssistantMessageEventStream();
  void recordThenReleaseAssistantEvents(
    context,
    providerRequest,
    stage,
    source,
    output,
  );
  return output;
}

async function recordThenReleaseAssistantEvents(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
  source: AssistantMessageEventStream,
  output: AssistantMessageEventStream,
): Promise<void> {
  const events: AssistantMessageEvent[] = [];
  try {
    for await (const event of source) events.push(event);
    const terminal = events.at(-1);
    if (terminal?.type !== "done") {
      throw new Error("acceptance_model_trace_invalid");
    }
    const chunks = normalizedAssistantToolCallChunks(events);
    await recordAgentModelTraceOutcome(
      context,
      providerRequest,
      stage,
      {
        choices: [{
          finish_reason: finishReasonForAssistantEvent(terminal.reason),
          message: { content: null },
        }],
        usage: {
          prompt_tokens: terminal.message.usage.input,
          completion_tokens: terminal.message.usage.output,
          total_tokens: terminal.message.usage.totalTokens,
          completion_tokens_details: {
            reasoning_tokens: terminal.message.usage.reasoning ?? 0,
          },
        },
        transport_metadata: {
          response_activity_observed: chunks.length > 1,
          first_content_at: null,
          last_activity_at: null,
          completed_at: new Date(0).toISOString(),
          response_bytes: new TextEncoder().encode(
            chunks.map((chunk) => chunk.tool_arguments_fragment ?? "").join(""),
          ).byteLength,
          finish_reason: finishReasonForAssistantEvent(terminal.reason),
          provider_trace_id: null,
          normalized_chunks: chunks,
        },
      },
      true,
    );
    for (const event of events) output.push(event);
  } catch (error) {
    if (!isAgentModelTraceFailure(error)) {
      try {
        await recordAgentModelTraceOutcome(
          context,
          providerRequest,
          stage,
          error,
          false,
        );
      } catch (captureError) {
        error = captureError;
      }
    }
    output.push(assistantErrorEvent(context, error));
  }
}

export function replayedAssistantMessageStream(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
): AssistantMessageEventStream {
  const output = createAssistantMessageEventStream();
  void claimThenReleaseAssistantEvents(context, providerRequest, stage, output);
  return output;
}

async function claimThenReleaseAssistantEvents(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
  output: AssistantMessageEventStream,
): Promise<void> {
  try {
    const response = await claimAgentModelTraceResponse(context, providerRequest, stage);
    if (response.response_kind !== "streaming") {
      throw new Error("acceptance_model_replay_mismatch");
    }
    for (const event of assistantEventsFromTrace(context, response)) output.push(event);
  } catch (error) {
    output.push(assistantErrorEvent(context, error));
  }
}

function normalizedAssistantToolCallChunks(
  events: ReadonlyArray<AssistantMessageEvent>,
): ReadonlyArray<AgentModelTraceStreamingChunkV1> {
  const chunks: AgentModelTraceStreamingChunkV1[] = [];
  for (const event of events) {
    if (event.type === "toolcall_start") {
      const toolCall = event.partial.content[event.contentIndex];
      if (!toolCall || toolCall.type !== "toolCall") {
        throw new Error("acceptance_model_trace_invalid");
      }
      chunks.push({
        sequence_no: chunks.length + 1,
        tool_call_index: 0,
        tool_call_id_fragment: toolCall.id,
        tool_name_fragment: toolCall.name,
      });
    } else if (event.type === "toolcall_delta" && event.delta.length > 0) {
      chunks.push({
        sequence_no: chunks.length + 1,
        tool_call_index: 0,
        tool_arguments_fragment: event.delta,
      });
    } else if (event.type === "done") {
      chunks.push({
        sequence_no: chunks.length + 1,
        finish_reason: finishReasonForAssistantEvent(event.reason),
      });
    }
  }
  if (chunks.length < 2 || chunks[0]?.tool_call_index !== 0) {
    throw new Error("acceptance_model_trace_invalid");
  }
  return chunks;
}

function assistantEventsFromTrace(
  context: AgentModelTraceContext,
  response: AgentModelTraceStreamingResponseV1,
): ReadonlyArray<AssistantMessageEvent> {
  let toolCallId = "";
  let toolName = "";
  let argumentsJson = "";
  const events: AssistantMessageEvent[] = [];
  const initial = assistantMessage(context, [], "toolUse", response);
  events.push({ type: "start", partial: initial });
  let started = false;
  for (const chunk of response.chunks) {
    if (chunk.tool_call_index === 0) {
      toolCallId += chunk.tool_call_id_fragment ?? "";
      toolName += chunk.tool_name_fragment ?? "";
      if (!started) {
        if (!toolCallId || !toolName) throw new Error("acceptance_model_replay_mismatch");
        started = true;
        events.push({
          type: "toolcall_start",
          contentIndex: 0,
          partial: assistantMessage(
            context,
            [{ type: "toolCall", id: toolCallId, name: toolName, arguments: {} }],
            "toolUse",
            response,
          ),
        });
      }
      const delta = chunk.tool_arguments_fragment ?? "";
      if (delta) {
        argumentsJson += delta;
        events.push({
          type: "toolcall_delta",
          contentIndex: 0,
          delta,
          partial: assistantMessage(
            context,
            [{
              type: "toolCall",
              id: toolCallId,
              name: toolName,
              arguments: partialJsonObject(argumentsJson),
            }],
            "toolUse",
            response,
          ),
        });
      }
    }
  }
  if (
    !started ||
    toolName !== "submit_structured_result" ||
    response.chunks.at(-1)?.finish_reason !== "tool_calls"
  ) {
    throw new Error("acceptance_model_replay_mismatch");
  }
  let argumentsValue: Readonly<Record<string, unknown>>;
  try {
    const parsed = JSON.parse(argumentsJson) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("invalid");
    }
    argumentsValue = parsed as Readonly<Record<string, unknown>>;
  } catch {
    throw new Error("acceptance_model_replay_mismatch");
  }
  const toolCall = {
    type: "toolCall" as const,
    id: toolCallId,
    name: toolName,
    arguments: argumentsValue,
  };
  const final = assistantMessage(context, [toolCall], "toolUse", response);
  events.push({ type: "toolcall_end", contentIndex: 0, toolCall, partial: final });
  events.push({ type: "done", reason: "toolUse", message: final });
  return events;
}

function assistantMessage(
  context: AgentModelTraceContext,
  content: ReadonlyArray<Readonly<Record<string, unknown>>>,
  stopReason: "toolUse",
  response: AgentModelTraceStreamingResponseV1,
) {
  return {
    role: "assistant" as const,
    content,
    api: "openai-completions" as const,
    provider: context.credential.provider,
    model: context.credential.model_id,
    usage: {
      input: response.prompt_tokens ?? 0,
      output: response.completion_tokens ?? 0,
      cacheRead: 0,
      cacheWrite: 0,
      reasoning: response.reasoning_tokens ?? 0,
      totalTokens: (response.prompt_tokens ?? 0) + (response.completion_tokens ?? 0),
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason,
    timestamp: 0,
  } as never;
}

function partialJsonObject(value: string): Readonly<Record<string, unknown>> {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Readonly<Record<string, unknown>>
      : {};
  } catch {
    return {};
  }
}

function finishReasonForAssistantEvent(reason: "stop" | "length" | "toolUse"): string {
  return reason === "toolUse" ? "tool_calls" : reason;
}

function assistantErrorEvent(
  context: AgentModelTraceContext,
  error: unknown,
): AssistantMessageEvent {
  const message = error instanceof Error ? error.message : "acceptance_model_trace_invalid";
  return {
    type: "error",
    reason: "error",
    error: {
      role: "assistant",
      content: [],
      api: "openai-completions",
      provider: context.credential.provider,
      model: context.credential.model_id,
      usage: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
      },
      stopReason: "error",
      errorMessage: message,
      timestamp: 0,
    },
  };
}

export function traceRequestIdentity(
  context: AgentModelTraceContext,
  providerRequest: AgentModelTraceProviderRequest,
  stage: ModelAttemptStage,
  attemptOrdinal = attemptOrdinalForStage(stage),
): AgentModelTraceRequestIdentityV1 {
  const credential = context.credential;
  if (
    !credential.adapter_id ||
    !credential.transport_kind ||
    !credential.capability_revision ||
    !credential.adapter_revision
  ) {
    throw new Error("acceptance_model_trace_invalid");
  }
  const logicalInput = {
    operation: context.request.operation,
    contract_name: context.request.contract_name ?? "SpecialistDraft",
    system_prompt: context.systemPrompt,
    user_prompt: context.userPrompt,
    schema: context.schema,
  };
  return {
    logical_invocation_key: `${context.request.operation}:${sha256(logicalInput).slice(7)}`,
    operation: context.request.operation,
    attempt_stage: stage,
    attempt_ordinal: attemptOrdinal,
    provider: credential.provider,
    model_ref: credential.model_ref,
    model_id: credential.model_id,
    structured_transport:
      credential.execution_policy.structured_transport === "json_object"
        ? "non_streaming_json_object"
        : credential.execution_policy.structured_transport,
    operation_policy_id:
      context.request.policy?.operation_policy_id ?? credential.model_policy_id,
    request_digest: sha256(providerRequest),
    contract_digest: digestValue(context.request.contract_digest),
    runtime_digest: sha256(loadRuntimeManifest()),
    prompt_digest: sha256({
      system_prompt: context.systemPrompt,
      user_prompt: context.userPrompt,
    }),
    schema_digest: sha256(context.schema),
    skill_digest: sha256(
      context.loadedSkills.map((skill) => ({
        skill_id: skill.skill_id,
        version: skill.version,
        sha256: skill.sha256,
      })),
    ),
    policy_digest: sha256(credential.execution_policy),
    supports_tool_calls: credential.supports_tool_calls,
    supports_strict_structured_output: credential.supports_strict_structured_output,
    supports_streaming: credential.supports_streaming,
    supports_streamed_tool_calls: credential.supports_streamed_tool_calls,
    supports_reasoning_controls: credential.supports_reasoning_controls,
    adapter_id: credential.adapter_id,
    transport_kind: credential.transport_kind,
    capability_revision: credential.capability_revision,
    adapter_revision: credential.adapter_revision,
    gateway_id: credential.gateway_id ?? null,
    model_alias: credential.model_alias ?? null,
    projection_digest: credential.projection_digest ?? null,
    openrouter_routing: credential.openrouter_routing ?? null,
    execution_policy: credential.execution_policy,
  };
}

export function normalizedTraceResponse(
  response: StructuredCompletionResponse,
): AgentModelTraceResponseV1 {
  if (response.transport_metadata?.normalized_chunks) {
    return {
      response_kind: "streaming",
      chunks: response.transport_metadata.normalized_chunks,
      prompt_tokens: response.usage?.prompt_tokens ?? null,
      completion_tokens: response.usage?.completion_tokens ?? null,
      reasoning_tokens:
        response.usage?.completion_tokens_details?.reasoning_tokens ?? null,
    };
  }
  const choice = response.choices?.[0];
  const toolCalls = choice?.message?.tool_calls ?? [];
  return {
    response_kind: "non_streaming",
    response_id: response.id ?? null,
    finish_reason: choice?.finish_reason ?? null,
    content: choice?.message?.content ?? null,
    tool_calls: toolCalls.map((toolCall) => ({
      tool_call_id: toolCall.id ?? "call_primary",
      tool_name: "submit_structured_result",
      arguments_json: toolCall.function?.arguments ?? "{}",
    })),
    prompt_tokens: response.usage?.prompt_tokens ?? null,
    completion_tokens: response.usage?.completion_tokens ?? null,
    reasoning_tokens:
      response.usage?.completion_tokens_details?.reasoning_tokens ?? null,
  };
}

function replayedCompletionResponse(
  response: AgentModelTraceResponseV1,
): StructuredCompletionResponse {
  if (response.response_kind === "transport_failure") {
    throw Object.assign(new Error(response.error_code), {
      code: response.error_code,
      status: response.http_status ?? undefined,
      response_started: response.response_started,
    });
  }
  if (response.response_kind === "streaming") {
    const content = response.chunks.map((chunk) => chunk.content ?? "").join("");
    const finishReason = response.chunks.at(-1)?.finish_reason ?? null;
    return {
      choices: [{ finish_reason: finishReason, message: { content } }],
      usage: traceUsage(response),
      transport_metadata: {
        response_activity_observed: content.length > 0,
        first_content_at: null,
        last_activity_at: null,
        completed_at: new Date(0).toISOString(),
        response_bytes: new TextEncoder().encode(content).byteLength,
        finish_reason: finishReason,
        provider_trace_id: null,
        normalized_chunks: response.chunks,
      },
    };
  }
  const nonStreaming = response as AgentModelTraceNonStreamingResponseV1;
  return {
    id: nonStreaming.response_id ?? null,
    choices: [
      {
        finish_reason: nonStreaming.finish_reason ?? null,
        message: {
          content: nonStreaming.content ?? null,
          tool_calls: (nonStreaming.tool_calls ?? []).map((toolCall) => ({
            id: toolCall.tool_call_id,
            type: "function",
            function: {
              name: toolCall.tool_name ?? "submit_structured_result",
              arguments: toolCall.arguments_json,
            },
          })),
        },
      },
    ],
    usage: traceUsage(nonStreaming),
  };
}

function traceUsage(
  response: AgentModelTraceNonStreamingResponseV1 | AgentModelTraceStreamingResponseV1,
): Exclude<StructuredCompletionResponse["usage"], undefined> {
  if (
    response.prompt_tokens === null &&
    response.completion_tokens === null &&
    response.reasoning_tokens === null
  ) return null;
  return {
    prompt_tokens: response.prompt_tokens ?? 0,
    completion_tokens: response.completion_tokens ?? 0,
    total_tokens: (response.prompt_tokens ?? 0) + (response.completion_tokens ?? 0),
    completion_tokens_details: {
      reasoning_tokens: response.reasoning_tokens ?? 0,
    },
  };
}

function normalizedTraceFailure(error: unknown): AgentModelTraceResponseV1 {
  const value = error && typeof error === "object"
    ? error as Record<string, unknown>
    : {};
  const response = value.response && typeof value.response === "object"
    ? value.response as Record<string, unknown>
    : {};
  const code = typeof value.code === "string"
    ? value.code
    : "agent_provider_transport_failed";
  const name = typeof value.name === "string" ? value.name : null;
  const status = typeof value.status === "number"
    ? value.status
    : typeof response.status === "number"
      ? response.status
      : null;
  return {
    response_kind: "transport_failure",
    error_code: code.slice(0, 120),
    exception_class: name?.slice(0, 160) ?? null,
    http_status: status,
    response_started: value.response_started === true,
  };
}

export function isAgentModelTraceFailure(error: unknown): boolean {
  return error instanceof Error && error.message.startsWith("acceptance_model_");
}

function attemptOrdinalForStage(stage: ModelAttemptStage): number {
  return stage === "initial" ? 1 : 2;
}

function digestValue(value: string): string {
  return /^sha256:[a-f0-9]{64}$/.test(value) ? value : `sha256:${value}`;
}

function sha256(value: unknown): string {
  const canonical = canonicalJsonValue(value);
  return `sha256:${createHash("sha256").update(JSON.stringify(canonical), "utf8").digest("hex")}`;
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
