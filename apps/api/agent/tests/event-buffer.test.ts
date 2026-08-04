import { EventEmitter } from "node:events";

import { describe, expect, it } from "vitest";

import {
  EventBuffer,
  EventBufferOverflow,
  type EventStreamWriter,
} from "../src/event-buffer.js";
import type { AgentRuntimeEvent } from "../src/generated/agent-runtime.js";

class FakeWriter extends EventEmitter implements EventStreamWriter {
  readonly chunks: string[] = [];
  paused = false;

  write(chunk: string): boolean {
    this.chunks.push(chunk);
    return !this.paused;
  }

  release(): void {
    this.paused = false;
    this.emit("drain");
  }
}

function runtimeEvent(
  eventType: AgentRuntimeEvent["event_type"],
  payload: Record<string, unknown> = {},
): AgentRuntimeEvent {
  return {
    protocol_version: "1",
    seq: 0,
    run_id: "arun_buffer",
    agent_name: "director",
    event_type: eventType,
    created_at: "2026-07-24T12:00:00Z",
    payload,
  };
}

function decoded(writer: FakeWriter): AgentRuntimeEvent[] {
  return writer.chunks.flatMap((chunk) =>
    chunk
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as AgentRuntimeEvent),
  );
}

describe("EventBuffer", () => {
  it("flushes events in sequence through one writer", async () => {
    const writer = new FakeWriter();
    const buffer = new EventBuffer(writer, 4096);

    buffer.enqueue(runtimeEvent("run_started"));
    buffer.enqueue(runtimeEvent("tool_call", { tool: "lookup" }));
    buffer.enqueue(runtimeEvent("run_completed", { value: {} }));
    await buffer.close();

    expect(decoded(writer).map((event) => [event.seq, event.event_type])).toEqual([
      [1, "run_started"],
      [2, "tool_call"],
      [3, "run_completed"],
    ]);
  });

  it("coalesces adjacent queued output deltas", async () => {
    const writer = new FakeWriter();
    writer.paused = true;
    const buffer = new EventBuffer(writer, 4096);

    buffer.enqueue(runtimeEvent("run_started"));
    buffer.enqueue(runtimeEvent("output_delta", { text: "alpha" }));
    buffer.enqueue(runtimeEvent("output_delta", { text: "-beta" }));
    buffer.enqueue(runtimeEvent("run_completed", { value: {} }));
    writer.release();
    await buffer.close();

    expect(decoded(writer)).toEqual([
      expect.objectContaining({ seq: 1, event_type: "run_started" }),
      expect.objectContaining({
        seq: 2,
        event_type: "output_delta",
        payload: { text: "alpha-beta" },
      }),
      expect.objectContaining({ seq: 3, event_type: "run_completed" }),
    ]);
  });

  it("waits for drain before writing later events", async () => {
    const writer = new FakeWriter();
    writer.paused = true;
    const buffer = new EventBuffer(writer, 4096);

    buffer.enqueue(runtimeEvent("run_started"));
    buffer.enqueue(runtimeEvent("tool_result", { tool: "lookup" }));
    buffer.enqueue(runtimeEvent("heartbeat"));
    await new Promise((resolve) => setImmediate(resolve));

    expect(decoded(writer).map((event) => event.event_type)).toEqual(["run_started"]);
    writer.release();
    await buffer.flush();
    expect(decoded(writer).map((event) => event.event_type)).toEqual([
      "run_started",
      "tool_result",
      "heartbeat",
    ]);
  });

  it("reports overflow without dropping mandatory events", async () => {
    const writer = new FakeWriter();
    writer.paused = true;
    const buffer = new EventBuffer(writer, 320);

    buffer.enqueue(runtimeEvent("run_started", { state: "x".repeat(80) }));
    expect(() =>
      buffer.enqueue(runtimeEvent("tool_result", { value: "y".repeat(160) })),
    ).toThrow(EventBufferOverflow);
    buffer.enqueueTerminal(
      runtimeEvent("run_failed", {
        code: "agent_stream_backpressure_exceeded",
        message: "Agent event stream exceeded its bounded queue.",
      }),
    );
    writer.release();
    await buffer.close();

    expect(decoded(writer).map((event) => event.event_type)).toEqual([
      "run_started",
      "run_failed",
    ]);
  });

  it("rejects writes after the terminal event", async () => {
    const writer = new FakeWriter();
    const buffer = new EventBuffer(writer, 4096);

    buffer.enqueue(runtimeEvent("run_completed", { value: {} }));
    expect(buffer.enqueue(runtimeEvent("heartbeat"))).toBe(false);
    await buffer.close();

    expect(decoded(writer)).toHaveLength(1);
  });
});
