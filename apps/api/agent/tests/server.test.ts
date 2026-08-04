import { once } from "node:events";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAgentRuntimeServer } from "../src/server.js";
import type { AgentModelAdapter, EventSink } from "../src/runtime.js";
import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import { loadRuntimeManifest } from "../src/manifest.js";

const servers: Array<ReturnType<typeof createAgentRuntimeServer>> = [];

const request: AgentRunRequest = {
  protocol_version: "1",
  run_id: "arun_test",
  request_id: "req_test",
  contract_digest: loadRuntimeManifest().contract_digest,
  context_snapshot_id: "context_test",
  agent_name: "director",
  operation: "conversation_turn",
  deadline_at: new Date(Date.now() + 5 * 60_000).toISOString(),
  model_policy_id: "director.conversation_turn.v1",
  context: {
    operation: "conversation_turn",
    user_input: "Create a product launch workflow.",
  },
  policy: {
    max_turns: 4,
    max_tool_calls: 4,
    max_handoffs: 1,
    timeout_seconds: 2,
    max_input_bytes: 4096,
    max_output_bytes: 4096,
    max_event_bytes: 4096,
  },
  credential_ref: "llm-default",
};

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) =>
        new Promise<void>((resolve) => {
          server.close(() => resolve());
        }),
    ),
  );
});

async function start(adapter?: AgentModelAdapter, options: Record<string, unknown> = {}) {
  const server = createAgentRuntimeServer({
    internalToken: "test-token",
    mode: "fake",
    ...(adapter ? { adapter } : {}),
    ...options,
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  servers.push(server);
  const address = server.address() as AddressInfo;
  return `http://127.0.0.1:${address.port}`;
}

describe("agent runtime server", () => {
  it("protects health and run endpoints with internal auth", async () => {
    const baseUrl = await start();
    const denied = await fetch(`${baseUrl}/internal/v1/health`);
    const accepted = await fetch(`${baseUrl}/internal/v1/health`, {
      headers: { authorization: "Bearer test-token" },
    });

    expect(denied.status).toBe(401);
    expect(accepted.status).toBe(200);
    expect(await accepted.json()).toMatchObject({
      protocol_version: "1",
      status: "ready",
      mode: "fake",
    });
  });

  it("streams ordered events and exactly one terminal event", async () => {
    const baseUrl = await start();
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify(request),
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/x-ndjson");
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { seq: number; event_type: string });
    expect(events.map((item) => item.seq)).toEqual([1, 2, 3]);
    expect(events.filter((item) => item.event_type.startsWith("run_"))).toEqual([
      expect.objectContaining({ event_type: "run_started" }),
      expect.objectContaining({ event_type: "run_completed" }),
    ]);
  });

  it("rejects a request built against a different contract digest", async () => {
    const baseUrl = await start();
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        contract_digest: "0".repeat(64),
      }),
    });

    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ code: "agent_contract_mismatch" });
  });

  it("cancels a running request without emitting two terminal events", async () => {
    let entered!: () => void;
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, signal: AbortSignal, _emit: EventSink) {
        entered();
        await new Promise<void>((resolve, reject) => {
          signal.addEventListener("abort", () => reject(new DOMException("cancel", "AbortError")));
        });
        return {};
      },
    };
    const baseUrl = await start(adapter);
    const runPromise = fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({ ...request, run_id: "arun_cancel" }),
    });
    await started;
    const cancelled = await fetch(
      `${baseUrl}/internal/v1/agent-runs/arun_cancel/cancel`,
      {
        method: "POST",
        headers: {
          authorization: "Bearer test-token",
          "content-type": "application/json",
        },
        body: JSON.stringify({ reason: "test_cancel" }),
      },
    );
    const repeated = await fetch(
      `${baseUrl}/internal/v1/agent-runs/arun_cancel/cancel`,
      {
        method: "POST",
        headers: { authorization: "Bearer test-token" },
      },
    );
    const response = await runPromise;
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event_type: string });

    expect(cancelled.status).toBe(200);
    expect(repeated.status).toBe(200);
    expect(events.filter((item) => item.event_type === "run_cancelled")).toHaveLength(1);
    expect(events.filter((item) => item.event_type === "run_failed")).toHaveLength(0);
  });

  it("reports deadline exhaustion as failure rather than cancellation", async () => {
    const adapter: AgentModelAdapter = {
      async run(_request, signal) {
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("deadline", "AbortError")),
          );
        });
        return {};
      },
    };
    const baseUrl = await start(adapter);
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        run_id: "arun_deadline",
        request_id: "req_deadline",
        deadline_at: new Date(Date.now() + 20).toISOString(),
      }),
    });
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event_type: string; payload: { code: string } });

    expect(events.at(-1)).toMatchObject({
      event_type: "run_failed",
      payload: { code: "agent_deadline_exceeded" },
    });
  });

  it("enforces a bounded cognitive concurrency pool", async () => {
    let entered!: () => void;
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, signal: AbortSignal) {
        entered();
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new DOMException("cancel", "AbortError")));
        });
        return {};
      },
    };
    const baseUrl = await start(adapter, { maxConcurrentRuns: 1 });
    const first = fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({ ...request, run_id: "arun_pool_one" }),
    });
    await started;
    const second = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        run_id: "arun_pool_two",
        request_id: "req_pool_two",
      }),
    });
    await fetch(`${baseUrl}/internal/v1/agent-runs/arun_pool_one/cancel`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({ reason: "test_cleanup" }),
    });
    await first;

    expect(second.status).toBe(503);
    expect(await second.json()).toMatchObject({ code: "agent_run_capacity_exceeded" });
  });

  it("allows two conversations by default and rejects a third active run", async () => {
    let entered = 0;
    let bothEntered!: () => void;
    const started = new Promise<void>((resolve) => {
      bothEntered = resolve;
    });
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, signal: AbortSignal) {
        entered += 1;
        if (entered === 2) bothEntered();
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("cancel", "AbortError")),
          );
        });
        return {};
      },
    };
    const baseUrl = await start(adapter);
    const active = ["one", "two"].map((suffix) =>
      fetch(`${baseUrl}/internal/v1/agent-runs`, {
        method: "POST",
        headers: {
          authorization: "Bearer test-token",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          ...request,
          run_id: `arun_default_${suffix}`,
          request_id: `req_default_${suffix}`,
          context: {
            ...request.context,
            conversation_id: `conversation_${suffix}`,
          },
        }),
      }),
    );
    await started;
    const third = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        run_id: "arun_default_three",
        request_id: "req_default_three",
        context: {
          ...request.context,
          conversation_id: "conversation_three",
        },
      }),
    });
    await Promise.all(
      ["one", "two"].map((suffix) =>
        fetch(`${baseUrl}/internal/v1/agent-runs/arun_default_${suffix}/cancel`, {
          method: "POST",
          headers: { authorization: "Bearer test-token" },
        }),
      ),
    );
    await Promise.all(active);

    expect(third.status).toBe(503);
    expect(await third.json()).toMatchObject({
      code: "agent_run_capacity_exceeded",
    });
  });

  it("rejects concurrent runs for the same conversation", async () => {
    let entered!: () => void;
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, signal: AbortSignal) {
        entered();
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("cancel", "AbortError")),
          );
        });
        return {};
      },
    };
    const baseUrl = await start(adapter);
    const first = fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        run_id: "arun_conversation_one",
        context: { ...request.context, conversation_id: "conversation_one" },
      }),
    });
    await started;
    const second = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        run_id: "arun_conversation_two",
        request_id: "req_conversation_two",
        context: { ...request.context, conversation_id: "conversation_one" },
      }),
    });
    await fetch(`${baseUrl}/internal/v1/agent-runs/arun_conversation_one/cancel`, {
      method: "POST",
      headers: { authorization: "Bearer test-token" },
    });
    await first;

    expect(second.status).toBe(409);
    expect(await second.json()).toMatchObject({ code: "agent_run_conflict" });
  });

  it("fails with one terminal event when the event byte budget is exceeded", async () => {
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, _signal: AbortSignal, emit: EventSink) {
        await emit({
          protocol_version: "1",
          seq: 0,
          run_id: "arun_test",
          agent_name: "director",
          event_type: "output_delta",
          created_at: new Date().toISOString(),
          payload: { text: "x".repeat(1000) },
        });
        return {};
      },
    };
    const baseUrl = await start(adapter, { maxQueueBytes: 256 });
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify(request),
    });
    const text = await response.text();

    expect(text).toContain("agent_stream_backpressure_exceeded");
    expect(text.match(/run_failed/g)).toHaveLength(1);
  });

  it("keeps serving after the event budget is exhausted", async () => {
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, _signal: AbortSignal, emit: EventSink) {
        await emit({
          protocol_version: "1",
          seq: 0,
          run_id: "arun_event_budget",
          agent_name: "director",
          event_type: "output_delta",
          created_at: new Date().toISOString(),
          payload: { text: "x".repeat(1000) },
        });
        return {};
      },
    };
    const baseUrl = await start(adapter);
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...request,
        run_id: "arun_event_budget",
        request_id: "req_event_budget",
        policy: {
          ...request.policy,
          max_event_bytes: 512,
        },
      }),
    });
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as {
        event_type: string;
        payload: { code?: string };
      });
    const health = await fetch(`${baseUrl}/internal/v1/health`, {
      headers: { authorization: "Bearer test-token" },
    });

    expect(events.at(-1)).toMatchObject({
      event_type: "run_failed",
      payload: { code: "agent_run_budget_exceeded" },
    });
    expect(health.status).toBe(200);
  });

  it("preserves allowlisted adapter error codes in the terminal event", async () => {
    const adapter: AgentModelAdapter = {
      async run() {
        throw new Error("agent_structured_output_invalid");
      },
    };
    const baseUrl = await start(adapter);
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify(request),
    });
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event_type: string; payload: { code?: string } });

    expect(events.at(-1)).toMatchObject({
      event_type: "run_failed",
      payload: { code: "agent_structured_output_invalid" },
    });
  });

  it("preserves provider credential failures from the internal broker", async () => {
    const adapter: AgentModelAdapter = {
      async run() {
        throw new Error("provider_credentials_missing");
      },
    };
    const baseUrl = await start(adapter);
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify(request),
    });
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event_type: string; payload: { code?: string } });

    expect(events.at(-1)).toMatchObject({
      event_type: "run_failed",
      payload: { code: "provider_credentials_missing" },
    });
  });

  it("writes a bounded diagnostic for a structured submission rejection", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const adapter: AgentModelAdapter = {
      async run() {
        throw new Error("agent_structured_output_invalid");
      },
    };
    const baseUrl = await start(adapter);
    try {
      await fetch(`${baseUrl}/internal/v1/agent-runs`, {
        method: "POST",
        headers: {
          authorization: "Bearer test-token",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          ...request,
          run_id: "arun_diagnostic",
          context: {
            ...request.context,
            user_input: "Private prompt that must not reach diagnostics.",
          },
        }),
      });

      const diagnostic = warning.mock.calls
        .map(([entry]) => String(entry))
        .find((entry) => entry.includes("agent_structured_submission_rejected"));
      expect(diagnostic).toContain("arun_diagnostic");
      expect(diagnostic).toContain("director");
      expect(diagnostic).toContain("conversation_turn");
      expect(diagnostic).toContain("agent_structured_output_invalid");
      expect(diagnostic).toContain("structured_submission");
      expect(diagnostic).not.toContain("Private prompt");
    } finally {
      warning.mockRestore();
    }
  });

  it("separates bounded runtime audit from the completed business value", async () => {
    const adapter: AgentModelAdapter = {
      async run() {
        return {
          value: "accepted",
          agent_runtime_audit: {
            provider: "OpenAI Compatible",
            model_id: "resolved-model",
            structured_attempts: 1,
          },
        };
      },
    };
    const baseUrl = await start(adapter);
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST",
      headers: {
        authorization: "Bearer test-token",
        "content-type": "application/json",
      },
      body: JSON.stringify(request),
    });
    const events = (await response.text())
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as {
        event_type: string;
        payload: Record<string, unknown>;
      });
    const completed = events.find((item) => item.event_type === "run_completed");

    expect(completed?.payload).toMatchObject({
      value: { value: "accepted" },
      audit: {
        provider: "OpenAI Compatible",
        model_id: "resolved-model",
        structured_attempts: 1,
        duration_ms: expect.any(Number),
      },
    });
  });
});
