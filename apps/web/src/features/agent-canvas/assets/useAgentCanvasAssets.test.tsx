import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { useAgentCanvasAssets } from "./useAgentCanvasAssets.ts";

const fixture = vi.hoisted(() => ({
  listAgentCanvasProjectAssets: vi.fn(),
  listAgentCanvasMyAssets: vi.fn(),
  listAgentCanvasRecommendedAssets: vi.fn(),
  uploadAgentCanvasAsset: vi.fn(),
}));

vi.mock("../../../api/v2Client.ts", () => ({
  v2Api: fixture,
}));

function projectAsset(
  assetId: string,
  mediaType: "image" | "video" | "audio",
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    version_id: `${assetId}-version`,
    media_type: mediaType,
    source_type: "upload",
    display_name: `${mediaType} ${assetId}`,
    mime_type: `${mediaType}/${mediaType === "image" ? "png" : "mp4"}`,
    status: "ready",
    preview_url: mediaType === "image" ? `/media/${assetId}.png` : null,
    media_url: `/media/${assetId}`,
    width: mediaType === "audio" ? null : 1280,
    height: mediaType === "audio" ? null : 720,
    duration_seconds: mediaType === "image" ? null : 8,
    checksum: `${assetId}-checksum`,
  };
}

function libraryAsset(scope: "my" | "recommended", entityId: string) {
  return {
    entity_id: entityId,
    scope,
    entity_type: "character",
    library_category: "characters",
    display_name: `${scope} ${entityId}`,
    tags: [],
    is_favorite: false,
    member_count: 1,
    preview_url: `/library/${entityId}.png`,
    preview_member: {
      member_id: `${entityId}-member`,
      semantic_type: "reference",
      asset_id: `${entityId}-asset`,
      version_id: `${entityId}-version`,
      media_type: "image",
      public_url: `/library/${entityId}.png`,
    },
  };
}

describe("useAgentCanvasAssets", () => {
  beforeEach(() => {
    fixture.listAgentCanvasProjectAssets.mockReset();
    fixture.listAgentCanvasMyAssets.mockReset();
    fixture.listAgentCanvasRecommendedAssets.mockReset();
    fixture.uploadAgentCanvasAsset.mockReset();
    fixture.listAgentCanvasProjectAssets.mockResolvedValue({
      workflow_id: "workflow-1",
      assets: [],
    });
    fixture.listAgentCanvasMyAssets.mockResolvedValue({ items: [] });
    fixture.listAgentCanvasRecommendedAssets.mockResolvedValue({ items: [] });
  });

  it("loads each scope from the Agent Canvas API and keeps My and Recommended image-only", async () => {
    fixture.listAgentCanvasProjectAssets.mockResolvedValue({
      workflow_id: "workflow-1",
      assets: [
        projectAsset("project-image", "image"),
        projectAsset("project-video", "video"),
        projectAsset("project-audio", "audio"),
      ],
    });
    fixture.listAgentCanvasMyAssets.mockResolvedValue({
      items: [
        libraryAsset("my", "portrait"),
        {
          ...libraryAsset("my", "not-an-image"),
          preview_member: {
            ...libraryAsset("my", "not-an-image").preview_member,
            media_type: "video",
          },
        },
      ],
    });
    fixture.listAgentCanvasRecommendedAssets.mockResolvedValue({
      items: [libraryAsset("recommended", "scene")],
    });

    const { result, rerender } = renderHook(
      ({ scope }) => useAgentCanvasAssets({ workflowId: "workflow-1", scope }),
      { initialProps: { scope: "project" as const } },
    );

    await waitFor(() => expect(result.current.items).toHaveLength(3));
    expect(result.current.items.map((item) => item.mediaType)).toEqual(["image", "video", "audio"]);
    expect(result.current.items[0]?.identity.versionId).toBe("project-image-version");

    rerender({ scope: "my" });
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(fixture.listAgentCanvasMyAssets).toHaveBeenCalledWith(null);
    expect(result.current.items[0]?.identity).toEqual({
      source: "my",
      assetId: "portrait-asset",
      entityId: "portrait",
      versionId: "portrait-version",
    });

    rerender({ scope: "recommended" });
    await waitFor(() => expect(result.current.items[0]?.id).toBe("recommended:scene"));
    expect(fixture.listAgentCanvasRecommendedAssets).toHaveBeenCalledWith(null);
  });

  it("filters by media type and case-insensitive search without making another request", async () => {
    fixture.listAgentCanvasProjectAssets.mockResolvedValue({
      workflow_id: "workflow-1",
      assets: [
        projectAsset("hero-still", "image"),
        { ...projectAsset("launch-film", "video"), display_name: "Launch Film" },
        projectAsset("theme-song", "audio"),
      ],
    });
    const { result, rerender } = renderHook(
      ({ mediaType, search }) => useAgentCanvasAssets({
        workflowId: "workflow-1",
        scope: "project",
        mediaType,
        search,
      }),
      {
        initialProps: {
          mediaType: "all" as const,
          search: "",
        },
      },
    );

    await waitFor(() => expect(result.current.items).toHaveLength(3));
    rerender({ mediaType: "video", search: "launch" });

    expect(result.current.items.map((item) => item.assetId)).toEqual(["launch-film"]);
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledTimes(1);
  });

  it("defers project asset loading until the caller enables the browser", async () => {
    const { result, rerender } = renderHook(
      ({ enabled }) => useAgentCanvasAssets({
        workflowId: "workflow-1",
        scope: "project",
        mediaType: "image",
        enabled,
      }),
      { initialProps: { enabled: false } },
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fixture.listAgentCanvasProjectAssets).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() => expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledOnce());

    rerender({ enabled: false });
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fixture.listAgentCanvasProjectAssets).toHaveBeenCalledOnce();
  });

  it("uploads multipart file metadata, refreshes project assets, and never persists file data", async () => {
    const uploaded = projectAsset("uploaded-video", "video");
    fixture.uploadAgentCanvasAsset.mockResolvedValue({
      workflow_id: "workflow-1",
      asset: uploaded,
    });
    fixture.listAgentCanvasProjectAssets
      .mockResolvedValueOnce({ workflow_id: "workflow-1", assets: [] })
      .mockResolvedValueOnce({ workflow_id: "workflow-1", assets: [uploaded] });
    const { result } = renderHook(() => useAgentCanvasAssets({
      workflowId: "workflow-1",
      scope: "project",
    }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const file = new File(["video"], "launch.mp4", { type: "video/mp4" });

    await act(async () => {
      await result.current.uploadFiles([file], {
        semanticRole: "reference_video",
        metadata: { origin: "asset-picker" },
      });
    });

    expect(fixture.uploadAgentCanvasAsset).toHaveBeenCalledTimes(1);
    const [workflowId, formData, idempotencyKey] =
      fixture.uploadAgentCanvasAsset.mock.calls[0] as [string, FormData, string];
    expect(workflowId).toBe("workflow-1");
    expect(formData.get("file")).toBe(file);
    expect(JSON.parse(String(formData.get("metadata")))).toEqual({
      media_type: "video",
      title: "launch",
      semantic_role: "reference_video",
      metadata: { origin: "asset-picker" },
    });
    expect(idempotencyKey).toMatch(/^asset-upload-/);
    expect(result.current.items.map((item) => item.assetId)).toEqual(["uploaded-video"]);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("returns the full Product upload handoff and honors caller-owned stable idempotency keys", async () => {
    const uploaded = {
      ...projectAsset("uploaded-product", "image"),
      version_id: "version-product-1",
    };
    fixture.uploadAgentCanvasAsset.mockResolvedValue({
      workflow_id: "workflow-1",
      asset: uploaded,
      pending_handoff_id: "handoff-product-1",
    });
    const { result } = renderHook(() => useAgentCanvasAssets({
      workflowId: "workflow-1",
      scope: "project",
    }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const file = new File(["image"], "product.png", { type: "image/png" });
    let receipts: Awaited<ReturnType<typeof result.current.uploadFilesWithReceipts>> = [];

    await act(async () => {
      receipts = await result.current.uploadFilesWithReceipts(
        [file],
        { semanticRole: "product_main" },
        ["product-upload-stable-1"],
      );
    });

    expect(fixture.uploadAgentCanvasAsset).toHaveBeenCalledWith(
      "workflow-1",
      expect.any(FormData),
      "product-upload-stable-1",
    );
    expect(receipts[0]).toMatchObject({
      pending_handoff_id: "handoff-product-1",
      asset: { asset_id: "uploaded-product", version_id: "version-product-1" },
    });
  });

  it("exposes a bounded error and retries the current scope", async () => {
    fixture.listAgentCanvasProjectAssets
      .mockRejectedValueOnce(new Error("Project assets unavailable"))
      .mockResolvedValueOnce({
        workflow_id: "workflow-1",
        assets: [projectAsset("recovered", "image")],
      });
    const { result } = renderHook(() => useAgentCanvasAssets({
      workflowId: "workflow-1",
      scope: "project",
    }));

    await waitFor(() => expect(result.current.error).toBe("Project assets unavailable"));
    await act(async () => {
      await result.current.retry();
    });

    expect(result.current.error).toBeNull();
    expect(result.current.items[0]?.assetId).toBe("recovered");
  });
});
