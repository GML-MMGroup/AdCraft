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
});
