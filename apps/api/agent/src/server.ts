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
import { RunBudget, RunBudgetFailure } from "./run-budget.js";

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

const terminalEvents = new Set(["run_completed", "run_failed", "run_cancelled"]);
const safeAdapterErrorCodes = new Set([
  "agent_model_unavailable",
  "agent_structured_output_invalid",
  "agent_run_budget_exceeded",
  "agent_tool_not_allowed",
  "agent_target_revision_conflict",
]);

export function createAgentRuntimeServer(options: ServerOptions) {
  const adapter = options.adapter ?? new FakeAgentModelAdapter();
  const maxRequestBytes = options.maxRequestBytes ?? 1_048_576;
  const maxQueueBytes = options.maxQueueBytes ?? 262_144;
  const maxConcurrentRuns = options.maxConcurrentRuns ?? 8;
  const heartbeatIntervalMs = options.heartbeatIntervalMs ?? 15_000;
  const activeRuns = new Map<string, ActiveRun>();

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
  maxRequestBytes: number,
  maxQueueBytes: number,
  heartbeatIntervalMs: number,
  maxConcurrentRuns: number,
): Promise<void> {
  let request: AgentRunRequest;
  try {
    request = validateAgentRunRequest(await readJson(incoming, maxRequestBytes));
  } catch {
    json(response, 422, { code: "agent_protocol_mismatch" });
    return;
  }
  if (activeRuns.has(request.run_id)) {
    json(response, 409, { code: "agent_run_already_active" });
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
    max_handoffs: request.policy?.max_handoffs ?? 8,
    timeout_seconds: request.policy?.timeout_seconds ?? 120,
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
      const terminal = terminalForFailure(active.abortCause, failure);
      await emit(
        event(request, 0, terminal.eventType, {
          code: terminal.code,
          message: terminal.message,
          audit: { duration_ms: Math.max(0, Date.now() - startedAt) },
        }),
      );
    }
  } finally {
    clearInterval(heartbeat);
    clearTimeout(timeout);
    activeRuns.delete(request.run_id);
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
} {
  if (cause === "deadline") {
    return {
      eventType: "run_failed",
      code: "agent_deadline_exceeded",
      message: "Agent run deadline exceeded.",
    };
  }
  if (cause === "explicit_cancel" || cause === "server_shutdown") {
    return {
      eventType: "run_cancelled",
      code: "agent_run_cancelled",
      message: "Agent run was cancelled.",
    };
  }
  return {
    eventType: "run_failed",
    code: failure?.code ?? "agent_runtime_unavailable",
    message: failure?.message ?? "Agent runtime failed.",
  };
}

class RuntimeFailure extends Error {
  constructor(
    readonly code: string,
    message: string,
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
  if (error instanceof RuntimeFailure) return error;
  if (error instanceof Error && safeAdapterErrorCodes.has(error.message)) {
    return new RuntimeFailure(error.message, "Agent runtime rejected the operation.");
  }
  return undefined;
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
