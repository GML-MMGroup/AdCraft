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
import { loadRuntimeManifest } from "./manifest.js";

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
}

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

  return createServer(async (incoming, response) => {
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
      active?.controller.abort();
      json(response, 200, {
        protocol_version: "1",
        run_id: runId,
        status: active ? "cancelling" : "not_active",
      });
      return;
    }
    json(response, 404, { code: "agent_internal_route_not_found" });
  });
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
    request = validateRequest(await readJson(incoming, maxRequestBytes));
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
  response.writeHead(200, {
    "content-type": "application/x-ndjson; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });

  const controller = new AbortController();
  activeRuns.set(request.run_id, { controller });
  let seq = 0;
  let terminalEmitted = false;
  const emit = async (candidate: AgentRuntimeEvent): Promise<void> => {
    if (terminalEmitted) return;
    const next = event(request, seq + 1, candidate.event_type, candidate.payload ?? {});
    const encoded = `${JSON.stringify(next)}\n`;
    const terminal = terminalEvents.has(next.event_type);
    if (!terminal && Buffer.byteLength(encoded) > maxQueueBytes) {
      throw new RuntimeFailure(
        "agent_stream_backpressure_exceeded",
        "Agent runtime event exceeded the bounded output queue.",
      );
    }
    seq = next.seq;
    if (terminal) terminalEmitted = true;
    response.write(encoded);
  };
  const heartbeat = setInterval(() => {
    if (!terminalEmitted && !controller.signal.aborted) {
      void emit(event(request, 0, "heartbeat", {})).catch(() => controller.abort());
    }
  }, heartbeatIntervalMs);
  heartbeat.unref();
  const timeout = setTimeout(
    () => controller.abort(new DOMException("Run timed out.", "TimeoutError")),
    Math.max(1, request.policy?.timeout_seconds ?? 120) * 1000,
  );
  timeout.unref();

  try {
    await emit(event(request, 0, "run_started", { fake: false }));
    const result = await adapter.run(request, controller.signal, emit);
    await emit(event(request, 0, "run_completed", result));
  } catch (error) {
    if (!terminalEmitted) {
      const cancelled =
        controller.signal.aborted ||
        (error instanceof DOMException && error.name === "AbortError");
      const failure = safeRuntimeFailure(error);
      await emit(
        event(request, 0, cancelled ? "run_cancelled" : "run_failed", {
          code: cancelled
            ? "agent_run_cancelled"
            : (failure?.code ?? "agent_runtime_unavailable"),
          message: cancelled
            ? "Agent run was cancelled."
            : (failure?.message ?? "Agent runtime failed."),
        }),
      );
    }
  } finally {
    clearInterval(heartbeat);
    clearTimeout(timeout);
    activeRuns.delete(request.run_id);
    response.end();
  }
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
  if (error instanceof RuntimeFailure) return error;
  if (error instanceof Error && safeAdapterErrorCodes.has(error.message)) {
    return new RuntimeFailure(error.message, "Agent runtime rejected the operation.");
  }
  return undefined;
}

function validateRequest(value: unknown): AgentRunRequest {
  if (!value || typeof value !== "object") throw new Error("invalid request");
  const request = value as Partial<AgentRunRequest>;
  if (
    request.protocol_version !== "1" ||
    !request.run_id ||
    !request.request_id ||
    !request.agent_name ||
    !request.operation ||
    !request.context?.user_input
  ) {
    throw new Error("invalid request");
  }
  return request as AgentRunRequest;
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
