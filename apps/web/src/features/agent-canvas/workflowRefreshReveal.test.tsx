import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAgentCanvasNodeRevealQueue } from "./canvas/useAgentCanvasNodeRevealQueue.ts";
import {
  releaseWorkflowRefreshNodeFromEvent,
  reserveWorkflowRefreshNodes,
  workflowRefreshRevealNodeIds,
} from "./workflowRefreshReveal.ts";

afterEach(cleanup);

describe("workflowRefreshRevealNodeIds", () => {
  it("shows a plain node_created node when the later workflow refresh makes it canonical", () => {
    const plainCreatedNodeIds = new Set<string>();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: { current: null },
      onFocusNode: vi.fn(),
    }));

    act(() => {
      // The runtime callback releases the node before the refresh has arrived.
      releaseWorkflowRefreshNodeFromEvent(
        { event_type: "node_created", node_id: "video-1", payload: {} },
        plainCreatedNodeIds,
        result.current.releaseNodeIds,
      );
    });
    expect(result.current.visibleNodeIds).toEqual(new Set());

    act(() => {
      const nextNodes = [{ node_id: "video-1" }];
      result.current.reserveNodeIds(workflowRefreshRevealNodeIds([], nextNodes, plainCreatedNodeIds));
      result.current.syncCanonicalNodeIds(nextNodes.map((node) => node.node_id));
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["video-1"]));
  });

  it("keeps receipt-owned nodes hidden while revealing plain creations from the same refresh", () => {
    const plainCreatedNodeIds = new Set(["video-1"]);
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: { current: null },
      onFocusNode: vi.fn(),
    }));
    const currentNodes = [{ node_id: "existing" }];
    const nextNodes = [...currentNodes, { node_id: "video-1" }, { node_id: "receipt-1" }];

    act(() => {
      result.current.syncCanonicalNodeIds(["existing"]);
      result.current.reserveNodeIds(["receipt-1"]);
      result.current.reserveNodeIds(workflowRefreshRevealNodeIds(
        currentNodes,
        nextNodes,
        plainCreatedNodeIds,
      ));
      result.current.syncCanonicalNodeIds(nextNodes.map((node) => node.node_id));
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["existing", "video-1"]));
  });
});

describe("guided Editing node reveal", () => {
  const editingEventTypes = ["guided_editing_updated", "editing_prepared", "guided_editing_ready"];

  it.each(editingEventTypes)("reveals Editing after %s without a page reload or action receipt", (eventType) => {
    const immediateRevealNodeIds = new Set<string>();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: { current: null },
      onFocusNode: vi.fn(),
    }));
    const currentNodes = [{ node_id: "video-1" }, { node_id: "bgm-1" }];
    const nextNodes = [...currentNodes, { node_id: "editing-1" }, { node_id: "receipt-1" }];

    act(() => {
      result.current.syncCanonicalNodeIds(currentNodes.map((node) => node.node_id));
      releaseWorkflowRefreshNodeFromEvent(
        { event_type: eventType, node_id: "editing-1", payload: {} },
        immediateRevealNodeIds,
        result.current.releaseNodeIds,
      );
      reserveWorkflowRefreshNodes(currentNodes, nextNodes, immediateRevealNodeIds, result.current.reserveNodeIds);
      result.current.syncCanonicalNodeIds(nextNodes.map((node) => node.node_id));
    });

    expect(result.current.visibleNodeIds).toEqual(new Set(["video-1", "bgm-1", "editing-1"]));
    expect(result.current.pendingNodeIds).toEqual([]);
  });

  it.each(editingEventTypes)("releases an already hidden Editing node when %s arrives late or repeats", (eventType) => {
    const immediateRevealNodeIds = new Set<string>();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: { current: null },
      onFocusNode: vi.fn(),
    }));
    const currentNodes = [{ node_id: "video-1" }, { node_id: "bgm-1" }];
    const nextNodes = [...currentNodes, { node_id: "editing-1" }, { node_id: "receipt-1" }];

    act(() => {
      reserveWorkflowRefreshNodes(currentNodes, nextNodes, immediateRevealNodeIds, result.current.reserveNodeIds);
      result.current.syncCanonicalNodeIds(nextNodes.map((node) => node.node_id));
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["video-1", "bgm-1"]));

    act(() => {
      for (let repeat = 0; repeat < 2; repeat += 1) {
        releaseWorkflowRefreshNodeFromEvent(
          { event_type: eventType, node_id: "editing-1", payload: {} },
          immediateRevealNodeIds,
          result.current.releaseNodeIds,
        );
      }
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["video-1", "bgm-1", "editing-1"]));
  });

  it.each(["editing_prepared", "guided_editing_ready"])("accepts the Editing ID in the %s payload", (eventType) => {
    const releaseNodeIds = vi.fn();
    const immediateRevealNodeIds = new Set<string>();

    releaseWorkflowRefreshNodeFromEvent(
      { event_type: eventType, node_id: null, payload: { editing_node_id: "editing-1" } },
      immediateRevealNodeIds,
      releaseNodeIds,
    );

    expect(immediateRevealNodeIds).toEqual(new Set(["editing-1"]));
    expect(releaseNodeIds).toHaveBeenCalledWith(["editing-1"]);
  });

  it("keeps Editing visible when consecutive event refreshes finish before React renders the workflow", () => {
    const immediateRevealNodeIds = new Set<string>();
    const { result } = renderHook(() => useAgentCanvasNodeRevealQueue({
      workflowId: "workflow-1",
      flowRef: { current: null },
      onFocusNode: vi.fn(),
    }));
    const currentNodes = [{ node_id: "video-1" }, { node_id: "bgm-1" }];
    const nextNodes = [...currentNodes, { node_id: "editing-1" }, { node_id: "receipt-1" }];

    act(() => {
      result.current.syncCanonicalNodeIds(currentNodes.map((node) => node.node_id));
      for (const eventType of editingEventTypes) {
        releaseWorkflowRefreshNodeFromEvent(
          { event_type: eventType, node_id: "editing-1", payload: {} },
          immediateRevealNodeIds,
          result.current.releaseNodeIds,
        );
      }
      // Both responses can complete before React commits the new workflow.
      reserveWorkflowRefreshNodes(currentNodes, nextNodes, immediateRevealNodeIds, result.current.reserveNodeIds);
      reserveWorkflowRefreshNodes(currentNodes, nextNodes, immediateRevealNodeIds, result.current.reserveNodeIds);
      result.current.syncCanonicalNodeIds(nextNodes.map((node) => node.node_id));
    });
    expect(result.current.visibleNodeIds).toEqual(new Set(["video-1", "bgm-1", "editing-1"]));

    act(() => {
      reserveWorkflowRefreshNodes(nextNodes, nextNodes, immediateRevealNodeIds, result.current.reserveNodeIds);
      result.current.syncCanonicalNodeIds(nextNodes.map((node) => node.node_id));
    });
    expect(immediateRevealNodeIds.size).toBe(0);
    expect(result.current.visibleNodeIds).toEqual(new Set(["video-1", "bgm-1", "editing-1"]));
  });

  it.each([
    { event_type: "action_receipt_created", node_id: "receipt-1", payload: {} },
    { event_type: "node_ready", node_id: "video-1", payload: { editing_node_id: "editing-1" } },
    { event_type: "editing_prepared", node_id: null, payload: {} },
    { event_type: "guided_editing_ready", node_id: null, payload: { editing_node_id: 42 } },
  ])("keeps receipt placement intact and ignores events without an Editing ID: $event_type", (event) => {
    const immediateRevealNodeIds = new Set<string>();
    const releaseNodeIds = vi.fn();

    releaseWorkflowRefreshNodeFromEvent(event, immediateRevealNodeIds, releaseNodeIds);

    expect(immediateRevealNodeIds.size).toBe(0);
    expect(releaseNodeIds).not.toHaveBeenCalled();
  });
});
