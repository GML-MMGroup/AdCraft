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
  uploadFilesWithReceipts: vi.fn(),
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
    uploadFilesWithReceipts: fixture.uploadFilesWithReceipts,
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
    fixture.uploadFilesWithReceipts.mockReset();
    fixture.items = [];
    sessionStorage.clear();
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
    fixture.uploadFilesWithReceipts.mockResolvedValue([{
      workflow_id: "workflow-1",
      asset: uploaded,
      pending_handoff_id: null,
    }]);
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

    expect(fixture.uploadFilesWithReceipts).toHaveBeenCalledOnce();
    expect(result.current.selectedAssetIds).toEqual(["uploaded"]);
    expect(result.current.view.assets[0]?.displayName).toBe("Asset uploaded");
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("stores a Product Main handoff only after the user explicitly chooses that upload role", async () => {
    const uploaded = {
      ...asset("uploaded-product"),
      version_id: "version-product-1",
    };
    fixture.uploadFilesWithReceipts.mockResolvedValue([{
      workflow_id: "workflow-1",
      asset: uploaded,
      pending_handoff_id: "handoff-product-1",
    }]);
    const { result } = renderHook(() => useComposerContext({ workflow: workflow() }));

    await act(async () => {
      await result.current.actions.upload([
        new File(["image"], "product.png", { type: "image/png" }),
      ], { semanticRole: "product_main" });
    });

    expect(fixture.uploadFilesWithReceipts).toHaveBeenCalledWith(
      expect.anything(),
      { semanticRole: "product_main" },
    );
    expect(result.current.productMainHandoff).toEqual({
      workflowId: "workflow-1",
      assetId: "uploaded-product",
      versionId: "version-product-1",
      pendingHandoffId: "handoff-product-1",
      displayName: "Asset uploaded-product",
      previewUrl: "/api/v2/assets/uploaded-product/content?v=version-product-1",
    });
  });

  it("does not infer Product Main from an unclassified upload", async () => {
    fixture.uploadFilesWithReceipts.mockResolvedValue([{
      workflow_id: "workflow-1",
      asset: { ...asset("unclassified"), version_id: "version-unclassified-1" },
      pending_handoff_id: null,
    }]);
    const { result } = renderHook(() => useComposerContext({ workflow: workflow() }));

    await act(async () => {
      await result.current.actions.upload([
        new File(["image"], "reference.png", { type: "image/png" }),
      ]);
    });

    expect(result.current.productMainHandoff).toBeNull();
  });

  it("projects failed uploads locally and preserves existing selections", async () => {
    fixture.uploadFilesWithReceipts.mockRejectedValue(new Error("Request failed with status 503"));
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
