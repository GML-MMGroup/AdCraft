import { randomUUID } from "node:crypto";
import type { AssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { WorkflowModelCallWriteV1 } from "./generated/agent-runtime.js";
import { isAcceptanceReplaySource, type AgentRuntimeTransportSource } from "./python-internal-client.js";
import type { AgentRunRequest } from "./generated/agent-runtime.js";
import type { ModelAttemptStage } from "./run-budget.js";

export interface WorkflowModelCallClient {
  recordWorkflowModelCall?(record: WorkflowModelCallWriteV1): Promise<unknown>;
}

interface CaptureOptions {
  readonly runId: string;
  readonly stage: ModelAttemptStage;
  readonly boundary: WorkflowModelCallWriteV1["boundary"];
  readonly write: (record: WorkflowModelCallWriteV1) => Promise<unknown>;
  readonly secrets?: ReadonlyArray<string>;
  readonly maxBytes?: number;
  readonly warn?: (code: string) => void;
}

/** Best-effort diagnostics: no caller awaits storage, and no error escapes. */
export class WorkflowModelCallCapture {
  readonly #id = `mcall-${randomUUID()}`;
  readonly #chunks: unknown[] = [];
  #bytes = 0;
  #truncated = false;
  #pending: Promise<void> = Promise.resolve();
  #begun = false;
  #stored = false;
  #finished = false;

  constructor(private readonly options: CaptureOptions) {}

  begin(payload: Readonly<Record<string, unknown>>): void {
    if (this.#begun) return;
    this.#begun = true;
    this.#enqueue("request", payload, false, true);
  }

  chunk(chunk: unknown): void {
    if (this.#truncated) return;
    try {
      const safe = this.#snapshot(chunk);
      const bytes = Buffer.byteLength(JSON.stringify(safe));
      if (this.#bytes + bytes > (this.options.maxBytes ?? 6 * 1024 * 1024)) {
        this.#truncated = true;
        return;
      }
      this.#bytes += bytes;
      this.#chunks.push(safe);
    } catch {
      this.#truncated = true;
      this.#warn();
    }
  }

  finish(payload: Readonly<Record<string, unknown>>, failed = false, complete = true): void {
    if (this.#finished || !this.#begun) return;
    this.#finished = true;
    this.#enqueue("outcome", {
      ...payload,
      ...(this.#chunks.length ? { chunks: this.#chunks } : {}),
      capture_truncated: this.#truncated,
    }, failed, complete && !this.#truncated);
  }

  async settled(): Promise<void> { await this.#pending; }

  #snapshot(value: unknown): unknown {
    const encoded = JSON.stringify(value, (key, item: unknown) => {
      if (/^(authorization|proxy.authorization|.*api.?key|.*access.?token|.*refresh.?token|.*secret.*|password|cookie|set.cookie|credential|signature|x.amz.signature|x.goog.signature|sig|token)$/i.test(key)) return "[REDACTED]";
      if (typeof item !== "string") return item;
      let safe = item;
      for (const secret of this.options.secrets ?? []) {
        if (secret) safe = safe.replaceAll(secret, "[REDACTED]");
      }
      return safe.replace(/\bBearer\s+[^\s"'\\,;]+/gi, "Bearer [REDACTED]");
    });
    if (Buffer.byteLength(encoded) > 12 * 1024 * 1024) throw new Error("capture_limit");
    return JSON.parse(encoded) as unknown;
  }

  #enqueue(phase: "request" | "outcome", payload: Readonly<Record<string, unknown>>, failed: boolean, complete: boolean): void {
    try {
      let snapshot: Record<string, unknown>;
      try {
        snapshot = this.#snapshot(payload) as Record<string, unknown>;
      } catch {
        snapshot = { capture_truncated: true, capture_error: "serialization_or_size_limit" };
        complete = false;
        this.#warn();
      }
      const record: WorkflowModelCallWriteV1 = {
        schema_version: "1", run_id: this.options.runId, call_id: this.#id,
        stage: this.options.stage, phase, boundary: this.options.boundary,
        recorded_at: new Date().toISOString(), payload: snapshot, failed, complete,
      };
      this.#pending = this.#pending.then(async () => {
        if (phase === "outcome" && !this.#stored) return;
        await this.options.write(record);
        if (phase === "request") this.#stored = true;
      }).catch(() => { this.#warn(); });
    } catch { this.#warn(); }
  }

  #warn(): void {
    try {
      (this.options.warn ?? console.warn)("agent_model_call_capture_unavailable");
    } catch { /* Diagnostics must never change the owning model operation. */ }
  }
}

export function workflowModelCallCapture(
  client: WorkflowModelCallClient | undefined,
  credential: AgentRuntimeTransportSource,
  request: AgentRunRequest,
  stage: ModelAttemptStage,
  boundary: WorkflowModelCallWriteV1["boundary"],
): WorkflowModelCallCapture | undefined {
  if (isAcceptanceReplaySource(credential) || !client?.recordWorkflowModelCall) return undefined;
  return new WorkflowModelCallCapture({
    runId: request.run_id, stage, boundary, secrets: [credential.api_key],
    write: (record) => client.recordWorkflowModelCall!(record),
  });
}

/** Do not serialize Error stacks, request clients, sockets or credentials. */
export function modelCallFailure(error: unknown): Record<string, unknown> {
  const source = error && typeof error === "object" ? error as Record<string, unknown> : {};
  return Object.fromEntries(
    ["name", "message", "code", "status", "statusCode", "error", "request_id", "response_started"]
      .filter((key) => source[key] !== undefined)
      .map((key) => [key, source[key]]),
  );
}

export function observeWorkflowAssistantStream(
  source: AssistantMessageEventStream,
  capture: WorkflowModelCallCapture | undefined,
): AssistantMessageEventStream {
  if (!capture) return source;
  async function* observe() {
    let terminal = false;
    let partial: unknown;
    try {
      for await (const event of source) {
        if ("partial" in event) partial = event.partial;
        if (event.type === "done" || event.type === "error") {
          terminal = true;
          capture!.finish({ assistant_message: event.type === "done" ? event.message : event.error }, event.type === "error", event.type === "done");
        } else {
          const { partial: _partial, ...delta } = event;
          capture!.chunk(delta);
        }
        yield event;
      }
    } catch (error) {
      terminal = true;
      capture!.finish({ error: modelCallFailure(error), partial_assistant_message: partial }, true, false);
      throw error;
    } finally {
      if (!terminal) capture!.finish({ partial_assistant_message: partial }, false, false);
    }
  }
  // Preserve the SDK stream's result API and event identity; do not buffer or
  // reconstruct events, swallow exceptions, or wait for diagnostic persistence.
  return new Proxy(source, {
    get(target, key) {
      if (key === Symbol.asyncIterator) return observe;
      const value: unknown = Reflect.get(target, key, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}
