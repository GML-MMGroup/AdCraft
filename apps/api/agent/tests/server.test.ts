import { once } from "node:events";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";

import { createAgentRuntimeServer } from "../src/server.js";
import type { AgentModelAdapter, EventSink } from "../src/runtime.js";
import type { AgentRunRequest } from "../src/generated/agent-runtime.js";

const servers: Array<ReturnType<typeof createAgentRuntimeServer>> = [];

const request: AgentRunRequest = {
  protocol_version: "1",
  run_id: "arun_test",
  request_id: "req_test",
  agent_name: "front_desk",
  operation: "workflow_creation",
  deadline_at: new Date(Date.now() + 5 * 60_000).toISOString(),
  model_policy_id: "front_desk.workflow_creation.v1",
  context: {
    operation: "workflow_creation",
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

  it("fails with one terminal event when the event byte budget is exceeded", async () => {
    const adapter: AgentModelAdapter = {
      async run(_request: AgentRunRequest, _signal: AbortSignal, emit: EventSink) {
        await emit({
          protocol_version: "1",
          seq: 0,
          run_id: "arun_test",
          agent_name: "front_desk",
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
          agent_name: "front_desk",
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
