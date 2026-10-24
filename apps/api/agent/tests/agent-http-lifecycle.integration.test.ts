import { once } from "node:events";
import { createServer, request as httpRequest, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { Agent } from "@earendil-works/pi-agent-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import { loadRuntimeManifest } from "../src/manifest.js";
import { PiModelAdapter } from "../src/pi-model-adapter.js";
import { PythonInternalClient, type AgentCredentialSnapshot } from "../src/python-internal-client.js";
import { createAgentRuntimeServer } from "../src/server.js";

const servers: Server[] = [];
const headers = { authorization: "Bearer integration-token", "content-type": "application/json" };

afterEach(async () => {
  vi.restoreAllMocks();
  await Promise.all(servers.splice(0).map(async (server) => {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }));
});

async function listen(server: Server): Promise<string> {
  servers.push(server);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

function agentRequest(runId: string): AgentRunRequest {
  return {
    protocol_version: "1",
    run_id: runId,
    request_id: `req_${runId}`,
    agent_name: "video_agent",
    operation: "execute_canvas_text",
    context_snapshot_id: `ctx_${runId}`,
    contract_digest: loadRuntimeManifest().contract_digest,
    contract_name: "AgentCanvasTextOutput",
    model_ref: "integration-model",
    model_policy_id: "video_agent.execute_canvas_text.v1",
    deadline_at: new Date(Date.now() + 10_000).toISOString(),
    context: {
      operation: "execute_canvas_text",
      conversation_id: "integration-conversation",
      user_input: "Write the selected text.",
    },
    policy: {
      operation_policy_id: "video_agent.execute_canvas_text.v1",
      operation_class: "materialization",
      timeout_seconds: 10,
      primary_timeout_seconds: 9,
      recovery_timeout_seconds: 0,
      persistence_reserve_seconds: 1,
      max_handoffs: 0,
      max_model_submissions: 1,
      max_output_tokens: 1024,
      recovery_mode: "none",
      transport_retry_limit: 0,
      structured_repair_limit: 0,
    },
  };
}

function credential(
  baseUrl: string,
  transport: "streaming_json_object" | "streamed_tool_call",
): AgentCredentialSnapshot {
  return {
    protocol_version: "1",
    source_kind: "provider",
    provider: "openai",
    model_ref: "integration-model",
    model_id: "integration-model",
    model_policy_id: "video_agent.execute_canvas_text.v1",
    base_url: baseUrl,
    api_key: "integration-key",
    supports_tool_calls: true,
    supports_strict_structured_output: true,
    supports_streaming: true,
    supports_streamed_tool_calls: true,
    supports_reasoning_controls: false,
    transport_kind: "pi_native_openai_compatible",
    adapter_id: "integration-adapter",
    capability_revision: "integration-capability-v1",
    adapter_revision: "integration-adapter-v1",
    trace_mode: "disabled",
    execution_policy: {
      model_ref: "integration-model",
      operation: "execute_canvas_text",
      operation_class: "materialization",
      thinking_format: "none",
      reasoning_control: "none",
      reasoning_mode: "low",
      enable_thinking: false,
      thinking_budget_tokens: null,
      structured_transport: transport,
      supports_tool_calls: true,
      supports_streamed_tool_calls: true,
      deadline_seconds: 10,
      primary_timeout_seconds: 9,
      recovery_timeout_seconds: 0,
      persistence_reserve_seconds: 1,
      max_model_submissions: 1,
      recovery_mode: "none",
      max_output_tokens: 1024,
      transport_retry_limit: 0,
      structured_repair_limit: 0,
    },
  };
}

function pythonClient(loadCredential: () => Promise<AgentCredentialSnapshot>): PythonInternalClient {
  return new PythonInternalClient({
    baseUrl: "http://python.internal",
    internalToken: "integration-token",
    fetchImpl: async (url, init) => {
      if (String(url).includes("/agent-runtime-config/")) {
        return Response.json(await loadCredential());
      }
      if (String(url).endsWith("/agent-model-calls")) {
        const record = JSON.parse(String(init?.body)) as { call_id: string; phase: string };
        return Response.json({ ...record, recorded: true });
      }
      throw new Error(`Unexpected Python callback: ${String(url)}`);
    },
  });
}

function observeRunResponse(server: Server): () => ServerResponse | undefined {
  let response: ServerResponse | undefined;
  server.on("request", (incoming, outgoing) => {
    if (incoming.url === "/internal/v1/agent-runs" && response === undefined) response = outgoing;
  });
  return () => response;
}

async function expectIdle(baseUrl: string): Promise<void> {
  await vi.waitFor(async () => {
    const health = await fetch(`${baseUrl}/internal/v1/health`, { headers });
    expect(await health.json()).toMatchObject({ active_runs: 0 });
  }, { timeout: 500, interval: 10 });
}

describe("real HTTP Agent lifecycle", () => {
  it("preserves an existing cancellation without loading credentials or submitting a model call", async () => {
    const loadCredential = vi.fn(async () => credential("http://127.0.0.1:1", "streamed_tool_call"));
    const adapter = new PiModelAdapter(pythonClient(loadCredential));
    const controller = new AbortController();
    const reason = new DOMException("already cancelled", "AbortError");
    controller.abort(reason);

    await expect(adapter.run(agentRequest("arun_already_cancelled"), controller.signal, async () => undefined))
      .rejects.toBe(reason);
    expect(loadCredential).not.toHaveBeenCalled();
  });

  it("preserves cancellation during the retry delay and does not start a second model prompt", async () => {
    const ready = credential("http://127.0.0.1:1", "streamed_tool_call");
    const retryPolicy = {
      primary_timeout_seconds: 8,
      recovery_timeout_seconds: 1,
      max_model_submissions: 2 as const,
      recovery_mode: "transport_retry_or_structured_repair" as const,
      transport_retry_limit: 1,
    };
    const adapter = new PiModelAdapter(pythonClient(async () => ({
      ...ready, execution_policy: { ...ready.execution_policy, ...retryPolicy },
    })));
    const controller = new AbortController();
    const reason = new DOMException("cancelled during retry delay", "AbortError");
    const prompt = vi.spyOn(Agent.prototype, "prompt").mockImplementation(async () => {
      setImmediate(() => controller.abort(reason));
      throw Object.assign(new Error("connection reset"), { code: "ECONNRESET" });
    });
    const request = agentRequest("arun_cancel_during_retry");

    await expect(adapter.run({ ...request, policy: { ...request.policy, ...retryPolicy } }, controller.signal, async () => undefined))
      .rejects.toBe(reason);
    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it("releases a real backpressured response and its listeners when a paused client disconnects", async () => {
    let calls = 0;
    const server = createAgentRuntimeServer({
      internalToken: "integration-token",
      mode: "fake",
      maxConcurrentRuns: 1,
      adapter: {
        async run() {
          calls += 1;
          return calls === 1 ? { text: "x".repeat(16 * 1024 * 1024) } : {};
        },
      },
    });
    const runResponse = observeRunResponse(server);
    const baseUrl = await listen(server);
    const outgoing = httpRequest(`${baseUrl}/internal/v1/agent-runs`, { method: "POST", headers });
    outgoing.end(JSON.stringify(agentRequest("arun_real_backpressure")));
    const [paused] = await once(outgoing, "response");
    try {
      await vi.waitFor(() => expect(runResponse()?.listenerCount("drain")).toBe(1), { timeout: 500 });
      await expectIdle(baseUrl);
      const next = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
        method: "POST", headers, body: JSON.stringify(agentRequest("arun_while_socket_paused")),
      });
      expect(next.status).toBe(200);
      expect(await next.text()).toContain("run_completed");
    } finally {
      paused.destroy();
      outgoing.destroy();
    }
    await vi.waitFor(() => {
      expect(runResponse()?.destroyed).toBe(true);
      expect(runResponse()?.listenerCount("drain")).toBe(0);
      expect(runResponse()?.listenerCount("close")).toBe(0);
      expect(runResponse()?.listenerCount("error")).toBe(0);
    }, { timeout: 500 });
    await expectIdle(baseUrl);
  });

  it("cancels the actual JSON model HTTP stream after the internal client disconnects", async () => {
    let providerResponse: ServerResponse | undefined;
    const providerUrl = await listen(createServer((_request, response) => {
      providerResponse = response;
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.write(`data: ${JSON.stringify({ choices: [{ index: 0, delta: { content: "{" } }] })}\n\n`);
    }));
    const adapter = new PiModelAdapter(pythonClient(async () => credential(providerUrl, "streaming_json_object")));
    const server = createAgentRuntimeServer({ internalToken: "integration-token", mode: "real", adapter });
    const runResponse = observeRunResponse(server);
    const baseUrl = await listen(server);
    const controller = new AbortController();
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST", headers, body: JSON.stringify(agentRequest("arun_real_model_disconnect")),
      signal: controller.signal,
    });
    await response.body!.getReader().read();
    await vi.waitFor(() => expect(providerResponse).toBeDefined(), { timeout: 500 });
    controller.abort();
    await vi.waitFor(() => expect(providerResponse?.destroyed).toBe(true), { timeout: 500 });
    await expectIdle(baseUrl);
    expect(runResponse()?.listenerCount("drain")).toBe(0);
    expect(runResponse()?.listenerCount("close")).toBe(0);
    expect(runResponse()?.listenerCount("error")).toBe(0);
  });

  it("does not submit a streamed-tool model call after cancellation during credential loading", async () => {
    let providerCalls = 0;
    const providerUrl = await listen(createServer((_request, response) => {
      providerCalls += 1;
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.end(`data: ${JSON.stringify({
        id: "cancelled-provider-call", model: "integration-model", created: 1,
        choices: [{ index: 0, delta: { role: "assistant", content: "abandoned" }, finish_reason: "stop" }],
      })}\n\ndata: [DONE]\n\n`);
    }));
    let credentialRequested!: () => void;
    const requested = new Promise<void>((resolve) => { credentialRequested = resolve; });
    let releaseCredential!: () => void;
    const pendingCredential = new Promise<void>((resolve) => { releaseCredential = resolve; });
    const adapter = new PiModelAdapter(pythonClient(async () => {
      credentialRequested();
      await pendingCredential;
      return credential(providerUrl, "streamed_tool_call");
    }));
    const server = createAgentRuntimeServer({ internalToken: "integration-token", mode: "real", adapter });
    const runResponse = observeRunResponse(server);
    const baseUrl = await listen(server);
    const controller = new AbortController();
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST", headers, body: JSON.stringify(agentRequest("arun_cancel_during_credentials")),
      signal: controller.signal,
    });
    await response.body!.getReader().read();
    await requested;
    controller.abort();
    await vi.waitFor(() => expect(runResponse()?.destroyed).toBe(true), { timeout: 500 });
    releaseCredential();
    await expectIdle(baseUrl);
    expect(providerCalls).toBe(0);
  });
});
