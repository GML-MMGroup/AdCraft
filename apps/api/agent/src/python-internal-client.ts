import type {
  AgentModelExecutionPolicyV1,
  AgentRunRequest,
  AgentToolCall,
  AgentToolResult,
} from "./generated/agent-runtime.js";

export interface AgentCredentialSnapshot {
  readonly protocol_version: "1";
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
  readonly execution_policy: AgentModelExecutionPolicyV1;
  readonly api_key: string;
}

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
      typeof payload.base_url !== "string" ||
      typeof payload.api_key !== "string" ||
      typeof payload.provider !== "string" ||
      typeof payload.supports_tool_calls !== "boolean" ||
      typeof payload.supports_strict_structured_output !== "boolean" ||
      typeof payload.supports_streaming !== "boolean" ||
      typeof payload.supports_streamed_tool_calls !== "boolean" ||
      typeof payload.supports_reasoning_controls !== "boolean" ||
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
    return payload as unknown as AgentCredentialSnapshot;
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

const OPERATION_CLASSES = new Set([
  "routing",
  "proposal",
  "materialization",
  "long_form",
]);
const THINKING_FORMATS = new Set(["zai", "qwen", "none"]);
const REASONING_CONTROLS = new Set([
  "provider_default",
  "enable_thinking",
  "reasoning_effort",
  "none",
]);
const STRUCTURED_TRANSPORTS = new Set([
  "streamed_tool_call",
  "non_streaming_tool_call",
  "non_streaming_json_object",
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
    !isBoundedAttempt(policy.structured_repair_limit)
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
    (policy.reasoning_mode === "low" &&
      (policy.enable_thinking || policy.thinking_budget_tokens !== null)) ||
    (policy.reasoning_mode === "deep" &&
      (!policy.enable_thinking || policy.thinking_budget_tokens === null))
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
