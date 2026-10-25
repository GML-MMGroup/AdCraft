import { getEventListeners, once } from "node:events";
import { createServer, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  executeOpenAICompletion,
  type StreamingJsonCompletionRequest,
} from "../src/pi-structured-transport.js";

const servers: Server[] = [];
const request: StreamingJsonCompletionRequest = {
  model: "local-test-model",
  messages: [{ role: "user", content: "Return one JSON object." }],
  max_tokens: 128,
  stream: true,
  response_format: { type: "json_object" },
};

afterEach(async () => {
  await Promise.all(servers.splice(0).map(async (server) => {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }));
});

function chunk(content: string | null, finishReason: "stop" | null = null): string {
  return `data: ${JSON.stringify({
    choices: [{ index: 0, delta: { content }, finish_reason: finishReason }],
  })}\n\n`;
}

async function provider(handle: (response: ServerResponse) => void): Promise<string> {
  const server = createServer((_incoming, response) => {
    response.writeHead(200, { "content-type": "text/event-stream" });
    handle(response);
  });
  servers.push(server);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

describe("streaming JSON HTTP cleanup", () => {
  it("closes the provider response when its content stream stalls", async () => {
    let response: ServerResponse | undefined;
    const baseUrl = await provider((outgoing) => {
      response = outgoing;
      outgoing.write(chunk("{"));
      // Keep the real HTTP response open without sending another token.
    });
    const caller = new AbortController();

    await expect(executeOpenAICompletion(request, {
      apiKey: "local-test-key",
      baseUrl,
      signal: caller.signal,
      timeoutMs: 2_000,
      idleTimeoutMs: 30,
    })).rejects.toMatchObject({ code: "agent_provider_timeout", stall_detected: true });

    await vi.waitFor(() => expect(response?.destroyed).toBe(true), { timeout: 500 });
    expect(caller.signal.aborted).toBe(false);
    expect(getEventListeners(caller.signal, "abort")).toHaveLength(0);
  });

  it("returns a complete JSON result without cancelling the caller", async () => {
    const baseUrl = await provider((response) => {
      response.write(chunk('{"text":"complete"}'));
      response.write(chunk(null, "stop"));
      response.end("data: [DONE]\n\n");
    });
    const caller = new AbortController();

    const result = await executeOpenAICompletion(request, {
      apiKey: "local-test-key",
      baseUrl,
      signal: caller.signal,
      timeoutMs: 2_000,
      idleTimeoutMs: 500,
    });

    expect(result.choices?.[0]?.message?.content).toBe('{"text":"complete"}');
    expect(result.choices?.[0]?.finish_reason).toBe("stop");
    expect(caller.signal.aborted).toBe(false);
    expect(getEventListeners(caller.signal, "abort")).toHaveLength(0);
  });

  it("closes the provider response and preserves caller cancellation", async () => {
    let response: ServerResponse | undefined;
    const baseUrl = await provider((outgoing) => {
      response = outgoing;
      outgoing.write(chunk("{"));
    });
    let receivedChunk!: () => void;
    const received = new Promise<void>((resolve) => { receivedChunk = resolve; });
    const caller = new AbortController();
    const reason = new DOMException("cancel the model request", "AbortError");
    const completion = executeOpenAICompletion(request, {
      apiKey: "local-test-key",
      baseUrl,
      signal: caller.signal,
      timeoutMs: 2_000,
      idleTimeoutMs: 1_000,
      onChunk: receivedChunk,
    });
    const cancelled = expect(completion).rejects.toBe(reason);
    await received;
    caller.abort(reason);
    await cancelled;

    await vi.waitFor(() => expect(response?.destroyed).toBe(true), { timeout: 500 });
    expect(getEventListeners(caller.signal, "abort")).toHaveLength(0);
  });
});
