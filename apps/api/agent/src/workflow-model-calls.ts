import { randomUUID } from "node:crypto";
import type { AssistantMessageEventStream } from "@earendil-works/pi-ai";
import type { WorkflowModelCallWriteV1 } from "./generated/agent-runtime.js";
import { isAcceptanceReplaySource, type AgentRuntimeTransportSource } from "./python-internal-client.js";
import type { AgentRunRequest } from "./generated/agent-runtime.js";
import type { ModelAttemptStage } from "./run-budget.js";
import type { LoadedSkill } from "./skills.js";

export interface WorkflowModelCallSkillContext {
  readonly [key: string]: unknown;
  readonly internal_capability_skills: ReadonlyArray<Readonly<Record<string, unknown>>>;
  readonly creative_method_skills: ReadonlyArray<Readonly<Record<string, unknown>>>;
  readonly audiovisual_style_skills: ReadonlyArray<Readonly<Record<string, unknown>>>;
}

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
  readonly skillContext?: WorkflowModelCallSkillContext;
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
    try {
      redactStreamFragments(this.#chunks, this.options.secrets ?? []);
    } catch {
      this.#chunks.length = 0;
      this.#truncated = true;
      this.#warn();
    }
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
        ...(this.options.skillContext
          ? { skill_context: this.options.skillContext as Readonly<Record<string, unknown>> }
          : {}),
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
      (this.options.warn ?? console.warn)(JSON.stringify({
        code: "agent_model_call_capture_unavailable", run_id: this.options.runId,
        call_id: this.#id, stage: this.options.stage,
      }));
    } catch { /* Diagnostics must never change the owning model operation. */ }
  }
}

/**
 * Project user-facing creative Skills into a compact, readable diagnostic
 * summary. The full request remains captured separately; this projection is
 * intentionally metadata-only so logs do not duplicate large prompt bodies.
 */
export function buildWorkflowModelCallSkillContext(
  request: AgentRunRequest,
  loadedSkills: ReadonlyArray<LoadedSkill> = [],
): WorkflowModelCallSkillContext {
  const internalCapabilitySkills = loadedSkills.map((skill) => ({
    skill_id: skill.skill_id,
    version: skill.version ?? null,
    digest: skill.sha256 ?? null,
  }));
  const creativeMethodSkills: Array<Readonly<Record<string, unknown>>> = [];
  const audiovisualStyleSkills: Array<Readonly<Record<string, unknown>>> = [];
  const seenCreative = new Set<string>();
  const seenStyle = new Set<string>();

  const addCreative = (entry: Readonly<Record<string, unknown>>): void => {
    if (typeof entry.skill_id !== "string") return;
    const key = `${entry.skill_id}:${typeof entry.version === "string" ? entry.version : ""}`;
    if (seenCreative.has(key)) return;
    seenCreative.add(key);
    creativeMethodSkills.push({
      skill_kind: "creative_method",
      skill_id: entry.skill_id,
      title: typeof entry.title === "string" ? entry.title : null,
      version: typeof entry.version === "string" ? entry.version : null,
      selected: entry.selected !== false,
      ...(typeof entry.reason === "string" ? { reason: entry.reason } : {}),
    });
  };

  const addStyle = (entry: Readonly<Record<string, unknown>>): void => {
    if (typeof entry.skill_id !== "string") return;
    const version =
      typeof entry.skill_version === "string"
        ? entry.skill_version
        : typeof entry.version === "string"
          ? entry.version
          : null;
    const runId = typeof entry.skill_run_id === "string" ? entry.skill_run_id : null;
    const key = `${entry.skill_id}:${version ?? ""}:${runId ?? ""}`;
    if (seenStyle.has(key)) return;
    seenStyle.add(key);
    audiovisualStyleSkills.push({
      skill_kind: "audiovisual_style",
      skill_id: entry.skill_id,
      version,
      skill_run_id: runId,
      ...(typeof entry.title === "string" ? { title: entry.title } : {}),
      ...(typeof entry.role === "string" ? { role: entry.role } : {}),
      ...(typeof entry.package_digest === "string" ? { package_digest: entry.package_digest } : {}),
      ...(typeof entry.creative_direction_snapshot_id === "string"
        ? { creative_direction_snapshot_id: entry.creative_direction_snapshot_id }
        : {}),
      ...(typeof entry.role_guidance_digest === "string"
        ? { role_guidance_digest: entry.role_guidance_digest }
        : {}),
    });
  };

  const visit = (value: unknown, parentKey = ""): void => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item, parentKey);
      return;
    }
    if (!value || typeof value !== "object") return;
    const object = value as Readonly<Record<string, unknown>>;
    if (object.skill_kind === "creative_method") addCreative(object);
    if (object.skill_kind === "audiovisual_style") addStyle(object);
    if (
      typeof object.skill_id === "string" &&
      (parentKey === "style_guidance" || parentKey === "style_projection")
    ) {
      addStyle(object);
    }
    for (const [key, child] of Object.entries(object)) visit(child, key);
  };
  visit(request.context);

  return {
    internal_capability_skills: internalCapabilitySkills,
    creative_method_skills: creativeMethodSkills,
    audiovisual_style_skills: audiovisualStyleSkills,
  };
}

/** A credential can straddle SDK chunks; sanitize the joined field channel. */
function redactStreamFragments(chunks: unknown[], secrets: ReadonlyArray<string>): void {
  type Fragment = { parent: Record<string, unknown>; key: string; text: string };
  const channels = new Map<string, Fragment[]>();
  const visit = (value: unknown, path: string): void => {
    if (Array.isArray(value)) { for (const item of value) visit(item, `${path}[]`); return; }
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      const channel = `${path}/${key}`;
      if (typeof child === "string") {
        const fragments = channels.get(channel) ?? [];
        fragments.push({ parent: value as Record<string, unknown>, key, text: child });
        channels.set(channel, fragments);
      } else visit(child, channel);
    }
  };
  visit(chunks, "");
  for (const fragments of channels.values()) {
    const joined = fragments.map((fragment) => fragment.text).join("");
    const ranges: Array<[number, number]> = [];
    for (const secret of secrets) {
      if (!secret) continue;
      let position = joined.indexOf(secret);
      while (position >= 0) {
        ranges.push([position, position + secret.length]);
        position = joined.indexOf(secret, position + secret.length);
      }
    }
    for (const match of joined.matchAll(/\bBearer\s+[^\s"'\\,;]+|(?:api[_-]?key|access[_-]?token|password|secret|x-amz-signature|x-goog-signature|sig|token)["']?\s*[=:]\s*["']?[^\s&"'<>]+/gi)) {
      ranges.push([match.index, match.index + match[0].length]);
    }
    ranges.sort((left, right) => left[0] - right[0]);
    let offset = 0;
    let rangeIndex = 0;
    for (const fragment of fragments) {
      const end = offset + fragment.text.length;
      while (rangeIndex < ranges.length && ranges[rangeIndex]![1] <= offset) rangeIndex += 1;
      if (ranges[rangeIndex] && ranges[rangeIndex]![0] < end) fragment.parent[fragment.key] = "[REDACTED]";
      offset = end;
    }
  }
}

export function workflowModelCallCapture(
  client: WorkflowModelCallClient | undefined,
  credential: AgentRuntimeTransportSource,
  request: AgentRunRequest,
  stage: ModelAttemptStage,
  boundary: WorkflowModelCallWriteV1["boundary"],
  loadedSkills: ReadonlyArray<LoadedSkill> = [],
): WorkflowModelCallCapture | undefined {
  if (isAcceptanceReplaySource(credential) || !client?.recordWorkflowModelCall) return undefined;
  return new WorkflowModelCallCapture({
    runId: request.run_id, stage, boundary, secrets: [credential.api_key],
    skillContext: buildWorkflowModelCallSkillContext(request, loadedSkills),
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
