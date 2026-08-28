import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  openAgentCanvasPresentationStream: vi.fn(),
}));

vi.mock("../../../api/agentCanvasApi.ts", () => ({
  agentCanvasApi: api,
}));

import type { PresentationStreamEventV1 } from "../../../types-v2.ts";
import { useAgentCanvasPresentationStreams } from "./useAgentCanvasPresentationStreams.ts";

class EventSourceStub {
  static instances: EventSourceStub[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private readonly listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();

  constructor(readonly url: string) {
    EventSourceStub.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    const current = this.listeners.get(type) ?? [];
    current.push(listener as (event: MessageEvent<string>) => void);
    this.listeners.set(type, current);
  }

  close() {
    this.closed = true;
  }

  emit(eventType: string, event: PresentationStreamEventV1) {
    const message = { data: JSON.stringify(event) } as MessageEvent<string>;
    this.listeners.get(eventType)?.forEach((listener) => listener(message));
  }
}

function event(overrides: Partial<PresentationStreamEventV1> = {}): PresentationStreamEventV1 {
  return {
    schema_version: 1,
    stream_id: "stream-1",
    workflow_id: "workflow-1",
    stream_kind: "assistant",
    event_type: "delta",
    sequence_no: 1,
    turn_id: "turn-1",
    node_id: null,
    generation_id: "generation-1",
    response_locale: "en-US",
    node_revision: null,
    delta: "Hello",
    authoritative_id: null,
    content_digest: null,
    error_code: null,
    reset: null,
    ...overrides,
  };
}

describe("useAgentCanvasPresentationStreams", () => {
  beforeEach(() => {
    EventSourceStub.instances = [];
    api.openAgentCanvasPresentationStream.mockImplementation((workflowId: string, streamId: string, afterSeq: number) => (
      new EventSourceStub(`/api/v2/workflows/${workflowId}/presentation/streams/${streamId}?after_seq=${afterSeq}`)
    ));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("assembles deltas once and keeps the stream cursor monotonic", async () => {
    const { result } = renderHook(() => useAgentCanvasPresentationStreams("workflow-1", ["stream-1"]));
    await waitFor(() => expect(EventSourceStub.instances).toHaveLength(1));
    const stream = EventSourceStub.instances[0]!;

    act(() => {
      stream.onopen?.();
      stream.emit("delta", event());
      stream.emit("delta", event());
      stream.emit("delta", event({ sequence_no: 2, delta: " world" }));
    });

    expect(result.current["stream-1"]).toMatchObject({
      status: "open",
      text: "Hello world",
      last_sequence_no: 2,
    });
  });

  it("reopens a failed connection from the last stream sequence", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useAgentCanvasPresentationStreams("workflow-1", ["stream-1"]));
    await act(async () => { await Promise.resolve(); });
    const first = EventSourceStub.instances[0]!;
    act(() => {
      first.emit("delta", event({ sequence_no: 4, delta: "Saved" }));
      first.onerror?.();
    });
    expect(result.current["stream-1"]?.status).toBe("reconnecting");
    act(() => { vi.advanceTimersByTime(1_000); });
    expect(api.openAgentCanvasPresentationStream).toHaveBeenLastCalledWith("workflow-1", "stream-1", 4);
  });

  it("clears the local buffer when the backend resets the presentation cursor", async () => {
    const { result } = renderHook(() => useAgentCanvasPresentationStreams("workflow-1", ["stream-1"]));
    await waitFor(() => expect(EventSourceStub.instances).toHaveLength(1));
    const stream = EventSourceStub.instances[0]!;

    act(() => {
      stream.emit("delta", event({ sequence_no: 1, delta: "Old response" }));
      stream.emit("reset", event({
        sequence_no: 2,
        event_type: "reset",
        delta: null,
        reset: {
          reason: "store_recovered",
          authoritative_id: "message-2",
          resource_kind: "message",
        },
      }));
      stream.emit("delta", event({ sequence_no: 3, delta: "New response" }));
    });

    expect(result.current["stream-1"]).toMatchObject({
      text: "New response",
      last_sequence_no: 3,
      last_event_type: "delta",
    });
  });
});
