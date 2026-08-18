import type { Viewport } from "@xyflow/react";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanvasLayoutPositionV2 } from "../../../types-v2.ts";
import {
  overlayAgentCanvasLayoutPreview,
  useAgentCanvasLayoutPreview,
} from "./useAgentCanvasLayoutPreview.ts";

const originalViewport: Viewport = { x: -140, y: 80, zoom: 0.72 };
const targetPositions: CanvasLayoutPositionV2[] = [{ node_id: "a", x: 50, y: 60 }];
const preview = {
  workflowId: "wf-1",
  nodes: [{ id: "a", position: { x: 1, y: 2 }, selected: true, data: { value: 1 } }],
  targetPositions,
  viewport: originalViewport,
};

describe("overlayAgentCanvasLayoutPreview", () => {
  it("overlays preview coordinates without changing node content or selection", () => {
    const current = [{ id: "a", position: { x: 1, y: 2 }, selected: true, data: { value: 1 } }];
    const next = overlayAgentCanvasLayoutPreview(current, targetPositions);

    expect(next[0]).toMatchObject({
      id: "a",
      position: { x: 50, y: 60 },
      selected: true,
      data: { value: 1 },
    });
    expect(current[0]?.position).toEqual({ x: 1, y: 2 });
  });
});

describe("useAgentCanvasLayoutPreview", () => {
  it("previews without persisting and keeps only after confirmation", async () => {
    const persistPositions = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport: vi.fn(),
    }));

    act(() => result.current.begin(preview));

    expect(result.current.status).toBe("previewing");
    expect(result.current.positions).toEqual(targetPositions);
    expect(persistPositions).not.toHaveBeenCalled();

    await act(() => result.current.keep());

    expect(persistPositions).toHaveBeenCalledOnce();
    expect(persistPositions).toHaveBeenCalledWith(targetPositions);
    expect(result.current.status).toBe("idle");
    expect(result.current.active).toBe(false);
  });

  it("cancels by restoring the saved viewport without persisting", () => {
    const persistPositions = vi.fn();
    const restoreViewport = vi.fn();
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport,
    }));

    act(() => result.current.begin(preview));
    act(() => result.current.cancel());

    expect(restoreViewport).toHaveBeenCalledOnce();
    expect(restoreViewport).toHaveBeenCalledWith(originalViewport);
    expect(persistPositions).not.toHaveBeenCalled();
    expect(result.current.status).toBe("idle");
    expect(result.current.positions).toEqual([]);
  });

  it("retains the preview and exposes the save error for a retry", async () => {
    const persistPositions = vi.fn().mockRejectedValue(new Error("Layout service unavailable"));
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport: vi.fn(),
    }));

    act(() => result.current.begin(preview));
    await act(() => result.current.keep());

    expect(result.current.status).toBe("save_error");
    expect(result.current.error).toBe("Layout service unavailable");
    expect(result.current.active).toBe(true);
    expect(result.current.positions).toEqual(targetPositions);
  });

  it("clears a save error after a retry succeeds", async () => {
    const persistPositions = vi.fn()
      .mockRejectedValueOnce(new Error("Layout service unavailable"))
      .mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport: vi.fn(),
    }));

    act(() => result.current.begin(preview));
    await act(() => result.current.keep());
    await act(() => result.current.keep());

    expect(persistPositions).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("idle");
    expect(result.current.error).toBeNull();
    expect(result.current.positions).toEqual([]);
  });

  it("clears a preview when the workflow ID changes without persisting", () => {
    const persistPositions = vi.fn();
    const { result, rerender } = renderHook(({ workflowId }) => useAgentCanvasLayoutPreview({
      workflowId,
      persistPositions,
      restoreViewport: vi.fn(),
    }), { initialProps: { workflowId: "wf-1" } });

    act(() => result.current.begin(preview));
    rerender({ workflowId: "wf-2" });

    expect(persistPositions).not.toHaveBeenCalled();
    expect(result.current.status).toBe("idle");
    expect(result.current.active).toBe(false);
    expect(result.current.positions).toEqual([]);
  });
});
