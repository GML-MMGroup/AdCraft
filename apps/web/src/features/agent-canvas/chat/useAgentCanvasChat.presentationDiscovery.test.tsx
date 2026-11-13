import { useMemo } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AgentCanvasWorkflowV2, PresentationStreamSummaryV1 } from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasChatTimeline: vi.fn(),
  agentCanvasCreativeSession: vi.fn(),
  listAgentCanvasPresentationStreams: vi.fn(),
  openAgentCanvasPresentationStream: vi.fn(),
}));
vi.mock("../../../api/agentCanvasApi.ts", () => ({ agentCanvasApi: api, isV2ApiError: () => false }));
import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";

const noEvents: [] = [];
function useHarness() {
  const workflow = useMemo<AgentCanvasWorkflowV2>(() => ({
    workflow_id: "workflow-1", project_id: "project-1", workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1", revision: 1, layout_revision: 1,
    nodes: [], bindings: [], assets: [], active_style_skill: null,
  }), []);
  return useAgentCanvasChat({ workflow, chatRevision: 0, chatEvents: noEvents });
}
function summary(id: string, status: PresentationStreamSummaryV1["status"]): PresentationStreamSummaryV1 {
  return {
    stream_id: id, stream_kind: "assistant", status, generation_id: id, turn_id: id,
    node_id: null, node_revision: null, created_at: "2026-11-09T00:00:00Z",
    terminal_at: status === "open" ? null : "2026-11-09T00:01:00Z",
  };
}
beforeEach(() => {
  vi.useFakeTimers();
  api.agentCanvasCreativeSession.mockResolvedValue(null);
  api.agentCanvasChatTimeline.mockResolvedValue({
    workflow_id: "workflow-1", conversation_id: "conversation-1", items: [], next_cursor: 0,
    guidanceSession: null, guidanceAdvancePrecondition: null, continuations: [], current_session_actions: [], presentationItems: [],
  });
  api.openAgentCanvasPresentationStream.mockImplementation(() => ({
    addEventListener: vi.fn(), close: vi.fn(), onerror: null, onopen: null,
  }));
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); vi.resetAllMocks(); });

it("reads historical summaries without subscribing to any finished output", async () => {
  const streams = Array.from({ length: 20 }, (_, i) => summary(`history-${i}`, i < 15 ? "completed" : "failed"));
  api.listAgentCanvasPresentationStreams.mockResolvedValue({ streams });
  const { result } = renderHook(useHarness);
  await act(async () => { await vi.advanceTimersByTimeAsync(100); });
  expect(result.current.state.presentationStreamSummaries).toHaveLength(20);
  expect(api.openAgentCanvasPresentationStream).not.toHaveBeenCalled();
});

it("subscribes only to live output and closes it when discovery reports completion", async () => {
  api.listAgentCanvasPresentationStreams.mockResolvedValue({ streams: [
    summary("live", "open"), summary("done", "completed"), summary("failed", "failed"), summary("replaced", "superseded"),
  ] });
  renderHook(useHarness);
  await act(async () => { await vi.advanceTimersByTimeAsync(100); });
  expect(api.openAgentCanvasPresentationStream).toHaveBeenCalledExactlyOnceWith("workflow-1", "live", 0);
  const source = api.openAgentCanvasPresentationStream.mock.results[0]!.value;
  const previousReads = api.agentCanvasChatTimeline.mock.calls.length;
  api.listAgentCanvasPresentationStreams.mockResolvedValue({ streams: [summary("live", "completed")] });
  await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
  expect(source.close).toHaveBeenCalled();
  expect(api.openAgentCanvasPresentationStream).toHaveBeenCalledTimes(1);
  expect(api.agentCanvasChatTimeline.mock.calls.length).toBeGreaterThan(previousReads);
});

it("does not pile up discovery reads while one is pending and cancels it on unmount", async () => {
  api.listAgentCanvasPresentationStreams
    .mockResolvedValueOnce({ streams: [summary("live", "open")] })
    .mockImplementation(() => new Promise(() => {}));
  const { unmount } = renderHook(useHarness);
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(api.listAgentCanvasPresentationStreams).toHaveBeenCalledTimes(2);
  const signal = api.listAgentCanvasPresentationStreams.mock.calls[1]![2].signal;
  expect(signal.aborted).toBe(false);
  unmount();
  expect(signal.aborted).toBe(true);
});
