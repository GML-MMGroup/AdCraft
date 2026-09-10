import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Edge } from "@xyflow/react";
import type { AgentCanvasWorkflowV2, CanvasBindingCreateRequestV2, CanvasBindingV2 } from "../../../types-v2.ts";
import { useOptimisticCanvasConnections } from "./useOptimisticCanvasConnections.ts";

afterEach(cleanup);
const request: CanvasBindingCreateRequestV2 = {
  source: { kind: "node_output", source_node_id: "source" }, target_node_id: "target",
  input_role: "image_reference", enabled: true, order: 0,
};
const binding = { ...request, binding_id: "binding-real", workflow_id: "a" } as CanvasBindingV2;
const edge: Edge = { id: binding.binding_id, source: "source", target: "target", data: { binding } };
function workflow(id = "a", bindings: CanvasBindingV2[] = [], ids = ["source", "target"]) {
  return { workflow_id: id, bindings, nodes: ids.map((node_id) => ({ node_id })) } as AgentCanvasWorkflowV2;
}
function deferred() {
  let resolve!: (binding: CanvasBindingV2 | null) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<CanvasBindingV2 | null>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup() {
  const pending = deferred();
  const createBinding = vi.fn((_request: CanvasBindingCreateRequestV2, _guard?: { isCurrent?: () => boolean }) => pending.promise);
  const onError = vi.fn();
  const hook = renderHook(({ workflow, edges }) => useOptimisticCanvasConnections({ workflow, edges, createBinding, onError }), {
    initialProps: { workflow: workflow(), edges: [] as Edge[] },
  });
  return { ...hook, pending, createBinding, onError };
}

describe("optimistic canvas connections", () => {
  it("draws immediately without a substitute Binding, then replaces without a gap", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    expect(h.result.current.displayEdges).toHaveLength(1);
    const temporary = h.result.current.displayEdges[0];
    expect(temporary.data?.binding).toBeUndefined();
    expect(temporary.data?.optimistic).toBe(true);
    expect(temporary.deletable).toBe(false);
    expect(h.createBinding).toHaveBeenCalledTimes(1);
    // Authority arrives before the parent effect commits the canonical display list.
    h.rerender({ workflow: workflow("a", [binding]), edges: [] });
    await act(async () => { h.pending.resolve(binding); });
    expect(h.result.current.displayEdges).toHaveLength(1);
    h.rerender({ workflow: workflow("a", [binding]), edges: [edge] });
    expect(h.result.current.displayEdges).toEqual([edge]);
  });

  it("removes only the failed temporary edge and reports the existing error", async () => {
    const h = setup();
    h.rerender({ workflow: workflow(), edges: [edge] });
    act(() => { void h.result.current.submit({ ...request, input_role: "text_context" }); });
    expect(h.result.current.displayEdges).toHaveLength(2);
    await act(async () => { h.pending.reject(new Error("conflict")); });
    expect(h.result.current.displayEdges).toEqual([edge]);
    expect(h.onError).toHaveBeenCalledOnce();
  });

  it("deduplicates pending requests, but preserves distinct semantic roles", () => {
    const h = setup();
    act(() => {
      void h.result.current.submit(request);
      void h.result.current.submit(request);
      void h.result.current.submit({ ...request, input_role: "text_context" });
    });
    expect(h.createBinding).toHaveBeenCalledTimes(2);
    expect(h.result.current.displayEdges).toHaveLength(2);
    expect(h.createBinding.mock.calls[1][0].order).toBe(0);
    expect(h.result.current.nextOrder("target")).toBe(1);
  });

  it("preserves explicit and omitted order without rewriting the request", () => {
    const h = setup();
    act(() => {
      void h.result.current.submit({ ...request, order: 3 });
      void h.result.current.submit({ ...request, input_role: "text_context", order: 0 });
      const { order: _order, ...unordered } = request;
      void h.result.current.submit({ ...unordered, input_role: "video_reference" });
    });
    expect(h.createBinding.mock.calls.map(([input]) => input.order)).toEqual([3, 0, undefined]);
    expect(h.result.current.nextOrder("target")).toBe(4);
  });

  it("retires a confirmed preview when newer authority disables its Binding", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    h.rerender({ workflow: workflow("a", [{ ...binding, enabled: false }]), edges: [] });
    await act(async () => { h.pending.resolve(binding); });
    expect(h.result.current.displayEdges).toHaveLength(0);
    h.rerender({ workflow: workflow("a", [{ ...binding, enabled: false }]), edges: [] });
    expect(h.result.current.displayEdges).toHaveLength(0);
  });

  it("does not duplicate an SSE-confirmed edge while HTTP is still pending", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    h.rerender({ workflow: workflow("a", [binding]), edges: [edge] });
    expect(h.result.current.displayEdges).toEqual([edge]);
    act(() => { void h.result.current.submit(request); });
    expect(h.createBinding).toHaveBeenCalledOnce();
    await act(async () => { h.pending.resolve(binding); });
    expect(h.result.current.displayEdges).toEqual([edge]);
  });

  it("preserves pending edges across unrelated authoritative refreshes", () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    const temporary = h.result.current.displayEdges[0];
    h.rerender({ workflow: workflow(), edges: [] });
    expect(h.result.current.displayEdges[0]).toBe(temporary);
  });

  it("cancels on node deletion before authority refresh and fences its response", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    const guard = h.createBinding.mock.calls[0][1]!.isCurrent!;
    expect(guard()).toBe(true);
    act(() => h.result.current.cancelForNodes(["target"]));
    expect(guard()).toBe(false);
    expect(h.result.current.displayEdges).toHaveLength(0);
    await act(async () => { h.pending.resolve(binding); });
    expect(h.result.current.displayEdges).toHaveLength(0);
  });

  it("removes connections when endpoints vanish from authority", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    h.rerender({ workflow: workflow("a", [], ["source"]), edges: [] });
    expect(h.result.current.displayEdges).toHaveLength(0);
    await act(async () => { h.pending.reject(new Error("late failure")); });
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("does not revive an old operation after A/B/A navigation", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    const guard = h.createBinding.mock.calls[0][1]!.isCurrent!;
    h.rerender({ workflow: workflow("b"), edges: [] });
    h.rerender({ workflow: workflow("a"), edges: [] });
    expect(guard()).toBe(false);
    await act(async () => { h.pending.resolve(binding); });
    expect(h.result.current.displayEdges).toHaveLength(0);
  });

  it("invalidates the mutation guard on unmount", async () => {
    const h = setup();
    act(() => { void h.result.current.submit(request); });
    const guard = h.createBinding.mock.calls[0][1]!.isCurrent!;
    h.unmount();
    expect(guard()).toBe(false);
    await act(async () => { h.pending.reject(new Error("late failure")); });
    expect(h.onError).not.toHaveBeenCalled();
  });
});
