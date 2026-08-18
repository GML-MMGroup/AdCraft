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

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });

  return { promise, resolve, reject };
}

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

    let kept = false;
    await act(async () => {
      kept = await result.current.keep();
    });

    expect(kept).toBe(true);
    expect(persistPositions).toHaveBeenCalledOnce();
    expect(persistPositions).toHaveBeenCalledWith(targetPositions, [{
      node_id: "a",
      x: 1,
      y: 2,
    }]);
    expect(result.current.status).toBe("idle");
    expect(result.current.active).toBe(false);
  });

  it("cancels by restoring the saved viewport without persisting", () => {
    const persistPositions = vi.fn();
    const restoreViewport = vi.fn();
    const rollbackPositions = vi.fn();
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport,
      rollbackPositions,
    }));

    act(() => result.current.begin(preview));
    act(() => result.current.cancel());

    expect(restoreViewport).toHaveBeenCalledOnce();
    expect(restoreViewport).toHaveBeenCalledWith(originalViewport, "wf-1");
    expect(rollbackPositions).toHaveBeenCalledOnce();
    expect(rollbackPositions).toHaveBeenCalledWith("wf-1", [{
      node_id: "a",
      x: 1,
      y: 2,
    }]);
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

  it("rolls back optimistic positions locally when Undo follows a failed Keep", async () => {
    const persistPositions = vi.fn().mockRejectedValue(new Error("Layout service unavailable"));
    const restoreViewport = vi.fn();
    const rollbackPositions = vi.fn();
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport,
      rollbackPositions,
    }));

    act(() => result.current.begin(preview));
    await act(() => result.current.keep());
    act(() => result.current.cancel());

    expect(rollbackPositions).toHaveBeenCalledOnce();
    expect(rollbackPositions).toHaveBeenCalledWith("wf-1", [{
      node_id: "a",
      x: 1,
      y: 2,
    }]);
    expect(persistPositions).toHaveBeenCalledOnce();
    expect(restoreViewport).toHaveBeenCalledWith(originalViewport, "wf-1");
  });

  it("restores the captured positions when canonical positions refresh during preview", () => {
    const rollbackPositions = vi.fn();
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions: vi.fn(),
      restoreViewport: vi.fn(),
      rollbackPositions,
    }));

    act(() => result.current.begin(preview));
    const refreshedCanonical = [{
      id: "a",
      position: { x: 900, y: 700 },
      selected: true,
      data: { value: 2 },
    }];
    expect(result.current.overlay(refreshedCanonical)[0]?.position).toEqual({ x: 50, y: 60 });

    act(() => result.current.cancel());

    expect(rollbackPositions).toHaveBeenCalledWith("wf-1", [{
      node_id: "a",
      x: 1,
      y: 2,
    }]);
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

  it("restores the preview viewport when the workflow ID changes without persisting", () => {
    const persistPositions = vi.fn();
    const restoreViewport = vi.fn();
    const rollbackPositions = vi.fn();
    const onUserResolution = vi.fn();
    const { result, rerender } = renderHook(({ workflowId }) => useAgentCanvasLayoutPreview({
      workflowId,
      persistPositions,
      restoreViewport,
      rollbackPositions,
      onUserResolution,
    }), { initialProps: { workflowId: "wf-1" } });

    act(() => result.current.begin(preview));
    rerender({ workflowId: "wf-2" });

    expect(persistPositions).not.toHaveBeenCalled();
    expect(result.current.status).toBe("idle");
    expect(result.current.active).toBe(false);
    expect(result.current.positions).toEqual([]);
    expect(restoreViewport).toHaveBeenCalledWith(originalViewport, "wf-1");
    expect(rollbackPositions).toHaveBeenCalledWith("wf-1", [{
      node_id: "a",
      x: 1,
      y: 2,
    }]);
    expect(onUserResolution).not.toHaveBeenCalled();
  });

  it("reports only explicit Undo and successful Keep as user resolutions", async () => {
    const onUserResolution = vi.fn();
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions: vi.fn().mockResolvedValue(undefined),
      restoreViewport: vi.fn(),
      onUserResolution,
    }));

    act(() => result.current.begin(preview));
    act(() => result.current.cancel());
    act(() => result.current.begin(preview));
    await act(() => result.current.keep());

    expect(onUserResolution.mock.calls).toEqual([["undo"], ["keep"]]);
  });

  it("restores the preview viewport during unmount without persisting", () => {
    const persistPositions = vi.fn();
    const restoreViewport = vi.fn();
    const { result, unmount } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport,
    }));

    act(() => result.current.begin(preview));
    unmount();

    expect(restoreViewport).toHaveBeenCalledWith(originalViewport, "wf-1");
    expect(persistPositions).not.toHaveBeenCalled();
  });

  it("ignores a successful save after cancellation and a replacement preview", async () => {
    const save = createDeferred<void>();
    const persistPositions = vi.fn(() => save.promise);
    const replacementPositions = [{ node_id: "a", x: 70, y: 80 }];
    const { result } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport: vi.fn(),
    }));

    act(() => result.current.begin(preview));
    let keep!: Promise<void>;
    act(() => {
      keep = result.current.keep();
    });
    act(() => result.current.cancel());
    act(() => result.current.begin({ ...preview, targetPositions: replacementPositions }));

    let kept = true;
    await act(async () => {
      save.resolve();
      kept = await keep;
    });

    expect(kept).toBe(false);
    expect(result.current.status).toBe("previewing");
    expect(result.current.error).toBeNull();
    expect(result.current.positions).toEqual(replacementPositions);
  });

  it("ignores a rejected save after switching away and back to a new preview", async () => {
    const save = createDeferred<void>();
    const persistPositions = vi.fn(() => save.promise);
    const replacementPositions = [{ node_id: "a", x: 70, y: 80 }];
    const { result, rerender } = renderHook(({ workflowId }) => useAgentCanvasLayoutPreview({
      workflowId,
      persistPositions,
      restoreViewport: vi.fn(),
    }), { initialProps: { workflowId: "wf-1" } });

    act(() => result.current.begin(preview));
    let keep!: Promise<void>;
    act(() => {
      keep = result.current.keep();
    });
    rerender({ workflowId: "wf-2" });
    rerender({ workflowId: "wf-1" });
    act(() => result.current.begin({ ...preview, targetPositions: replacementPositions }));

    await act(async () => {
      save.reject(new Error("Layout service unavailable"));
      await keep;
    });

    expect(result.current.status).toBe("previewing");
    expect(result.current.error).toBeNull();
    expect(result.current.positions).toEqual(replacementPositions);
  });

  it("does not update unmounted state or retry persistence when an in-flight save completes", async () => {
    const save = createDeferred<void>();
    const persistPositions = vi.fn(() => save.promise);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { result, unmount } = renderHook(() => useAgentCanvasLayoutPreview({
      workflowId: "wf-1",
      persistPositions,
      restoreViewport: vi.fn(),
    }));

    act(() => result.current.begin(preview));
    let keep!: Promise<void>;
    act(() => {
      keep = result.current.keep();
    });
    unmount();

    await act(async () => {
      save.resolve();
      await keep;
    });

    expect(persistPositions).toHaveBeenCalledOnce();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
