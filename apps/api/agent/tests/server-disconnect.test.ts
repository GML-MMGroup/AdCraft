import { once } from "node:events";
import { ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentRunRequest } from "../src/generated/agent-runtime.js";
import { loadRuntimeManifest } from "../src/manifest.js";
import type { AgentModelAdapter } from "../src/runtime.js";
import { createAgentRuntimeServer } from "../src/server.js";

const servers: Array<ReturnType<typeof createAgentRuntimeServer>> = [];
const headers = { authorization: "Bearer lifecycle-token", "content-type": "application/json" };

afterEach(async () => {
  await Promise.all(servers.splice(0).map(async (server) => {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }));
});

function request(runId: string): AgentRunRequest {
  return {
    protocol_version: "1",
    run_id: runId,
    request_id: `req_${runId}`,
    agent_name: "video_agent",
    operation: "execute_canvas_text",
    context_snapshot_id: `ctx_${runId}`,
    contract_digest: loadRuntimeManifest().contract_digest,
    contract_name: "AgentCanvasTextOutput",
    deadline_at: new Date(Date.now() + 10_000).toISOString(),
    model_policy_id: "video_agent.execute_canvas_text.v1",
    context: {
      operation: "execute_canvas_text",
      conversation_id: "conversation_lifecycle",
      user_input: "Write the selected text.",
    },
    policy: { timeout_seconds: 10, max_handoffs: 0 },
  };
}

async function start(adapter: AgentModelAdapter): Promise<string> {
  const server = createAgentRuntimeServer({
    internalToken: "lifecycle-token",
    mode: "fake",
    adapter,
    maxConcurrentRuns: 1,
  });
  servers.push(server);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

describe("runtime response lifecycle", () => {
  it("aborts abandoned runs and releases their concurrency and conversation slots", async () => {
    let adapterSignal: AbortSignal | undefined;
    let calls = 0;
    const baseUrl = await start({
      async run(_request, signal) {
        calls += 1;
        if (calls > 1) return {};
        adapterSignal = signal;
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        });
        return {};
      },
    });
    const controller = new AbortController();
    const abandoned = request("arun_disconnected");
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST", headers, body: JSON.stringify(abandoned), signal: controller.signal,
    });
    expect(response.status).toBe(200);
    await response.body!.getReader().read();
    controller.abort();
    try {
      await vi.waitFor(() => expect(adapterSignal?.aborted).toBe(true), { timeout: 300 });
      await vi.waitFor(async () => {
        const health = await fetch(`${baseUrl}/internal/v1/health`, { headers });
        expect(await health.json()).toMatchObject({ active_runs: 0 });
      }, { timeout: 300 });
      const next = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
        method: "POST", headers, body: JSON.stringify(request("arun_after_disconnect")),
      });
      expect(next.status).toBe(200);
      expect(await next.text()).toContain("run_completed");
    } finally {
      await fetch(`${baseUrl}/internal/v1/agent-runs/${abandoned.run_id}/cancel`, {
        method: "POST", headers,
      });
    }
  });

  it("does not cancel a successfully completed response", async () => {
    let adapterSignal: AbortSignal | undefined;
    const baseUrl = await start({
      async run(_request, signal) {
        adapterSignal = signal;
        return { text: "completed" };
      },
    });
    const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
      method: "POST", headers, body: JSON.stringify(request("arun_normal_finish")),
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toContain("run_completed");
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(adapterSignal?.aborted).toBe(false);
  });

  it("releases completed model and conversation slots while the terminal response is backpressured", async () => {
    let terminalWritten!: () => void;
    const terminalPending = new Promise<void>((resolve) => { terminalWritten = resolve; });
    let blockedResponse: ServerResponse | undefined;
    const originalWrite = ServerResponse.prototype.write;
    const write = vi.spyOn(ServerResponse.prototype, "write").mockImplementation(
      function (this: ServerResponse, chunk: unknown, ...args: unknown[]) {
        if (
          blockedResponse === undefined &&
          typeof chunk === "string" &&
          chunk.includes('"event_type":"run_completed"')
        ) {
          // Keep a connected sink under backpressure without relying on OS socket sizes.
          blockedResponse = this;
          terminalWritten();
          return false;
        }
        return Reflect.apply(originalWrite, this, [chunk, ...args]) as boolean;
      },
    );
    const baseUrl = await start({ async run() { return {}; } });
    try {
      const response = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
        method: "POST", headers, body: JSON.stringify(request("arun_slow_terminal")),
      });
      expect(response.status).toBe(200);
      await terminalPending;
      const health = await fetch(`${baseUrl}/internal/v1/health`, { headers });
      expect(await health.json()).toMatchObject({ active_runs: 0 });

      const next = await fetch(`${baseUrl}/internal/v1/agent-runs`, {
        method: "POST", headers, body: JSON.stringify(request("arun_during_final_drain")),
      });
      expect(next.status).toBe(200);
      expect(await next.text()).toContain("run_completed");
    } finally {
      blockedResponse?.destroy();
      write.mockRestore();
    }
  });
});
