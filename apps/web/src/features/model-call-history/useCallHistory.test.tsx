import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useCallHistory, READ_INTERVAL_MS } from "./useCallHistory";
const { list, detail } = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn() }));
vi.mock("../../api/agentModelCallHistoryApi", () => ({ agentModelCallHistoryApi: { list, detail } }));
beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); list.mockResolvedValue({workflow_id:"w",items:[],next_offset:73}); detail.mockResolvedValue({call_id:"c",request:{},outcome:null}); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
it("loads summaries only, throttles refresh, follows server cursors and restores previous offset", async () => {
  const {result} = renderHook(() => useCallHistory("w"));
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(list).toHaveBeenCalledTimes(1); expect(detail).not.toHaveBeenCalled();
  await act(async () => { await result.current.refresh(); }); expect(list).toHaveBeenCalledTimes(1);
  await act(() => vi.advanceTimersByTimeAsync(READ_INTERVAL_MS));
  await act(async () => { await result.current.next(); }); expect(list.mock.calls[1][1]).toBe(73);
  await act(() => vi.advanceTimersByTimeAsync(READ_INTERVAL_MS));
  await act(async () => { await result.current.previous(); }); expect(list.mock.calls[2][1]).toBe(0);
});
it("locks simultaneous detail clicks and lets refresh invalidate the old outcome", async () => {
  const {result} = renderHook(() => useCallHistory("w")); await act(() => vi.advanceTimersByTimeAsync(1));
  await act(async () => { await Promise.all([result.current.select("c"),result.current.select("c")]); });
  expect(detail).toHaveBeenCalledTimes(1);
  await act(() => vi.advanceTimersByTimeAsync(READ_INTERVAL_MS));
  await act(async () => { await result.current.refresh(); }); expect(result.current.selected).toBeNull();
  await act(async () => { await result.current.select("c"); }); expect(detail).toHaveBeenCalledTimes(2);
});
it("keeps read failures local and aborts on unmount", async () => {
  list.mockRejectedValueOnce(new Error("Denied"));
  const {result,unmount} = renderHook(() => useCallHistory("w")); await act(() => vi.advanceTimersByTimeAsync(1));
  expect(result.current.error).toBe("Denied"); expect(detail).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(READ_INTERVAL_MS));
  list.mockImplementation(() => new Promise(() => {})); act(() => { void result.current.refresh(); });
  const signal = list.mock.calls.at(-1)?.[2] as AbortSignal; unmount(); expect(signal.aborted).toBe(true);
});
