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

  it("does not reopen an ended stream when another stream joins", async () => {
    const { result, rerender } = renderHook(
      ({ ids }: { ids: string[] }) => useAgentCanvasPresentationStreams("workflow-1", ids),
      { initialProps: { ids: ["stream-1"] } },
    );
    await waitFor(() => expect(EventSourceStub.instances).toHaveLength(1));
    act(() => {
      EventSourceStub.instances[0]!.emit("delta", event());
      EventSourceStub.instances[0]!.emit("committed", event({ event_type: "committed", sequence_no: 2, delta: null, authoritative_id: "msg-1", content_digest: "a".repeat(64) }));
    });
    expect(result.current["stream-1"]?.status).toBe("completed");

    rerender({ ids: ["stream-1", "stream-2"] });
    await waitFor(() => expect(EventSourceStub.instances).toHaveLength(2));

    expect(EventSourceStub.instances[1]!.url).toContain("/streams/stream-2?");
    expect(result.current["stream-1"]).toMatchObject({ status: "completed", text: "Hello" });
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

  it.each([
    ["committed", "completed"],
    ["failed", "failed"],
    ["superseded", "superseded"],
  ] as const)("keeps a %s stream finished when another stream is added or removed", (eventType, status) => {
    const { result, rerender } = renderHook(
      ({ streamIds }) => useAgentCanvasPresentationStreams("workflow-1", streamIds),
      { initialProps: { streamIds: ["stream-1"] } },
    );
    const first = EventSourceStub.instances[0]!;
    act(() => {
      first.emit("delta", event());
      first.emit(eventType, event({
        sequence_no: 2,
        event_type: eventType,
        delta: null,
        authoritative_id: eventType === "committed" ? "message-1" : null,
        content_digest: eventType === "committed" ? "a".repeat(64) : null,
        error_code: eventType === "failed" ? "generation_failed" : null,
      }));
    });
    const finishedView = result.current["stream-1"];
    expect(finishedView).toMatchObject({ status, text: "Hello", last_sequence_no: 2 });
    expect(first.closed).toBe(true);

    rerender({ streamIds: ["stream-1", "stream-2"] });

    expect(EventSourceStub.instances).toHaveLength(2);
    expect(EventSourceStub.instances[1]?.url).toContain("/stream-2?after_seq=0");
    expect(result.current["stream-1"]).toBe(finishedView);

    rerender({ streamIds: ["stream-1"] });

    expect(EventSourceStub.instances).toHaveLength(2);
    expect(EventSourceStub.instances[1]?.closed).toBe(true);
    expect(result.current["stream-1"]).toBe(finishedView);
  });

  it("resumes an unfinished stream from its cursor when another stream is added", () => {
    const { result, rerender } = renderHook(
      ({ streamIds }) => useAgentCanvasPresentationStreams("workflow-1", streamIds),
      { initialProps: { streamIds: ["stream-1"] } },
    );
    const first = EventSourceStub.instances[0]!;
    act(() => first.emit("delta", event({ sequence_no: 4, delta: "Saved" })));

    rerender({ streamIds: ["stream-1", "stream-2"] });

    expect(first.closed).toBe(true);
    expect(EventSourceStub.instances).toHaveLength(3);
    const resumed = EventSourceStub.instances[1]!;
    expect(resumed.url).toContain("/stream-1?after_seq=4");
    act(() => resumed.emit("delta", event({ sequence_no: 5, delta: " response" })));
    expect(result.current["stream-1"]).toMatchObject({
      status: "open", text: "Saved response", last_sequence_no: 5,
    });
  });

  it("starts a fresh stream in a different workflow after the old stream finished", () => {
    const { result, rerender } = renderHook(
      ({ workflowId }) => useAgentCanvasPresentationStreams(workflowId, ["stream-1"]),
      { initialProps: { workflowId: "workflow-1" } },
    );
    act(() => {
      EventSourceStub.instances[0]!.emit("delta", event());
      EventSourceStub.instances[0]!.emit("committed", event({
        sequence_no: 2, event_type: "committed", delta: null,
        authoritative_id: "message-1", content_digest: "a".repeat(64),
      }));
    });

    rerender({ workflowId: "workflow-2" });

    expect(EventSourceStub.instances).toHaveLength(2);
    const next = EventSourceStub.instances[1]!;
    expect(next.url).toContain("/workflows/workflow-2/presentation/streams/stream-1?after_seq=0");
    expect(result.current["stream-1"]).toMatchObject({
      status: "connecting", text: "", last_sequence_no: 0, last_event_type: null,
    });
    act(() => next.emit("delta", event({ workflow_id: "workflow-2", delta: "New workflow" })));
    expect(result.current["stream-1"]?.text).toBe("New workflow");
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
