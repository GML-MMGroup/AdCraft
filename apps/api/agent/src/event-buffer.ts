import type { AgentRuntimeEvent } from "./generated/agent-runtime.js";

export interface EventStreamWriter {
  write(chunk: string): boolean;
  once(event: "drain", listener: () => void): unknown;
}

interface BufferedEvent {
  event: AgentRuntimeEvent;
  encoded: string;
  bytes: number;
}

const terminalEventTypes = new Set([
  "run_completed",
  "run_failed",
  "run_cancelled",
]);

export class EventBufferOverflow extends Error {
  readonly code = "agent_stream_backpressure_exceeded";

  constructor() {
    super("Agent event stream exceeded its bounded queue.");
  }
}

export class EventBuffer {
  readonly #writer: EventStreamWriter;
  readonly #maximumBytes: number;
  readonly #queue: BufferedEvent[] = [];
  readonly #flushWaiters: Array<() => void> = [];
  #bufferedBytes = 0;
  #nextSequence = 1;
  #writing = false;
  #terminalEnqueued = false;
  #closed = false;

  constructor(writer: EventStreamWriter, maximumBytes: number) {
    if (!Number.isInteger(maximumBytes) || maximumBytes <= 0) {
      throw new Error("Event buffer maximum bytes must be positive.");
    }
    this.#writer = writer;
    this.#maximumBytes = maximumBytes;
  }

  enqueue(candidate: AgentRuntimeEvent): boolean {
    if (this.#closed || this.#terminalEnqueued) return false;
    if (candidate.event_type === "output_delta" && this.#coalesce(candidate)) {
      return true;
    }
    this.#append(candidate, false);
    return true;
  }

  enqueueTerminal(candidate: AgentRuntimeEvent): boolean {
    if (this.#closed || this.#terminalEnqueued) return false;
    if (!terminalEventTypes.has(candidate.event_type)) {
      throw new Error("Only terminal events may bypass the event buffer limit.");
    }
    this.#append(candidate, true);
    return true;
  }

  async flush(): Promise<void> {
    if (!this.#writing && this.#queue.length === 0) return;
    await new Promise<void>((resolve) => this.#flushWaiters.push(resolve));
  }

  async close(): Promise<void> {
    this.#closed = true;
    await this.flush();
  }

  #append(candidate: AgentRuntimeEvent, allowTerminalOverflow: boolean): void {
    const event = { ...candidate, seq: this.#nextSequence };
    const entry = encode(event);
    if (
      !allowTerminalOverflow &&
      this.#bufferedBytes + entry.bytes > this.#maximumBytes
    ) {
      throw new EventBufferOverflow();
    }
    this.#nextSequence += 1;
    this.#bufferedBytes += entry.bytes;
    this.#queue.push(entry);
    if (terminalEventTypes.has(event.event_type)) this.#terminalEnqueued = true;
    this.#startWriter();
  }

  #coalesce(candidate: AgentRuntimeEvent): boolean {
    const previous = this.#queue.at(-1);
    const previousText = previous?.event.payload?.text;
    const nextText = candidate.payload?.text;
    if (
      !previous ||
      previous.event.event_type !== "output_delta" ||
      previous.event.run_id !== candidate.run_id ||
      typeof previousText !== "string" ||
      typeof nextText !== "string"
    ) {
      return false;
    }
    const merged = encode({
      ...previous.event,
      payload: { ...previous.event.payload, text: `${previousText}${nextText}` },
    });
    const nextBytes = this.#bufferedBytes - previous.bytes + merged.bytes;
    if (nextBytes > this.#maximumBytes) throw new EventBufferOverflow();
    this.#bufferedBytes = nextBytes;
    this.#queue[this.#queue.length - 1] = merged;
    return true;
  }

  #startWriter(): void {
    if (this.#writing) return;
    this.#writing = true;
    void this.#drain();
  }

  async #drain(): Promise<void> {
    while (this.#queue.length > 0) {
      const entry = this.#queue.shift();
      if (!entry) break;
      const accepted = this.#writer.write(entry.encoded);
      if (!accepted) {
        await new Promise<void>((resolve) => this.#writer.once("drain", resolve));
      }
      this.#bufferedBytes -= entry.bytes;
    }
    this.#writing = false;
    for (const resolve of this.#flushWaiters.splice(0)) resolve();
    if (this.#queue.length > 0) this.#startWriter();
  }
}

function encode(event: AgentRuntimeEvent): BufferedEvent {
  const encoded = `${JSON.stringify(event)}\n`;
  return {
    event,
    encoded,
    bytes: Buffer.byteLength(encoded),
  };
}
