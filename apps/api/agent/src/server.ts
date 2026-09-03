import { timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import type {
  AgentRunRequest,
  AgentRuntimeEvent,
} from "./generated/agent-runtime.js";
import {
  event,
  FakeAgentModelAdapter,
  type AgentModelAdapter,
} from "./runtime.js";
import { EventBuffer, EventBufferOverflow } from "./event-buffer.js";
import { loadRuntimeManifest } from "./manifest.js";
import { validateAgentRunRequest } from "./protocol-validator.js";
import {
  operationDeadlineSeconds,
  RunBudget,
  RunBudgetFailure,
} from "./run-budget.js";
import { AgentOperationFailure } from "./operation-recovery.js";
import { AgentPromptInputProjectionError } from "./prompt-input-projection.js";

interface ServerOptions {
  readonly internalToken: string;
  readonly mode: "real" | "fake";
  readonly adapter?: AgentModelAdapter;
  readonly maxRequestBytes?: number;
  readonly maxQueueBytes?: number;
  readonly maxConcurrentRuns?: number;
  readonly heartbeatIntervalMs?: number;
}

interface ActiveRun {
  readonly controller: AbortController;
  abortCause?: AbortCause;
}

type AbortCause =
  | "deadline"
  | "explicit_cancel"
  | "server_shutdown"
  | "client_transport_lost";

type FailureAudit = AgentOperationFailure["attemptMetadata"];

type TerminalFailureAudit = Readonly<Record<string, unknown>>;

interface ProjectionFailureAudit {
  readonly context_contract_name: string;
  readonly projection_id?: string;
}

const terminalEvents = new Set(["run_completed", "run_failed", "run_cancelled"]);
const safeAdapterErrorCodes = new Set([
  "agent_model_incompatible",
  "agent_model_capability_mismatch",
  "agent_model_policy_mismatch",
  "agent_model_unavailable",
  "agent_operation_not_allowed",
  "agent_structured_output_invalid",
  "agent_contract_validation_failed",
  "agent_provider_timeout",
  "agent_provider_transport_failed",
  "agent_run_budget_exceeded",
  "agent_tool_not_allowed",
  "agent_target_revision_conflict",
  "provider_credentials_invalid",
  "provider_credentials_missing",
]);
const preSubmissionFailureCodes = new Set([
  "agent_context_input_missing",
  "agent_model_capability_mismatch",
  "agent_model_incompatible",
  "agent_model_policy_mismatch",
  "agent_model_unavailable",
  "agent_operation_not_allowed",
  "agent_prompt_input_registry_invalid",
  "provider_credentials_invalid",
  "provider_credentials_missing",
]);
const structuredFailureCodes = new Set([
  "agent_contract_validation_failed",
  "agent_structured_output_invalid",
]);
const providerFailureCodes = new Set([
  "agent_provider_timeout",
  "agent_provider_transport_failed",
]);
const safeFailureMessages: Readonly<Record<string, string>> = {
  agent_contract_validation_failed: "Agent contract validation failed.",
  agent_context_input_missing: "Agent Prompt input is incomplete.",
  agent_deadline_exceeded: "Agent run deadline exceeded.",
  agent_model_capability_mismatch: "Agent model capability does not satisfy this operation.",
  agent_model_incompatible: "Agent model is incompatible with this operation.",
  agent_model_policy_mismatch: "Agent model policy rejected this operation.",
  agent_model_unavailable: "Agent model is unavailable.",
  agent_operation_not_allowed: "Agent operation is not allowed.",
  agent_prompt_input_registry_invalid: "Agent Prompt input registry is invalid.",
  agent_provider_timeout: "Agent provider request timed out.",
  agent_provider_transport_failed: "Agent provider transport failed.",
  agent_run_budget_exceeded: "Agent runtime policy rejected the operation.",
  agent_stream_backpressure_exceeded: "Agent runtime stream exceeded its byte budget.",
  agent_structured_output_invalid: "Agent structured output was invalid.",
  agent_target_revision_conflict: "Agent target revision changed.",
  agent_tool_not_allowed: "Agent tool is not allowed.",
  provider_credentials_invalid: "Agent provider credentials are invalid.",
  provider_credentials_missing: "Agent provider credentials are unavailable.",
};

export function createAgentRuntimeServer(options: ServerOptions) {
  const adapter = options.adapter ?? new FakeAgentModelAdapter();
  const maxRequestBytes = options.maxRequestBytes ?? 1_048_576;
  const maxQueueBytes = options.maxQueueBytes ?? 262_144;
  const maxConcurrentRuns = options.maxConcurrentRuns ?? 2;
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? 15_000;
  const activeRuns = new Map<string, ActiveRun>();
  const activeConversations = new Map<string, string>();

  const server = createServer(async (incoming, response) => {
    if (!authorized(incoming, options.internalToken)) {
      json(response, 401, { code: "agent_internal_auth_failed" });
      return;
    }
    const url = new URL(incoming.url ?? "/", "http://agent-runtime.local");
    if (incoming.method === "GET" && url.pathname === "/internal/v1/health") {
      json(response, 200, {
        ...loadRuntimeManifest(),
        status: "ready",
        mode: options.mode,
        pi_version: "0.81.1",
        active_runs: activeRuns.size,
      });
      return;
    }
    if (incoming.method === "POST" && url.pathname === "/internal/v1/agent-runs") {
      await handleRun(
        incoming,
        response,
        adapter,
        activeRuns,
        activeConversations,
        maxRequestBytes,
        maxQueueBytes,
        heartbeatIntervalMs,
        maxConcurrentRuns,
      );
      return;
    }
    const cancellationMatch = url.pathname.match(
      /^\/internal\/v1\/agent-runs\/([^/]+)\/cancel$/,
    );
    if (incoming.method === "POST" && cancellationMatch) {
      const runId = decodeURIComponent(cancellationMatch[1] ?? "");
      const active = activeRuns.get(runId);
      if (active && !active.abortCause) {
        active.abortCause = "explicit_cancel";
        active.controller.abort();
      }
      json(response, 200, {
        protocol_version: "1",
        run_id: runId,
        status: active ? "cancelling" : "not_active",
      });
      return;
    }
    json(response, 404, { code: "agent_internal_route_not_found" });
  });
  server.on("close", () => {
    for (const active of activeRuns.values()) {
      if (!active.abortCause) active.abortCause = "server_shutdown";
      active.controller.abort();
    }
  });
  return server;
}

async function handleRun(
  incoming: IncomingMessage,
  response: ServerResponse,
  adapter: AgentModelAdapter,
  activeRuns: Map<string, ActiveRun>,
  activeConversations: Map<string, string>,
  maxRequestBytes: number,
  maxQueueBytes: number,
  heartbeatIntervalMs: number,
  maxConcurrentRuns: number,
): Promise<void> {
  let request: AgentRunRequest;
  try {
    request = validateAgentRunRequest(await readJson(incoming, maxRequestBytes));
  } catch (error) {
    const code =
      error instanceof Error && error.message === "agent_context_registry_invalid"
        ? error.message
        : "agent_protocol_mismatch";
    json(response, 422, { code });
    return;
  }
  if (activeRuns.has(request.run_id)) {
    json(response, 409, { code: "agent_run_already_active" });
    return;
  }
  const conversationId =
    "conversation_id" in request.context
      ? request.context.conversation_id
      : undefined;
  if (conversationId && activeConversations.has(conversationId)) {
    json(response, 409, { code: "agent_run_conflict" });
    return;
  }
  if (request.contract_digest !== loadRuntimeManifest().contract_digest) {
    json(response, 409, { code: "agent_contract_mismatch" });
    return;
  }
  if (activeRuns.size >= maxConcurrentRuns) {
    json(response, 503, { code: "agent_run_capacity_exceeded" });
    return;
  }
  const controller = new AbortController();
  const policy = {
    max_turns: request.policy?.max_turns ?? 8,
    max_tool_calls: request.policy?.max_tool_calls ?? 16,
    max_handoffs: 0 as const,
    timeout_seconds:
      request.policy?.timeout_seconds ?? operationDeadlineSeconds(request.operation),
    max_input_bytes: request.policy?.max_input_bytes ?? 131_072,
    max_output_bytes: request.policy?.max_output_bytes ?? 262_144,
    max_event_bytes: request.policy?.max_event_bytes ?? 65_536,
  };
  const effectiveDeadline = Math.min(
    Date.parse(request.deadline_at),
    Date.now() + policy.timeout_seconds * 1000,
  );
  const budget = new RunBudget(policy, effectiveDeadline);
  try {
    budget.observeInput(Buffer.byteLength(JSON.stringify(request)));
  } catch {
    json(response, 422, { code: "agent_run_budget_exceeded" });
    return;
  }
  response.writeHead(200, {
    "content-type": "application/x-ndjson; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  const active: ActiveRun = { controller };
  activeRuns.set(request.run_id, active);
  if (conversationId) activeConversations.set(conversationId, request.run_id);
  const startedAt = Date.now();
  const eventBuffer = new EventBuffer(response, maxQueueBytes);
  let terminalEmitted = false;
  const emit = async (candidate: AgentRuntimeEvent): Promise<void> => {
    if (terminalEmitted) return;
    const next = event(request, 0, candidate.event_type, candidate.payload ?? {});
    const encoded = `${JSON.stringify(next)}\n`;
    const terminal = terminalEvents.has(next.event_type);
    if (!terminal) {
      budget.observeEvent(Buffer.byteLength(encoded));
      if (next.event_type === "output_delta") {
        budget.observeOutput(Buffer.byteLength(JSON.stringify(next.payload)));
      }
    }
    if (terminal) {
      terminalEmitted = eventBuffer.enqueueTerminal(next);
      return;
    }
    eventBuffer.enqueue(next);
  };
  const heartbeat = setInterval(() => {
    if (!terminalEmitted && !controller.signal.aborted) {
      void emit(event(request, 0, "heartbeat", {})).catch(() => controller.abort());
    }
  }, heartbeatIntervalMs);
  heartbeat.unref();
  const timeout = setTimeout(
    () => {
      if (!active.abortCause) active.abortCause = "deadline";
      controller.abort(new DOMException("Run timed out.", "TimeoutError"));
    },
    Math.max(1, budget.remainingMs()),
  );
  timeout.unref();

  try {
    await emit(event(request, 0, "run_started", { fake: false }));
    const result = await adapter.run(request, controller.signal, emit, budget);
    await emit(
      event(
        request,
        0,
        "run_completed",
        completedPayload(result, Date.now() - startedAt),
      ),
    );
  } catch (error) {
    if (!terminalEmitted) {
      const failure = safeRuntimeFailure(error);
      logStructuredRejectionDiagnostic(request, failure);
      logTerminalProviderDiagnostic(request, failure);
      logPromptProjectionDiagnostic(request, failure);
      const terminal = terminalForFailure(active.abortCause, failure);
      await emit(
        event(request, 0, terminal.eventType, {
          code: terminal.code,
          message: terminal.message,
          retryable: terminal.retryable,
          audit: terminalFailureAudit(
            request,
            terminal,
            failure,
            Math.max(0, Date.now() - startedAt),
          ),
        }),
      );
    }
  } finally {
    clearInterval(heartbeat);
    clearTimeout(timeout);
    activeRuns.delete(request.run_id);
    if (conversationId) activeConversations.delete(conversationId);
    await eventBuffer.close();
    response.end();
  }
}

function completedPayload(
  result: Readonly<Record<string, unknown>>,
  durationMs: number,
): Readonly<Record<string, unknown>> {
  const { agent_runtime_audit: candidateAudit, ...value } = result;
  const audit =
    candidateAudit &&
    typeof candidateAudit === "object" &&
    !Array.isArray(candidateAudit)
      ? candidateAudit
      : {};
  return {
    value,
    audit: {
      ...audit,
      duration_ms: Math.max(0, durationMs),
    },
  };
}

function terminalForFailure(
  cause: AbortCause | undefined,
  failure: RuntimeFailure | undefined,
): {
  eventType: "run_failed" | "run_cancelled";
  code: string;
  message: string;
  retryable: boolean;
  attemptStage: string;
} {
  if (cause === "deadline") {
    return {
      eventType: "run_failed",
      code: "agent_deadline_exceeded",
      message: "Agent run deadline exceeded.",
      retryable: true,
      attemptStage: "initial",
    };
  }
  if (cause === "explicit_cancel" || cause === "server_shutdown") {
    return {
      eventType: "run_cancelled",
      code: "agent_run_cancelled",
      message: "Agent run was cancelled.",
      retryable: false,
      attemptStage: "initial",
    };
  }
  return {
    eventType: "run_failed",
    code: failure?.code ?? "agent_runtime_unavailable",
    message: safeFailureMessage(failure?.code),
    retryable: failure?.retryable ?? false,
    attemptStage: failure?.attemptStage ?? "initial",
  };
}

function safeFailureMessage(code: string | undefined): string {
  return (code && safeFailureMessages[code]) ?? "Agent runtime failed.";
}

function terminalFailureAudit(
  request: AgentRunRequest,
  terminal: ReturnType<typeof terminalForFailure>,
  failure: RuntimeFailure | undefined,
  durationMs: number,
): TerminalFailureAudit {
  const attempt = failure?.attemptMetadata;
  const modelSubmissionCount = submittedModelCount(terminal.code, attempt);
  const responseActivityObserved = attempt?.response_activity_observed ??
    (modelSubmissionCount === 0 ? false : undefined);
  return {
    duration_ms: durationMs,
    operation: request.operation,
    agent_name: request.agent_name,
    operation_policy_id:
      attempt?.operation_policy_id ?? request.policy?.operation_policy_id,
    attempt_stage: attempt?.attempt_stage ?? terminal.attemptStage,
    ...safeAttemptAudit(attempt),
    ...safeProjectionAudit(failure?.projectionMetadata),
    failure_boundary: failureBoundary(terminal.code, attempt),
    ...(modelSubmissionCount === undefined ? {} : { model_submission_count: modelSubmissionCount }),
    ...(responseActivityObserved === undefined
      ? {}
      : { response_activity_observed: responseActivityObserved }),
    retryable: terminal.retryable,
    terminal_code: terminal.code,
  };
}

function submittedModelCount(
  code: string,
  attempt: FailureAudit,
): number | undefined {
  if (attempt) {
    return Math.max(
      1,
      attempt.transport_retry_count + 1,
      attempt.structured_attempt_count,
    );
  }
  return preSubmissionFailureCodes.has(code) ? 0 : undefined;
}

function failureBoundary(code: string, attempt: FailureAudit): string {
  if (providerFailureCodes.has(code)) return "provider";
  if (structuredFailureCodes.has(code)) return "structured_validation";
  if (preSubmissionFailureCodes.has(code)) return "operation_preparation";
  if (attempt) return "model_response";
  return "runtime_internal";
}

function safeAttemptAudit(attempt: FailureAudit): TerminalFailureAudit {
  if (!attempt) return {};
  return {
    provider: boundedAuditText(attempt.provider, 160),
    model_ref: boundedAuditText(attempt.model_ref, 320),
    structured_transport: attempt.structured_transport,
    thinking_format: attempt.thinking_format,
    reasoning_control: attempt.reasoning_control,
    reasoning_mode: attempt.reasoning_mode,
    reasoning_effort: attempt.reasoning_effort,
    enable_thinking: attempt.enable_thinking,
    thinking_budget_tokens: attempt.thinking_budget_tokens,
    deadline_seconds: attempt.deadline_seconds,
    max_output_tokens: attempt.max_output_tokens,
    operation_policy_id: boundedAuditText(attempt.operation_policy_id, 160),
    operation_class: attempt.operation_class,
    effective_timeout_ms: attempt.effective_timeout_ms,
    request_bytes: attempt.request_bytes,
    schema_bytes: attempt.schema_bytes,
    response_activity_observed: attempt.response_activity_observed,
    attempt_stage: attempt.attempt_stage,
    started_at: boundedAuditText(attempt.started_at, 64),
    first_response_at: boundedOptionalAuditText(attempt.first_response_at, 64),
    last_activity_at: boundedOptionalAuditText(attempt.last_activity_at, 64),
    finished_at: boundedAuditText(attempt.finished_at, 64),
    duration_ms: attempt.duration_ms,
    finish_reason: boundedOptionalAuditText(attempt.finish_reason, 160),
    provider_trace_id: boundedOptionalAuditText(attempt.provider_trace_id, 320),
    safe_exception_class: boundedOptionalAuditText(attempt.safe_exception_class, 160),
    safe_error_code: boundedOptionalAuditText(attempt.safe_error_code, 120),
    http_status: attempt.http_status,
    input_tokens: attempt.input_tokens,
    output_tokens: attempt.output_tokens,
    reasoning_tokens: attempt.reasoning_tokens,
    transport_retry_count: attempt.transport_retry_count,
    structured_attempt_count: attempt.structured_attempt_count,
    structured_validation_attempts: attempt.structured_validation_attempts,
  };
}

function safeProjectionAudit(
  projection: ProjectionFailureAudit | undefined,
): TerminalFailureAudit {
  if (!projection) return {};
  return {
    context_contract_name: boundedAuditText(projection.context_contract_name, 160),
    ...(projection.projection_id
      ? { projection_id: boundedAuditText(projection.projection_id, 160) }
      : {}),
  };
}

function boundedAuditText(value: string, maximum: number): string {
  return value.slice(0, maximum);
}

function boundedOptionalAuditText(
  value: string | null | undefined,
  maximum: number,
): string | null | undefined {
  return typeof value === "string" ? value.slice(0, maximum) : value;
}

class RuntimeFailure extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly retryable = false,
    readonly attemptStage = "initial",
    readonly attemptMetadata?: FailureAudit,
    readonly projectionMetadata?: ProjectionFailureAudit,
  ) {
    super(message);
  }
}

function safeRuntimeFailure(error: unknown): RuntimeFailure | undefined {
  if (error instanceof RunBudgetFailure) {
    return new RuntimeFailure(error.code, "Agent runtime policy rejected the operation.");
  }
  if (error instanceof EventBufferOverflow) {
    return new RuntimeFailure(error.code, error.message);
  }
  if (error instanceof AgentOperationFailure) {
    return new RuntimeFailure(
      error.code,
      safeFailureMessage(error.code),
      error.retryable,
      error.attemptStage,
      error.attemptMetadata,
    );
  }
  if (error instanceof AgentPromptInputProjectionError) {
    return new RuntimeFailure(
      error.code,
      "Agent Prompt input could not be projected.",
      false,
      "initial",
      undefined,
      {
        context_contract_name: error.contextContractName,
        ...(error.projectionId ? { projection_id: error.projectionId } : {}),
      },
    );
  }
  if (error instanceof RuntimeFailure) return error;
  if (error instanceof Error && safeAdapterErrorCodes.has(error.message)) {
    return new RuntimeFailure(error.message, "Agent runtime rejected the operation.");
  }
  return undefined;
}

function logTerminalProviderDiagnostic(
  request: AgentRunRequest,
  failure: RuntimeFailure | undefined,
): void {
  if (
    failure?.code !== "agent_provider_timeout" &&
    failure?.code !== "agent_provider_transport_failed"
  ) {
    return;
  }
  const audit = failure.attemptMetadata;
  console.error(
    JSON.stringify({
      event: "agent_provider_terminal_failure",
      run_id: request.run_id,
      agent_name: request.agent_name,
      operation: request.operation,
      stable_error_code: failure.code,
      operation_policy_id:
        audit?.operation_policy_id ?? request.policy?.operation_policy_id,
      operation_class: audit?.operation_class ?? request.policy?.operation_class,
      effective_timeout_ms: audit?.effective_timeout_ms,
      attempt_stage: audit?.attempt_stage ?? failure.attemptStage,
      safe_exception_class: audit?.safe_exception_class,
      safe_error_code: audit?.safe_error_code,
      http_status: audit?.http_status,
      provider_trace_id: audit?.provider_trace_id,
    }),
  );
}

function logStructuredRejectionDiagnostic(
  request: AgentRunRequest,
  failure: RuntimeFailure | undefined,
): void {
  if (failure?.code !== "agent_structured_output_invalid") return;
  console.warn(
    JSON.stringify({
      event: "agent_structured_submission_rejected",
      run_id: request.run_id,
      agent_name: request.agent_name,
      operation: request.operation,
      stage: "structured_submission",
      safe_error_code: failure.code,
      exception_class: failure.constructor.name,
      retryable: false,
    }),
  );
}

function logPromptProjectionDiagnostic(
  request: AgentRunRequest,
  failure: RuntimeFailure | undefined,
): void {
  if (
    failure?.code !== "agent_context_input_missing" &&
    failure?.code !== "agent_prompt_input_registry_invalid"
  ) {
    return;
  }
  console.warn(
    JSON.stringify({
      event: "agent_prompt_input_projection_failed",
      run_id: request.run_id,
      agent_name: request.agent_name,
      operation: request.operation,
      context_contract_name: failure.projectionMetadata?.context_contract_name,
      projection_id: failure.projectionMetadata?.projection_id,
      stable_error_code: failure.code,
      attempt_stage: failure.attemptStage,
      retryable: false,
    }),
  );
}

async function readJson(incoming: IncomingMessage, maximumBytes: number): Promise<unknown> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of incoming) {
    const buffer = Buffer.from(chunk);
    bytes += buffer.byteLength;
    if (bytes > maximumBytes) throw new Error("request too large");
    chunks.push(buffer);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf-8"));
}

function authorized(request: IncomingMessage, expectedToken: string): boolean {
  const header = request.headers.authorization;
  if (!header?.startsWith("Bearer ")) return false;
  const supplied = Buffer.from(header.slice(7));
  const expected = Buffer.from(expectedToken);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

function json(response: ServerResponse, status: number, payload: unknown): void {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(payload));
}
