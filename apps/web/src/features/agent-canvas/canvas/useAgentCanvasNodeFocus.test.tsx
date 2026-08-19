import { act, cleanup, fireEvent, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentCanvasNodeFocus } from "./useAgentCanvasNodeFocus.ts";

const originalViewport = { x: -140, y: 80, zoom: 0.72 };

function createFlowRef() {
  return {
    current: {
      getViewport: vi.fn(() => originalViewport),
      fitView: vi.fn().mockResolvedValue(true),
      setViewport: vi.fn().mockResolvedValue(true),
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

describe("useAgentCanvasNodeFocus", () => {
  it("captures the current viewport and zooms the whole canvas around the double-clicked node", () => {
    const flowRef = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeFocus({
      flowRef,
      scopeKey: "workflow-1",
    }));

    act(() => result.current.focusNode("image-1"));

    expect(result.current.focusedNodeId).toBe("image-1");
    expect(flowRef.current.getViewport).toHaveBeenCalledOnce();
    expect(flowRef.current.fitView).toHaveBeenCalledWith({
      nodes: [{ id: "image-1" }],
      padding: 0.12,
      duration: 420,
      minZoom: 0.05,
      maxZoom: 4,
    });
  });

  it("restores the exact pre-focus viewport when Escape is pressed", () => {
    const flowRef = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeFocus({
      flowRef,
      scopeKey: "workflow-1",
    }));
    act(() => result.current.focusNode("image-1"));

    fireEvent.keyDown(window, { key: "Escape" });

    expect(result.current.focusedNodeId).toBeNull();
    expect(flowRef.current.setViewport).toHaveBeenCalledWith(originalViewport, { duration: 320 });
  });

  it("delays exit for a single click on another node so a double click can switch focus", () => {
    const flowRef = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeFocus({
      flowRef,
      scopeKey: "workflow-1",
    }));
    act(() => result.current.focusNode("image-1"));

    act(() => result.current.scheduleExitForNodeSelection("video-1"));
    expect(result.current.focusedNodeId).toBe("image-1");

    act(() => vi.advanceTimersByTime(240));
    expect(result.current.focusedNodeId).toBeNull();
    expect(flowRef.current.setViewport).toHaveBeenCalledWith(originalViewport, { duration: 320 });
  });

  it("keeps the original viewport while switching focus directly to another node", () => {
    const flowRef = createFlowRef();
    const { result } = renderHook(() => useAgentCanvasNodeFocus({
      flowRef,
      scopeKey: "workflow-1",
    }));
    act(() => result.current.focusNode("image-1"));
    act(() => result.current.scheduleExitForNodeSelection("video-1"));

    act(() => result.current.focusNode("video-1"));
    act(() => vi.advanceTimersByTime(240));

    expect(result.current.focusedNodeId).toBe("video-1");
    expect(flowRef.current.getViewport).toHaveBeenCalledOnce();
    expect(flowRef.current.setViewport).not.toHaveBeenCalled();
  });
});
