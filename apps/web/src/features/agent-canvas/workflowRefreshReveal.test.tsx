import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAgentCanvasNodeRevealQueue } from "./canvas/useAgentCanvasNodeRevealQueue.ts";
import { workflowRefreshRevealNodeIds } from "./workflowRefreshReveal.ts";

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
      plainCreatedNodeIds.add("video-1");
      result.current.releaseNodeIds(["video-1"]);
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
