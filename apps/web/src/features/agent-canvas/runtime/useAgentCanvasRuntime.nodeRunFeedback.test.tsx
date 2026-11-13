import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentCanvasWorkflowV2, CanvasNodeV2, CanvasRunAcceptedV2, CanvasRuntimeSnapshotV2 } from "../../../types-v2.ts";

const api = vi.hoisted(() => ({
  agentCanvasRuntime: vi.fn(), agentCanvasEvents: vi.fn(), agentCanvasWorkflowWithEtag: vi.fn(),
  openAgentCanvasEventStream: vi.fn(), runAgentCanvas: vi.fn(),
}));
vi.mock("../../../api/agentCanvasApi.ts", () => ({ agentCanvasApi: api, isV2ApiError: () => false }));
import { useAgentCanvasRuntime } from "./useAgentCanvasRuntime.ts";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function node(status: CanvasNodeV2["status"] = "draft"): CanvasNodeV2 {
  return {
    node_id: "image-1", workflow_id: "workflow-1", node_type: "image", creative_role: "general_image",
    role_contract_version: "ad-media-role-v1", title: "Prepared image", status, execution_mode: "generative",
    summary_prompt: null, generation_prompt: "A product image.", structured_content: {}, model_id: null,
    model_selection_mode: "default", model_ref: null, model_summary: null, parameters: {}, metadata: {},
    parameter_provenance: {}, prompt_context_snapshot_id: null, output_asset_id: status === "ready" ? "old-output" : null,
    output_asset_version_id: null, latest_attempt: null, prompt_presentation: null, prompt_preparation: null,
    position: { x: 0, y: 0 }, revision: 1, error: null,
    created_at: "2026-11-09T00:00:00Z", updated_at: "2026-11-09T00:00:00Z",
  };
}
function workflow(nodes = [node()], workflowId = "workflow-1"): AgentCanvasWorkflowV2 {
  return { workflow_id: workflowId, project_id: "project-1", workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1", revision: 1, layout_revision: 1, nodes, bindings: [], assets: [], active_style_skill: null };
}
const accepted: CanvasRunAcceptedV2 = {
  workflow_id: "workflow-1", execution_id: "execution-new", status: "queued",
  accepted_node_ids: ["image-1"], joined_node_ids: [], skipped: [], waiting_node_ids: [],
  run_intent_snapshot_ids: {}, events_cursor: 10,
};
const runtime: CanvasRuntimeSnapshotV2 = {
  workflow_id: "workflow-1", active_execution_id: null, execution_status: null, node_runtime: {},
  queued_node_ids: [], working_node_ids: [], waiting_node_ids: [], ready_node_ids: [], failed_node_ids: [],
  events_cursor: 0, updated_at: "2026-11-09T00:00:00Z",
};
const callbacks = { applyWorkflow: vi.fn(), mergePublishedAsset: vi.fn(), mergeNode: vi.fn() };
beforeEach(() => {
  vi.useFakeTimers();
  api.agentCanvasRuntime.mockResolvedValue(runtime);
  api.agentCanvasEvents.mockResolvedValue({ workflow_id: "workflow-1", events: [], next_cursor: 0 });
  api.agentCanvasWorkflowWithEtag.mockResolvedValue({ value: workflow(), etag: '"1"' });
  api.openAgentCanvasEventStream.mockReturnValue({ addEventListener: vi.fn(), close: vi.fn() });
  api.runAgentCanvas.mockResolvedValue(accepted);
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); vi.resetAllMocks(); });

describe("node Run feedback", () => {
  it.each(["queued", "waiting", "running"] as const)("does not resubmit a persisted %s attempt after reload", async (status) => {
    const current = node();
    current.latest_attempt = {
      execution_id: "execution-existing", member_id: "member-existing", run_intent_snapshot_id: null,
      status, error: null, created_at: current.created_at, updated_at: current.updated_at,
    };
    const { result } = renderHook(() => useAgentCanvasRuntime(workflow([current]), callbacks));
    expect(result.current.actions.beginNodeRun(current)).toBeNull();
    await act(async () => { await result.current.actions.runNode(current); });
    expect(api.runAgentCanvas).not.toHaveBeenCalled();
  });

  it("starts immediately, blocks duplicate submissions, and survives a stale post-acceptance snapshot", async () => {
    const submission = deferred<CanvasRunAcceptedV2>();
    api.runAgentCanvas.mockReturnValue(submission.promise);
    const original = workflow();
    const { result } = renderHook(() => useAgentCanvasRuntime(original, callbacks));
    let request!: Promise<void>;
    act(() => { request = result.current.actions.runNode(original.nodes[0]!); });
    expect(result.current.state.pendingNodeIds?.has("image-1")).toBe(true);
    await act(async () => { await result.current.actions.runNode(original.nodes[0]!); });
    expect(api.runAgentCanvas).toHaveBeenCalledTimes(1);
    await act(async () => { submission.resolve(accepted); await request; });
    expect(result.current.state.pendingNodeIds.has("image-1")).toBe(true);
    expect(original.nodes[0]!.status).toBe("draft");
    expect(callbacks.mergeNode).not.toHaveBeenCalled();
  });

  it("rolls back a failed regeneration without modifying the previous output", async () => {
    const submission = deferred<CanvasRunAcceptedV2>();
    api.runAgentCanvas.mockReturnValue(submission.promise);
    const original = workflow([node("ready")]);
    const { result } = renderHook(() => useAgentCanvasRuntime(original, callbacks));
    let request!: Promise<void>;
    act(() => { request = result.current.actions.runNode(original.nodes[0]!); });
    expect(result.current.state.pendingNodeIds?.has("image-1")).toBe(true);
    const rejection = expect(request).rejects.toThrow("Provider unavailable");
    await act(async () => { submission.reject(new Error("Provider unavailable")); await rejection; });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
    expect(original.nodes[0]).toMatchObject({ status: "ready", output_asset_id: "old-output" });
    expect(result.current.state.runPending).toBe(false);
  });

  it("holds feedback for an old finished attempt and hands off to this execution's terminal node", async () => {
    const oldNode = { ...node("ready"), latest_attempt: {
      execution_id: "execution-old", member_id: "member-old", status: "succeeded" as const,
      run_intent_snapshot_id: null, error: null, created_at: node().created_at, updated_at: node().updated_at,
    } };
    const { result, rerender } = renderHook(({ current }) => useAgentCanvasRuntime(current, callbacks), {
      initialProps: { current: workflow([oldNode]) },
    });
    await act(async () => { await result.current.actions.runNode(oldNode); });
    rerender({ current: workflow([{ ...oldNode, revision: 2 }]) });
    expect(result.current.state.pendingNodeIds?.has("image-1")).toBe(true);
    rerender({ current: workflow([{ ...oldNode, revision: 3, latest_attempt: { ...oldNode.latest_attempt, execution_id: accepted.execution_id } }]) });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
  });

  it("keeps preparation feedback until submission or cancels it when saving fails", async () => {
    const original = workflow();
    const { result } = renderHook(() => useAgentCanvasRuntime(original, callbacks));
    let cancel!: () => void;
    act(() => { cancel = result.current.actions.beginNodeRun(original.nodes[0]!)!; });
    expect(result.current.state.pendingNodeIds.has("image-1")).toBe(true);
    expect(result.current.actions.beginNodeRun(original.nodes[0]!)).toBeNull();
    expect(api.runAgentCanvas).not.toHaveBeenCalled();
    act(() => cancel());
    expect(result.current.state.pendingNodeIds.size).toBe(0);
    act(() => { cancel = result.current.actions.beginNodeRun(original.nodes[0]!)!; });
    await act(async () => { await result.current.actions.runNode(original.nodes[0]!); cancel(); });
    expect(result.current.state.pendingNodeIds.has("image-1")).toBe(true);
  });

  it("hands off queued work to canonical Working without a Draft frame", async () => {
    const original = node();
    const { result, rerender } = renderHook(({ current }) => useAgentCanvasRuntime(current, callbacks), {
      initialProps: { current: workflow([original]) },
    });
    await act(async () => { await result.current.actions.runNode(original); });
    const attempt = { execution_id: accepted.execution_id, member_id: "member-new", run_intent_snapshot_id: null,
      status: "queued" as const, error: null, created_at: original.created_at, updated_at: original.updated_at };
    rerender({ current: workflow([{ ...original, latest_attempt: attempt, revision: 2 }]) });
    expect(result.current.state.pendingNodeIds.has("image-1")).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(api.agentCanvasWorkflowWithEtag.mock.calls.length).toBeGreaterThan(1);
    rerender({ current: workflow([{ ...original, status: "working", latest_attempt: { ...attempt, status: "running" }, revision: 3 }]) });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
    const reads = api.agentCanvasWorkflowWithEtag.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    expect(api.agentCanvasWorkflowWithEtag).toHaveBeenCalledTimes(reads);
  });

  it("reconciles a terminal node that arrived before the submission response", async () => {
    const submission = deferred<CanvasRunAcceptedV2>();
    api.runAgentCanvas.mockReturnValue(submission.promise);
    const original = node();
    const { result, rerender } = renderHook(({ current }) => useAgentCanvasRuntime(current, callbacks), {
      initialProps: { current: workflow([original]) },
    });
    let request!: Promise<void>;
    act(() => { request = result.current.actions.runNode(original); });
    rerender({ current: workflow([{ ...original, status: "ready", revision: 2, output_asset_id: "new-output", latest_attempt: {
      execution_id: accepted.execution_id, member_id: "member-new", run_intent_snapshot_id: null,
      status: "succeeded", error: null, created_at: original.created_at, updated_at: original.updated_at,
    } }]) });
    await act(async () => { submission.resolve(accepted); await request; });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
  });

  it("keeps other nodes pending when one of two parallel submissions fails", async () => {
    const one = deferred<CanvasRunAcceptedV2>();
    const two = deferred<CanvasRunAcceptedV2>();
    api.runAgentCanvas.mockReturnValueOnce(one.promise).mockReturnValueOnce(two.promise);
    const original = workflow([node(), { ...node(), node_id: "image-2" }]);
    const { result } = renderHook(() => useAgentCanvasRuntime(original, callbacks));
    let first!: Promise<void>; let second!: Promise<void>;
    act(() => { first = result.current.actions.runNode(original.nodes[0]!); second = result.current.actions.runNode(original.nodes[1]!); });
    expect(result.current.state.pendingNodeIds.size).toBe(2);
    const firstError = expect(first).rejects.toThrow("Rejected");
    await act(async () => { one.reject(new Error("Rejected")); await firstError; });
    expect([...result.current.state.pendingNodeIds]).toEqual(["image-2"]);
    expect(result.current.state.runPending).toBe(true);
    const secondError = expect(second).rejects.toThrow("Rejected");
    await act(async () => { two.reject(new Error("Rejected")); await secondError; });
    expect(result.current.state.runPending).toBe(false);
  });

  it("ignores a late result after leaving and returning to the same workflow", async () => {
    const old = deferred<CanvasRunAcceptedV2>();
    const next = deferred<CanvasRunAcceptedV2>();
    api.runAgentCanvas.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
    const original = workflow();
    const { result, rerender } = renderHook(({ current }) => useAgentCanvasRuntime(current, callbacks), { initialProps: { current: original } });
    let oldRequest!: Promise<void>; let newRequest!: Promise<void>;
    act(() => { oldRequest = result.current.actions.runNode(original.nodes[0]!); });
    rerender({ current: workflow([], "workflow-2") });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
    rerender({ current: original });
    act(() => { newRequest = result.current.actions.runNode(original.nodes[0]!); });
    await act(async () => { old.resolve(accepted); await oldRequest; });
    expect(result.current.state.pendingNodeIds.has("image-1")).toBe(true);
    const rejection = expect(newRequest).rejects.toThrow("New request failed");
    await act(async () => { next.reject(new Error("New request failed")); await rejection; });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
  });

  it("releases feedback when the server skips the requested node", async () => {
    api.runAgentCanvas.mockResolvedValue({ ...accepted, accepted_node_ids: [], skipped: [{ node_id: "image-1", reason: "not_runnable" }] });
    const original = workflow();
    const { result } = renderHook(() => useAgentCanvasRuntime(original, callbacks));
    await act(async () => { await expect(result.current.actions.runNode(original.nodes[0]!)).rejects.toThrow("could not be queued"); });
    expect(result.current.state.pendingNodeIds.size).toBe(0);
  });

  it("does not submit from an old preparation callback after revisiting the workflow", async () => {
    const original = workflow();
    const { result, rerender } = renderHook(({ current }) => useAgentCanvasRuntime(current, callbacks), { initialProps: { current: original } });
    const originalRun = result.current.actions.runNode;
    act(() => { result.current.actions.beginNodeRun(original.nodes[0]!); });
    rerender({ current: workflow([], "workflow-2") });
    rerender({ current: original });
    await act(async () => { await originalRun(original.nodes[0]!); });
    expect(api.runAgentCanvas).not.toHaveBeenCalled();
    expect(result.current.state.pendingNodeIds.size).toBe(0);
  });
});
