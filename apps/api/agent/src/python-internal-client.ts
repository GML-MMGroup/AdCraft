import type {
  AgentModelTraceClaimRequestV1,
  AgentModelTraceClaimResponseV1,
  AgentModelTraceRecordRequestV1,
  AgentModelTraceRecordReceiptV1,
  AgentModelExecutionPolicyV1,
  AgentRuntimeAcceptanceReplaySourceV1,
  AgentRunRequest,
  AgentToolCall,
  AgentToolResult,
  OpenRouterRoutingPolicyV1,
} from "./generated/agent-runtime.js";

export interface AgentCredentialSnapshot {
  readonly protocol_version: "1";
  readonly source_kind?: "provider";
  readonly provider: string;
  readonly model_ref: string;
  readonly model_id: string;
  readonly model_policy_id: string;
  readonly base_url: string;
  readonly supports_tool_calls: boolean;
  readonly supports_strict_structured_output: boolean;
  readonly supports_streaming: boolean;
  readonly supports_streamed_tool_calls: boolean;
  readonly supports_reasoning_controls: boolean;
  readonly adapter_id?: string;
  readonly transport_kind?: "pi_native_openai_compatible" | "litellm_chat";
  readonly capability_revision?: string;
  readonly adapter_revision?: string;
  readonly gateway_id?: string | null;
  readonly model_alias?: string | null;
  readonly projection_digest?: string | null;
  readonly openrouter_routing?: OpenRouterRoutingPolicyV1 | null;
  readonly execution_policy: AgentModelExecutionPolicyV1;
  readonly api_key: string;
  readonly trace_mode?: "disabled" | "live_record";
  readonly trace_session_id?: string | null;
}
export type AgentRuntimeTransportSource =
  | AgentCredentialSnapshot
  | AgentRuntimeAcceptanceReplaySourceV1;

interface PythonInternalClientOptions {
  readonly baseUrl: string;
  readonly internalToken: string;
  readonly fetchImpl?: typeof fetch;
}

export class PythonInternalClient {
  readonly #baseUrl: string;
  readonly #internalToken: string;
  readonly #fetch: typeof fetch;

  constructor(options: PythonInternalClientOptions) {
    this.#baseUrl = options.baseUrl.replace(/\/$/, "");
    this.#internalToken = options.internalToken;
    this.#fetch = options.fetchImpl ?? fetch;
  }

  async credential(
    credentialRef: string,
    runId: string,
    agentName: AgentRunRequest["agent_name"],
    operation: string,
    modelPolicyId: string,
    modelRef: string,
  ): Promise<AgentCredentialSnapshot> {
    const source = await this.runtimeSource(
      credentialRef,
      runId,
      agentName,
      operation,
      modelPolicyId,
      modelRef,
    );
    if (source.source_kind !== "provider") {
      throw new Error("agent_protocol_mismatch");
    }
    return source;
  }

  async runtimeSource(
    credentialRef: string,
    runId: string,
    agentName: AgentRunRequest["agent_name"],
    operation: string,
    modelPolicyId: string,
    modelRef: string,
  ): Promise<AgentRuntimeTransportSource> {
    const query = new URLSearchParams({
      run_id: runId,
      agent_name: agentName,
      operation,
      model_policy_id: modelPolicyId,
      model_ref: modelRef,
    });
    const response = await this.#fetch(
      `${this.#baseUrl}/internal/v1/agent-runtime-config/${encodeURIComponent(credentialRef)}?${query.toString()}`,
      {
        headers: {
          authorization: `Bearer ${this.#internalToken}`,
          "cache-control": "no-store",
        },
        signal: AbortSignal.timeout(5_000),
      },
    );
    const payload = await boundedJson(response);
    if (
      payload.protocol_version !== "1" ||
      typeof payload.model_ref !== "string" ||
      typeof payload.model_id !== "string" ||
      typeof payload.model_policy_id !== "string" ||
      typeof payload.provider !== "string" ||
      typeof payload.supports_tool_calls !== "boolean" ||
      typeof payload.supports_strict_structured_output !== "boolean" ||
      typeof payload.supports_streaming !== "boolean" ||
      typeof payload.supports_streamed_tool_calls !== "boolean" ||
      typeof payload.supports_reasoning_controls !== "boolean" ||
      !isTransportIdentity(payload) ||
      !isOpenRouterRouting(payload) ||
      !isExecutionPolicy(
        payload.execution_policy,
        operation,
        modelRef,
        payload.supports_tool_calls,
        payload.supports_streamed_tool_calls,
      )
    ) {
      throw new Error("agent_protocol_mismatch");
    }
    if (payload.source_kind === "provider") {
      if (
        typeof payload.base_url !== "string" ||
        typeof payload.api_key !== "string" ||
        (payload.trace_mode !== "disabled" && payload.trace_mode !== "live_record") ||
        ((payload.trace_mode === "live_record") !==
          (typeof payload.trace_session_id === "string"))
      ) {
        throw new Error("agent_protocol_mismatch");
      }
      return payload as unknown as AgentCredentialSnapshot;
    }
    if (
      payload.source_kind !== "acceptance_replay" ||
      typeof payload.trace_session_id !== "string" ||
      !isDigest(payload.expected_bundle_digest) ||
      "base_url" in payload ||
      "api_key" in payload
    ) {
      throw new Error("agent_protocol_mismatch");
    }
    return payload as unknown as AgentRuntimeAcceptanceReplaySourceV1;
  }

  async recordModelTraceAttempt(
    request: AgentModelTraceRecordRequestV1,
  ): Promise<AgentModelTraceRecordReceiptV1> {
    const payload = await this.#postTraceRequest(
      request.session_id,
      "record",
      request,
    );
    if (!isTraceReceipt(payload, request.session_id, request.attempt_id)) {
      throw new Error("agent_protocol_mismatch");
    }
    return payload as unknown as AgentModelTraceRecordReceiptV1;
  }

  async claimModelTraceAttempt(
    request: AgentModelTraceClaimRequestV1,
  ): Promise<AgentModelTraceClaimResponseV1> {
    const payload = await this.#postTraceRequest(
      request.session_id,
      "claim",
      request,
    );
    if (
      !isTraceReceipt(payload, request.session_id, request.attempt_id) ||
      !isTraceResponse(payload.response)
    ) {
      throw new Error("agent_protocol_mismatch");
    }
    return payload as unknown as AgentModelTraceClaimResponseV1;
  }

  async #postTraceRequest(
    sessionId: string,
    action: "record" | "claim",
    body: AgentModelTraceRecordRequestV1 | AgentModelTraceClaimRequestV1,
  ): Promise<Record<string, unknown>> {
    const response = await this.#fetch(
      `${this.#baseUrl}/internal/v1/agent-model-traces/${encodeURIComponent(sessionId)}/${action}`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${this.#internalToken}`,
          "cache-control": "no-store",
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(5_000),
      },
    );
    return boundedJson(response);
  }

  async executeTool(call: AgentToolCall): Promise<AgentToolResult> {
    const response = await this.#fetch(`${this.#baseUrl}/internal/v1/agent-tools/execute`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.#internalToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(call),
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await boundedJson(response);
    if (
      payload.protocol_version !== "1" ||
      payload.run_id !== call.run_id ||
      payload.tool_call_id !== call.tool_call_id ||
      typeof payload.status !== "string"
    ) {
      throw new Error("agent_protocol_mismatch");
    }
    return payload as unknown as AgentToolResult;
  }
}

function isTraceReceipt(
  payload: Record<string, unknown>,
  sessionId: string,
  attemptId: string,
): boolean {
  return payload.protocol_version === "1" &&
    payload.session_id === sessionId &&
    payload.attempt_id === attemptId &&
    isPositiveInteger(payload.sequence_no) &&
    isDigest(payload.entry_digest) &&
    typeof payload.replayed === "boolean";
}

function isTraceResponse(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const response = value as Record<string, unknown>;
  if (response.response_kind === "transport_failure") {
    return typeof response.error_code === "string" &&
      typeof response.response_started === "boolean";
  }
  if (response.response_kind === "non_streaming") {
    return (response.content === null || typeof response.content === "string") &&
      Array.isArray(response.tool_calls);
  }
  if (response.response_kind === "streaming") {
    return Array.isArray(response.chunks) &&
      response.chunks.every(
        (chunk) =>
          !!chunk &&
          typeof chunk === "object" &&
          !Array.isArray(chunk) &&
          isPositiveInteger((chunk as Record<string, unknown>).sequence_no),
      );
  }
  return false;
}

function isDigest(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[a-f0-9]{64}$/.test(value);
}

function isOpenRouterRouting(payload: Record<string, unknown>): boolean {
  const routing = payload.openrouter_routing;
  if (!String(payload.model_ref).startsWith("openrouter:")) {
    return routing === null || routing === undefined;
  }
  if (!routing || typeof routing !== "object" || Array.isArray(routing)) return false;
  const value = routing as Record<string, unknown>;
  return value.routing_policy_id === "openrouter-openai-only-v1" &&
    typeof value.routing_policy_digest === "string" &&
    /^sha256:[a-f0-9]{64}$/.test(value.routing_policy_digest) &&
    Array.isArray(value.provider_only) &&
    value.provider_only.length === 1 &&
    value.provider_only[0] === "openai" &&
    value.require_parameters === true &&
    value.allow_fallbacks === false;
}

function isTransportIdentity(payload: Record<string, unknown>): boolean {
  if (
    payload.transport_kind === undefined &&
    payload.adapter_id === undefined &&
    payload.capability_revision === undefined &&
    payload.adapter_revision === undefined
  ) {
    return true;
  }
  if (
    typeof payload.adapter_id !== "string" ||
    typeof payload.capability_revision !== "string" ||
    typeof payload.adapter_revision !== "string" ||
    (payload.transport_kind !== "pi_native_openai_compatible" &&
      payload.transport_kind !== "litellm_chat")
  ) {
    return false;
  }
  if (payload.transport_kind === "litellm_chat") {
    return (
      typeof payload.gateway_id === "string" &&
      typeof payload.model_alias === "string" &&
      typeof payload.projection_digest === "string" &&
      /^sha256:[a-f0-9]{64}$/.test(payload.projection_digest)
    );
  }
  return (
    (payload.gateway_id === null || payload.gateway_id === undefined) &&
    (payload.model_alias === null || payload.model_alias === undefined) &&
    (payload.projection_digest === null || payload.projection_digest === undefined)
  );
}

const OPERATION_CLASSES = new Set([
  "routing",
  "proposal",
  "materialization",
  "long_form",
]);
const THINKING_FORMATS = new Set(["zai", "qwen", "openai", "none"]);
const REASONING_CONTROLS = new Set([
  "provider_default",
  "enable_thinking",
  "reasoning_effort",
  "none",
]);
const REASONING_EFFORTS = new Set(["minimal", "low", "medium", "high"]);
const STRUCTURED_TRANSPORTS = new Set([
  "streamed_tool_call",
  "non_streaming_tool_call",
  "non_streaming_json_object",
  "non_streaming_json_schema",
  "streaming_json_object",
  "json_object",
]);

function isExecutionPolicy(
  value: unknown,
  operation: string,
  modelRef: string,
  supportsToolCalls: unknown,
  supportsStreamedToolCalls: unknown,
): value is AgentModelExecutionPolicyV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const policy = value as Record<string, unknown>;
  if (
    policy.model_ref !== modelRef ||
    policy.operation !== operation ||
    typeof policy.operation_class !== "string" ||
    !OPERATION_CLASSES.has(policy.operation_class) ||
    typeof policy.thinking_format !== "string" ||
    !THINKING_FORMATS.has(policy.thinking_format) ||
    typeof policy.reasoning_control !== "string" ||
    !REASONING_CONTROLS.has(policy.reasoning_control) ||
    (policy.reasoning_mode !== "low" && policy.reasoning_mode !== "deep") ||
    !isReasoningEffort(policy.reasoning_effort) ||
    typeof policy.enable_thinking !== "boolean" ||
    !isThinkingBudget(policy.thinking_budget_tokens) ||
    typeof policy.structured_transport !== "string" ||
    !STRUCTURED_TRANSPORTS.has(policy.structured_transport) ||
    policy.supports_tool_calls !== supportsToolCalls ||
    policy.supports_streamed_tool_calls !== supportsStreamedToolCalls ||
    !isPositiveInteger(policy.deadline_seconds) ||
    !isPositiveInteger(policy.primary_timeout_seconds) ||
    !isNonNegativeInteger(policy.recovery_timeout_seconds) ||
    !isPositiveInteger(policy.persistence_reserve_seconds) ||
    policy.primary_timeout_seconds +
        policy.recovery_timeout_seconds +
        policy.persistence_reserve_seconds !==
      policy.deadline_seconds ||
    (policy.max_model_submissions !== 1 && policy.max_model_submissions !== 2) ||
    (policy.recovery_mode !== "none" &&
      policy.recovery_mode !== "structured_repair_only" &&
      policy.recovery_mode !== "transport_retry_or_structured_repair") ||
    !isPositiveInteger(policy.max_output_tokens) ||
    !isBoundedAttempt(policy.transport_retry_limit) ||
    !isBoundedAttempt(policy.structured_repair_limit) ||
    (policy.json_object_fallback_certified !== undefined &&
      typeof policy.json_object_fallback_certified !== "boolean")
  ) {
    return false;
  }
  if (
    (policy.max_model_submissions === 1 &&
      (policy.recovery_mode !== "none" ||
        policy.recovery_timeout_seconds !== 0 ||
        policy.transport_retry_limit !== 0 ||
        policy.structured_repair_limit !== 0)) ||
    (policy.max_model_submissions === 2 &&
      (policy.recovery_mode === "none" || policy.recovery_timeout_seconds < 1)) ||
    (policy.recovery_mode === "structured_repair_only" &&
      (policy.transport_retry_limit !== 0 || policy.structured_repair_limit !== 1))
  ) {
    return false;
  }
  if (
    (policy.reasoning_control === "enable_thinking" &&
      ((policy.reasoning_mode === "low" &&
        (policy.enable_thinking || policy.thinking_budget_tokens !== null)) ||
        (policy.reasoning_mode === "deep" &&
          (!policy.enable_thinking || policy.thinking_budget_tokens === null)))) ||
    (policy.reasoning_control !== "enable_thinking" &&
      (policy.enable_thinking || policy.thinking_budget_tokens !== null))
  ) {
    return false;
  }
  if (
    (policy.reasoning_control === "reasoning_effort" &&
      (policy.reasoning_effort == null ||
        policy.enable_thinking ||
        policy.thinking_budget_tokens !== null)) ||
    (policy.reasoning_control !== "reasoning_effort" &&
      policy.reasoning_effort != null)
  ) {
    return false;
  }
  if (
    policy.json_object_fallback_certified === true &&
    (!modelRef.startsWith("openrouter:") ||
      policy.structured_transport !== "non_streaming_json_schema" ||
      policy.max_model_submissions !== 2)
  ) {
    return false;
  }
  if (
    policy.structured_transport === "streamed_tool_call" &&
    policy.supports_streamed_tool_calls !== true
  ) {
    return false;
  }
  if (
    policy.structured_transport === "non_streaming_tool_call" &&
    policy.supports_tool_calls !== true
  ) {
    return false;
  }
  return true;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isBoundedAttempt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 1;
}

function isThinkingBudget(value: unknown): value is number | null {
  return value === null || isPositiveInteger(value);
}

function isReasoningEffort(
  value: unknown,
): value is "minimal" | "low" | "medium" | "high" | null | undefined {
  return value == null || (typeof value === "string" && REASONING_EFFORTS.has(value));
}

async function boundedJson(response: Response): Promise<Record<string, unknown>> {
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > 65_536) throw new Error("agent_protocol_mismatch");
  const payload: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("agent_protocol_mismatch");
  }
  if (!response.ok) {
    const detail = (payload as Record<string, unknown>).detail;
    if (
      detail &&
      typeof detail === "object" &&
      !Array.isArray(detail) &&
      typeof (detail as Record<string, unknown>).code === "string"
    ) {
      throw new Error((detail as Record<string, string>).code);
    }
    throw new Error(`agent_internal_request_failed:${response.status}`);
  }
  return payload as Record<string, unknown>;
}
