import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReactFlowInstance } from "@xyflow/react";
import type { ProgressiveNodePlacementPlan } from "./agentCanvasProgressivePlacement.ts";
import { useAgentCanvasNodeRevealQueue } from "./useAgentCanvasNodeRevealQueue.ts";

function plan(nodeIds: string[]): ProgressiveNodePlacementPlan {
  return {
    positions: nodeIds.map((node_id) => ({ node_id, x: 100, y: 100 })),
    levels: [{ level: 0, nodeIds }],
    orderedNodeIds: nodeIds,
  };
}

function createFlowRef() {
  let mounted: string[] = [];
  return {
    mounted: (nodeIds: string[]) => { mounted = nodeIds; },
    ref: {
      current: {
        getNodes: () => mounted.map((id) => ({ id })),
      } as unknown as ReactFlowInstance,
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useAgentCanvasNodeRevealQueue", () => {
  it("reveals and focuses nodes in deterministic order after they are mounted", async () => {
    const focus = vi.fn();
    const flow = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: flow.ref,
      onFocusNode: focus,
      reducedMotion: false,
    }));

    act(() => {
      result.current.enqueue(plan(["world", "script"]));
      result.current.syncCanonicalNodeIds(["world", "script"]);
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["world"]));
    expect(focus).not.toHaveBeenCalled();

    act(() => flow.mounted(["world"]));
    await act(async () => vi.advanceTimersByTime(16));
    expect(focus).toHaveBeenNthCalledWith(1, "world");

    act(() => flow.mounted(["world", "script"]));
    await act(async () => vi.advanceTimersByTime(420));
    expect(result.current.visibleNodeIds).toEqual(new Set(["world", "script"]));
    expect(focus).toHaveBeenNthCalledWith(2, "script");
  });

  it("does not focus the same node twice when delivery is duplicated", () => {
    const focus = vi.fn();
    const flow = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: flow.ref,
      onFocusNode: focus,
      reducedMotion: true,
    }));

    act(() => {
      result.current.enqueue(plan(["world"]));
      result.current.enqueue(plan(["world"]));
      result.current.syncCanonicalNodeIds(["world"]);
      flow.mounted(["world"]);
    });
    expect(result.current.pendingNodeIds).toEqual([]);
    expect(result.current.visibleNodeIds).toEqual(new Set(["world"]));
  });

  it("keeps reserved receipt nodes hidden until their placement plan is queued", () => {
    const focus = vi.fn();
    const flow = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: flow.ref,
      onFocusNode: focus,
      reducedMotion: true,
    }));

    act(() => {
      result.current.reserveNodeIds(["world"]);
      result.current.syncCanonicalNodeIds(["world"]);
    });
    expect(result.current.visibleNodeIds).toEqual(new Set());

    act(() => {
      flow.mounted(["world"]);
      result.current.enqueue(plan(["world"]));
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["world"]));
  });

  it("interrupts pending focus without hiding revealed nodes", () => {
    const focus = vi.fn();
    const flow = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: flow.ref,
      onFocusNode: focus,
      reducedMotion: false,
    }));

    act(() => {
      result.current.enqueue(plan(["world", "script"]));
      result.current.syncCanonicalNodeIds(["world", "script"]);
      result.current.interrupt();
    });
    act(() => vi.advanceTimersByTime(1_000));
    expect(focus).not.toHaveBeenCalled();
    expect(result.current.visibleNodeIds).toEqual(new Set(["world", "script"]));
    expect(result.current.pendingNodeIds).toEqual([]);
  });
});
