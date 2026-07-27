import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { v2Api } from "../../../api/v2Client.ts";
import { normalizeWorkflowRuntimeV2 } from "../../../api/v2Normalizers.ts";
import { useV2RuntimeController } from "./useV2RuntimeController.ts";

type EventListener = (event: Event) => void;

class TestEventSource {
  static instances: TestEventSource[] = [];

  onopen: (() => void) | null = null;
  onmessage: EventListener | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private readonly listeners = new Map<string, EventListener>();

  constructor(readonly workflowId: string) {
    TestEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener);
  }

  close() {
    this.closed = true;
  }

  emit(event: Record<string, unknown>, type = "message") {
    const message = { data: JSON.stringify(event) } as MessageEvent;
    if (type === "message") this.onmessage?.(message);
    else this.listeners.get(type)?.(message);
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  cleanup();
  TestEventSource.instances = [];
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("useV2RuntimeController", () => {
  it("resets workflow-scoped runtime state before B transport when B snapshot fails", async () => {
    vi.useFakeTimers();
    vi.spyOn(v2Api, "runtime")
      .mockResolvedValueOnce(normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-a",
        events_cursor: 100,
        active_execution_id: "execution-a",
        execution_status: "running",
        running_slot_ids: ["slot-a"],
      }))
      .mockRejectedValueOnce(new Error("B snapshot unavailable"));
    vi.spyOn(v2Api, "openEventStream").mockImplementation((workflowId) => new TestEventSource(workflowId) as unknown as EventSource);

    const { result, rerender } = renderHook(
      ({ workflowId }) => useV2RuntimeController({ workflowId }),
      { initialProps: { workflowId: "workflow-a" } },
    );
    await flushPromises();
    expect(result.current.store.lastEventSeq).toBe(100);
    expect(result.current.store.runningSlotIds).toEqual(["slot-a"]);

    rerender({ workflowId: "workflow-b" });
    await flushPromises();
    expect(result.current.store.lastEventSeq).toBe(0);
    expect(result.current.store.activeExecutionId).toBeNull();
    expect(result.current.store.runningSlotIds).toEqual([]);
    expect(TestEventSource.instances.at(-1)?.workflowId).toBe("workflow-b");

    await act(async () => {
      TestEventSource.instances.at(-1)?.emit({
        seq: 1,
        event_type: "execution_started",
        workflow_id: "workflow-b",
        payload: { execution_id: "execution-b" },
      });
      await vi.advanceTimersByTimeAsync(16);
    });

    expect(result.current.store.lastEventSeq).toBe(1);
    expect(result.current.store.activeExecutionId).toBe("execution-b");
    expect(result.current.store.runningSlotIds).toEqual([]);
  });

  it("does not open a stream after an unmounted snapshot request settles", async () => {
    const snapshot = deferred<ReturnType<typeof normalizeWorkflowRuntimeV2>>();
    vi.spyOn(v2Api, "runtime").mockReturnValue(snapshot.promise);
    const openEventStream = vi.spyOn(v2Api, "openEventStream").mockImplementation((workflowId) => new TestEventSource(workflowId) as unknown as EventSource);

    const { unmount } = renderHook(() => useV2RuntimeController({ workflowId: "workflow-a" }));
    unmount();
    snapshot.resolve(normalizeWorkflowRuntimeV2({ workflow_id: "workflow-a", events_cursor: 1 }));
    await flushPromises();

    expect(openEventStream).not.toHaveBeenCalled();
    expect(TestEventSource.instances).toEqual([]);
  });

  it("serializes eligibility recovery after an in-flight fallback poll", async () => {
    vi.useFakeTimers();
    let online = true;
    vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
    vi.spyOn(v2Api, "runtime").mockResolvedValue(
      normalizeWorkflowRuntimeV2({ workflow_id: "workflow-a", events_cursor: 0 }),
    );
    const poll = deferred<Awaited<ReturnType<typeof v2Api.events>>>();
    vi.spyOn(v2Api, "events").mockReturnValue(poll.promise);
    const openEventStream = vi.spyOn(v2Api, "openEventStream")
      .mockImplementation((workflowId) => new TestEventSource(workflowId) as unknown as EventSource);
    const onEvents = vi.fn();

    const { result } = renderHook(() => useV2RuntimeController({
      workflowId: "workflow-a",
      onEvents,
    }));
    await flushPromises();

    for (let failure = 0; failure < 3; failure += 1) {
      act(() => {
        TestEventSource.instances.at(-1)?.onerror?.();
      });
      await act(async () => {
        await vi.runOnlyPendingTimersAsync();
      });
    }
    act(() => {
      TestEventSource.instances.at(-1)?.onerror?.();
    });
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });

    expect(openEventStream).toHaveBeenCalledTimes(4);
    expect(v2Api.events).toHaveBeenCalledTimes(1);

    act(() => {
      online = false;
      window.dispatchEvent(new Event("offline"));
      online = true;
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("online"));
    });

    expect(openEventStream).toHaveBeenCalledTimes(4);
    expect(onEvents).not.toHaveBeenCalled();

    poll.resolve({
      events: [{
        seq: 1,
        event_type: "execution_started",
        workflow_id: "workflow-a",
        payload: { execution_id: "execution-a" },
      }],
      next_after_seq: 1,
    });
    await flushPromises();
    await flushPromises();

    expect(onEvents).toHaveBeenCalledTimes(1);
    expect(result.current.store.activeExecutionId).toBe("execution-a");
    expect(openEventStream).toHaveBeenCalledTimes(5);
    expect(openEventStream).toHaveBeenLastCalledWith("workflow-a", 1);
    expect(vi.getTimerCount()).toBe(0);

    act(() => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("online"));
      TestEventSource.instances.at(-1)?.onopen?.();
    });

    expect(openEventStream).toHaveBeenCalledTimes(5);
    expect(onEvents).toHaveBeenCalledTimes(1);
    expect(result.current.connectionState).toBe("connected");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("hands connected SSE ownership to direct synchronization without duplicate side effects", async () => {
    vi.useFakeTimers();
    vi.spyOn(v2Api, "runtime").mockResolvedValue(
      normalizeWorkflowRuntimeV2({ workflow_id: "workflow-a", events_cursor: 0 }),
    );
    const terminalEvent = {
      seq: 11,
      event_type: "execution_completed",
      workflow_id: "workflow-a",
      payload: { execution_id: "execution-a", status: "completed" },
    };
    const streamClosedWhenPolling: boolean[] = [];
    const events = vi.spyOn(v2Api, "events").mockImplementation(async () => {
      streamClosedWhenPolling.push(TestEventSource.instances.at(-1)?.closed ?? false);
      return {
        events: [],
        next_after_seq: 11,
      };
    });
    const openEventStream = vi.spyOn(v2Api, "openEventStream")
      .mockImplementation((workflowId) => new TestEventSource(workflowId) as unknown as EventSource);
    const onEvents = vi.fn();

    const { result } = renderHook(() => useV2RuntimeController({
      workflowId: "workflow-a",
      onEvents,
    }));
    await flushPromises();

    act(() => {
      TestEventSource.instances.at(-1)?.onopen?.();
      TestEventSource.instances.at(-1)?.emit(terminalEvent);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16);
    });
    await act(async () => {
      await result.current.syncEvents("workflow-a");
    });

    expect(events).toHaveBeenCalledTimes(1);
    expect(events).toHaveBeenLastCalledWith("workflow-a", 11, expect.any(AbortSignal));
    expect(streamClosedWhenPolling).toEqual([true]);
    expect(openEventStream).toHaveBeenCalledTimes(2);
    expect(openEventStream).toHaveBeenLastCalledWith("workflow-a", 11);
    expect(onEvents).toHaveBeenCalledTimes(1);
    expect(onEvents).toHaveBeenLastCalledWith("workflow-a", [terminalEvent]);
    expect(result.current.store.lastEventSeq).toBe(11);
    expect(result.current.store.executionStatus).toBe("completed");
  });

  it("aborts a deferred fallback poll before replacement transport opens", async () => {
    vi.useFakeTimers();
    vi.spyOn(v2Api, "runtime").mockImplementation(async (workflowId) => (
      normalizeWorkflowRuntimeV2({ workflow_id: workflowId, events_cursor: 0 })
    ));
    let activePolls = 0;
    const pollSignals: Array<AbortSignal | undefined> = [];
    const completePolls: Array<() => void> = [];
    vi.spyOn(v2Api, "events").mockImplementation((...args) => {
      const [, afterSeq = 0, signal] = args as unknown as [string, number?, AbortSignal?];
      pollSignals.push(signal);
      activePolls += 1;
      return new Promise((resolve) => {
        let settled = false;
        const complete = () => {
          if (settled) return;
          settled = true;
          activePolls -= 1;
          resolve({ events: [], next_after_seq: afterSeq });
        };
        completePolls.push(complete);
        signal?.addEventListener("abort", complete, { once: true });
      });
    });
    const activePollsWhenOpening: number[] = [];
    vi.spyOn(v2Api, "openEventStream").mockImplementation((workflowId) => {
      activePollsWhenOpening.push(activePolls);
      return new TestEventSource(workflowId) as unknown as EventSource;
    });

    const { rerender } = renderHook(
      ({ workflowId }) => useV2RuntimeController({ workflowId }),
      { initialProps: { workflowId: "workflow-a" } },
    );
    await flushPromises();

    for (let failure = 0; failure < 3; failure += 1) {
      act(() => {
        TestEventSource.instances.at(-1)?.onerror?.();
      });
      await act(async () => {
        await vi.runOnlyPendingTimersAsync();
      });
    }
    act(() => {
      TestEventSource.instances.at(-1)?.onerror?.();
    });
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    expect(activePolls).toBe(1);

    rerender({ workflowId: "workflow-b" });
    await flushPromises();

    expect(pollSignals).toHaveLength(1);
    expect(pollSignals[0]?.aborted).toBe(true);
    expect(activePolls).toBe(0);
    expect(activePollsWhenOpening.at(-1)).toBe(0);
    expect(TestEventSource.instances.at(-1)?.workflowId).toBe("workflow-b");

    completePolls.forEach((complete) => complete());
  });

  it("does not apply a deferred snapshot older than a streamed terminal event", async () => {
    vi.useFakeTimers();
    const staleSnapshot = deferred<ReturnType<typeof normalizeWorkflowRuntimeV2>>();
    vi.spyOn(v2Api, "runtime")
      .mockResolvedValueOnce(normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-a",
        events_cursor: 0,
      }))
      .mockReturnValueOnce(staleSnapshot.promise);
    vi.spyOn(v2Api, "openEventStream")
      .mockImplementation((workflowId) => new TestEventSource(workflowId) as unknown as EventSource);
    const onSnapshot = vi.fn();

    const { result } = renderHook(() => useV2RuntimeController({
      workflowId: "workflow-a",
      onSnapshot,
    }));
    await flushPromises();

    let pendingSnapshot!: Promise<unknown>;
    act(() => {
      pendingSnapshot = result.current.syncSnapshot("workflow-a");
      TestEventSource.instances.at(-1)?.emit({
        seq: 11,
        event_type: "execution_completed",
        workflow_id: "workflow-a",
        payload: { execution_id: "execution-a", status: "completed" },
      });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16);
    });
    staleSnapshot.resolve(normalizeWorkflowRuntimeV2({
      workflow_id: "workflow-a",
      events_cursor: 10,
      active_execution_id: "execution-a",
      execution_status: "running",
      running_slot_ids: ["slot-a"],
    }));
    await act(async () => {
      await pendingSnapshot;
    });

    expect(result.current.store.lastEventSeq).toBe(11);
    expect(result.current.store.executionStatus).toBe("completed");
    expect(result.current.store.runningSlotIds).toEqual([]);
    expect(onSnapshot).toHaveBeenCalledTimes(1);
  });
});
