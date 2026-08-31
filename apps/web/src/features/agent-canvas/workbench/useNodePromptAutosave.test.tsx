import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { V2ApiError } from "../../../api/v2Client.ts";
import { useNodePromptAutosave } from "./useNodePromptAutosave.ts";

describe("useNodePromptAutosave", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("debounces each node and coalesces the latest prompt", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ value }) => useNodePromptAutosave({
      nodeId: "node-1",
      value,
      enabled: true,
      patchNode,
    }), { initialProps: { value: "first" } });

    act(() => result.current.schedule("second"));
    rerender({ value: "second" });
    act(() => result.current.schedule("latest"));
    rerender({ value: "latest" });
    await act(async () => { vi.advanceTimersByTime(499); });
    expect(patchNode).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); });
    await act(async () => { await Promise.resolve(); });

    expect(patchNode).toHaveBeenCalledTimes(1);
    expect(patchNode).toHaveBeenCalledWith("node-1", { generation_prompt: "latest" }, { coalesce: true });
  });

  it("flushes immediately and preserves local text on a revision conflict", async () => {
    const patchNode = vi.fn().mockRejectedValue(new V2ApiError({
      status: 412,
      code: "workflow_state_conflict",
      message: "Workflow changed elsewhere.",
      details: {},
      violations: [],
      suggestedActions: [],
      payload: null,
    }));
    const onConflict = vi.fn();
    const { result, rerender } = renderHook(({ value }) => useNodePromptAutosave({
      nodeId: "node-1",
      value,
      enabled: true,
      patchNode,
      onConflict,
    }), { initialProps: { value: "local text" } });
    act(() => result.current.schedule("unsaved local text"));
    rerender({ value: "unsaved local text" });
    const flushed = await act(async () => result.current.flush());

    expect(flushed).toBe(false);
    expect(result.current.status).toBe("conflict");
    expect(onConflict).toHaveBeenCalledTimes(1);
    expect(patchNode).toHaveBeenCalledWith("node-1", { generation_prompt: "unsaved local text" }, { coalesce: true });
  });

  it("flushes pending text when the editor owner unmounts", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const { result, rerender, unmount } = renderHook(({ value }) => useNodePromptAutosave({
      nodeId: "node-1",
      value,
      enabled: true,
      patchNode,
    }), { initialProps: { value: "before" } });
    act(() => result.current.schedule("on close"));
    rerender({ value: "on close" });
    unmount();
    await act(async () => { await Promise.resolve(); });

    expect(patchNode).toHaveBeenCalledWith("node-1", { generation_prompt: "on close" }, { coalesce: true });
  });
});
