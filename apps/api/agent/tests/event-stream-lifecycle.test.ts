import { EventEmitter } from "node:events";

import { describe, expect, it } from "vitest";

import { EventBuffer, type EventStreamWriter } from "../src/event-buffer.js";
import type { AgentRuntimeEvent } from "../src/generated/agent-runtime.js";
import { aggregateStreamingJsonCompletion } from "../src/pi-structured-transport.js";

class PausedWriter extends EventEmitter implements EventStreamWriter {
  readonly chunks: string[] = [];
  destroyed = false;
  paused = true;

  write(chunk: string): boolean {
    this.chunks.push(chunk);
    return !this.paused;
  }
}

function runtimeEvent(eventType: AgentRuntimeEvent["event_type"]): AgentRuntimeEvent {
  return {
    protocol_version: "1",
    seq: 0,
    run_id: "arun_lifecycle",
    agent_name: "video_agent",
    event_type: eventType,
    created_at: new Date().toISOString(),
    payload: {},
  };
}

async function settles(promise: Promise<unknown>): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("stream cleanup did not settle")), 100);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

describe("event stream lifecycle", () => {
  it.each(["close", "error"] as const)(
    "releases backpressure and discards undeliverable events on writer %s",
    async (eventName) => {
      const writer = new PausedWriter();
      // An independent observer also receives writer errors.
      writer.on("error", () => undefined);
      const buffer = new EventBuffer(writer, 4096);
      buffer.enqueue(runtimeEvent("run_started"));
      buffer.enqueue(runtimeEvent("heartbeat"));
      const flushing = buffer.flush();
      const closing = buffer.close();
      writer.destroyed = true;
      writer.emit(eventName, new Error("socket lost"));
      try {
        await settles(Promise.all([flushing, closing]));
        expect(buffer.enqueue(runtimeEvent("heartbeat"))).toBe(false);
        expect(writer.chunks).toHaveLength(1);
        expect(writer.listenerCount("drain")).toBe(0);
      } finally {
        writer.paused = false;
        writer.emit("drain");
      }
    },
  );

  it("settles cleanup after a synchronous write failure", async () => {
    const writer = new PausedWriter();
    writer.write = () => { throw new Error("socket write failed"); };
    const buffer = new EventBuffer(writer, 4096);
    buffer.enqueue(runtimeEvent("run_started"));

    await settles(buffer.close());
    expect(buffer.enqueue(runtimeEvent("heartbeat"))).toBe(false);
  });

  it("does not write to a writer that was already destroyed", async () => {
    const writer = new PausedWriter();
    writer.destroyed = true;
    const buffer = new EventBuffer(writer, 4096);

    expect(buffer.enqueue(runtimeEvent("run_started"))).toBe(false);
    await settles(buffer.close());
    expect(writer.chunks).toEqual([]);
  });

  it("keeps ordering and removes lifecycle listeners after a normal drain", async () => {
    const writer = new PausedWriter();
    const buffer = new EventBuffer(writer, 4096);
    buffer.enqueue(runtimeEvent("run_started"));
    buffer.enqueueTerminal(runtimeEvent("run_completed"));
    writer.paused = false;
    writer.emit("drain");
    await settles(buffer.close());

    expect(writer.chunks.map((chunk) => JSON.parse(chunk).seq)).toEqual([1, 2]);
    expect(writer.listenerCount("drain")).toBe(0);
    expect(writer.listenerCount("close")).toBe(0);
    expect(writer.listenerCount("error")).toBe(0);
  });

  it("returns cancellation before a pending async generator can finish closing", async () => {
    let started!: () => void;
    const nextStarted = new Promise<void>((resolve) => { started = resolve; });
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    const stream = {
      async *[Symbol.asyncIterator]() {
        started();
        await pending;
        yield { choices: [{ delta: { content: "{}" }, finish_reason: "stop" }] };
      },
    };
    const controller = new AbortController();
    const result = aggregateStreamingJsonCompletion(stream, {
      signal: controller.signal,
      maxOutputBytes: 4096,
    });
    // Attach the rejection observer before aborting to avoid an unhandled rejection.
    const rejected = expect(result).rejects.toMatchObject({ name: "AbortError" });
    await nextStarted;
    controller.abort(new DOMException("cancelled", "AbortError"));
    try {
      await settles(rejected);
    } finally {
      release();
      await result.catch(() => undefined);
    }
  });

  it("preserves cancellation when iterator cleanup rejects", async () => {
    let release!: (value: IteratorResult<unknown>) => void;
    const pending = new Promise<IteratorResult<unknown>>((resolve) => { release = resolve; });
    const stream: AsyncIterable<unknown> = {
      [Symbol.asyncIterator]() {
        return {
          next: () => pending,
          return: async () => { throw new Error("cleanup failed"); },
        };
      },
    };
    const controller = new AbortController();
    const result = aggregateStreamingJsonCompletion(stream, {
      signal: controller.signal,
      maxOutputBytes: 4096,
    });
    const rejected = expect(result).rejects.toMatchObject({ name: "AbortError" });
    controller.abort(new DOMException("cancelled", "AbortError"));
    await settles(rejected);
    release({ done: true, value: undefined });
    await new Promise<void>((resolve) => setImmediate(resolve));
  });
});
