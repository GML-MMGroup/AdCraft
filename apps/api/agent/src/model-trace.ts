import { createHash } from "node:crypto";

import type {
  AgentModelTraceRecordRequestV1,
  AgentModelTraceRequestIdentityV1,
  AgentModelTraceNonStreamingResponseV1,
  AgentModelTraceSafeFailureV1,
  AgentModelTraceStreamingResponseV1,
  AgentRunRequest,
} from "./generated/agent-runtime.js";
import { loadRuntimeManifest } from "./manifest.js";
import type {
  StructuredCompletionRequest,
  StructuredCompletionResponse,
} from "./pi-structured-transport.js";
import type {
  AgentCredentialSnapshot,
  PythonInternalClient,
} from "./python-internal-client.js";
import type { ModelAttemptStage } from "./run-budget.js";
import type { LoadedSkill } from "./skills.js";

type AgentModelTraceResponseV1 =
  | AgentModelTraceNonStreamingResponseV1
  | AgentModelTraceStreamingResponseV1
  | AgentModelTraceSafeFailureV1;

export type AgentModelTraceRecordClient = Pick<
  PythonInternalClient,
  "recordModelTraceAttempt"
>;

export interface AgentModelTraceContext {
  readonly credential: AgentCredentialSnapshot;
  readonly request: AgentRunRequest;
  readonly systemPrompt: string;
  readonly userPrompt: string;
  readonly schema: Readonly<Record<string, unknown>>;
  readonly loadedSkills: ReadonlyArray<LoadedSkill>;
  readonly traceClient?: AgentModelTraceRecordClient;
}

export async function recordAgentModelTraceOutcome(
  context: AgentModelTraceContext,
  providerRequest: StructuredCompletionRequest,
  stage: ModelAttemptStage,
  response: StructuredCompletionResponse | unknown,
  succeeded: boolean,
): Promise<void> {
  if (context.credential.trace_mode !== "live_record") return;
  if (!context.credential.trace_session_id || !context.traceClient) {
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

export function traceRequestIdentity(
  context: AgentModelTraceContext,
  providerRequest: StructuredCompletionRequest,
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
