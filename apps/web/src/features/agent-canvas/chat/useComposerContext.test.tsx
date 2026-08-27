import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { useComposerContext } from "./useComposerContext.ts";

const fixture = vi.hoisted(() => ({
  uploadFiles: vi.fn(),
  items: [] as Array<{ projectAsset: ProjectAssetSummaryV2 | null }>,
}));

vi.mock("../assets/useAgentCanvasAssets.ts", () => ({
  useAgentCanvasAssets: () => ({
    items: fixture.items,
    loading: false,
    error: null,
    uploading: false,
    uploadError: null,
    retry: vi.fn(),
    uploadFiles: fixture.uploadFiles,
  }),
}));

function asset(assetId: string): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    display_name: `Asset ${assetId}`,
    media_type: "image",
    preview_url: `/preview/${assetId}`,
    media_url: `/content/${assetId}`,
  } as ProjectAssetSummaryV2;
}

function node(nodeId: string): CanvasNodeV2 {
  return {
    node_id: nodeId,
    title: `Node ${nodeId}`,
    node_type: "image",
  } as CanvasNodeV2;
}

function workflow(workflowId = "workflow-1"): AgentCanvasWorkflowV2 {
  return {
    workflow_id: workflowId,
    nodes: [node("node-1")],
    assets: [asset("asset-1")],
    active_style_skill: {
      title: "Quiet Product Film",
      summary: "Restrained product cinematography.",
    },
  } as AgentCanvasWorkflowV2;
}

describe("useComposerContext", () => {
  beforeEach(() => {
    fixture.uploadFiles.mockReset();
    fixture.items = [];
  });

  it("toggles and removes message-scoped IDs without duplicates", () => {
    const { result } = renderHook(() => useComposerContext({ workflow: workflow() }));

    act(() => {
      result.current.actions.toggleNode("node-1");
      result.current.actions.toggleAsset("asset-1");
    });
    expect(result.current.selectedNodeIds).toEqual(["node-1"]);
    expect(result.current.selectedAssetIds).toEqual(["asset-1"]);

    act(() => {
      result.current.actions.removeNode("node-1");
      result.current.actions.removeAsset("asset-1");
    });
    expect(result.current.selectedNodeIds).toEqual([]);
    expect(result.current.selectedAssetIds).toEqual([]);
  });

  it("adds successful image uploads to context and refreshes workflow authority", async () => {
    const uploaded = asset("uploaded");
    fixture.uploadFiles.mockResolvedValue([uploaded]);
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useComposerContext({
      workflow: workflow(),
      onWorkflowRefresh: refresh,
    }));

    await act(async () => {
      await result.current.actions.upload([
        new File(["image"], "hero.png", { type: "image/png" }),
      ]);
    });

    expect(fixture.uploadFiles).toHaveBeenCalledOnce();
    expect(result.current.selectedAssetIds).toEqual(["uploaded"]);
    expect(result.current.view.assets[0]?.displayName).toBe("Asset uploaded");
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("projects failed uploads locally and preserves existing selections", async () => {
    fixture.uploadFiles.mockRejectedValue(new Error("Request failed with status 503"));
    const { result } = renderHook(() => useComposerContext({ workflow: workflow() }));
    act(() => result.current.actions.toggleAsset("asset-1"));

    await act(async () => {
      await result.current.actions.upload([
        new File(["image"], "hero.png", { type: "image/png" }),
      ]);
    });

    expect(result.current.selectedAssetIds).toEqual(["asset-1"]);
    expect(result.current.view.uploadState).toBe("failed");
    expect(result.current.uploadIssue).toMatchObject({ scope: "context", action: "none" });
  });

  it("clears message context without clearing the workflow Skill", () => {
    const { result } = renderHook(() => useComposerContext({ workflow: workflow() }));
    act(() => {
      result.current.actions.toggleNode("node-1");
      result.current.actions.toggleAsset("asset-1");
      result.current.actions.clearMessageContext();
    });

    expect(result.current.view.skill?.title).toBe("Quiet Product Film");
    expect(result.current.view.assets).toEqual([]);
    expect(result.current.view.nodes).toEqual([]);
  });

  it("consumes only context included in an accepted request", () => {
    const { result } = renderHook(() => useComposerContext({ workflow: {
      ...workflow(),
      nodes: [node("node-1"), node("node-2")],
      assets: [asset("asset-1"), asset("asset-2")],
    } }));
    act(() => {
      result.current.actions.toggleNode("node-1");
      result.current.actions.toggleAsset("asset-1");
      result.current.actions.toggleNode("node-2");
      result.current.actions.toggleAsset("asset-2");
      result.current.actions.consumeSubmittedContext({
        nodeIds: ["node-1"],
        assetIds: ["asset-1"],
      });
    });

    expect(result.current.selectedNodeIds).toEqual(["node-2"]);
    expect(result.current.selectedAssetIds).toEqual(["asset-2"]);
  });

  it("drops transient context when switching workflow authority", async () => {
    const { result, rerender } = renderHook(
      ({ current }) => useComposerContext({ workflow: current }),
      { initialProps: { current: workflow("workflow-1") } },
    );
    act(() => {
      result.current.actions.toggleNode("node-1");
      result.current.actions.toggleAsset("asset-1");
    });

    rerender({ current: { ...workflow("workflow-2"), nodes: [], assets: [] } });
    await waitFor(() => expect(result.current.selectedNodeIds).toEqual([]));
    expect(result.current.selectedAssetIds).toEqual([]);
    expect(result.current.view.uploadState).toBe("idle");
  });
});
