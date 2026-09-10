import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";

const posterApi = vi.hoisted(() => ({
  loadVideoPosterRecordForAsset: vi.fn(),
}));

vi.mock("../../../workflow/videoPosterCache.ts", () => posterApi);

import { useAgentCanvasVideoPoster } from "./useAgentCanvasVideoPoster.ts";

const asset = {
  asset_id: "asset-video",
  version_id: "version-video-1",
  workflow_id: "workflow-1",
  project_id: "project-1",
  media_type: "video",
  preview_url: null,
  media_url: "/api/v2/assets/asset-video/content",
  checksum: "checksum-video-1",
  created_at: "2026-09-03T00:00:00Z",
  display_name: "Video output",
} as ProjectAssetSummaryV2;

describe("useAgentCanvasVideoPoster", () => {
  beforeEach(() => {
    posterApi.loadVideoPosterRecordForAsset.mockResolvedValue({ poster_blob: new Blob(["poster"]) });
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:video-poster"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reuses the same generated poster URL after a node remount", async () => {
    const first = renderHook(() => useAgentCanvasVideoPoster(asset));
    await waitFor(() => expect(first.result.current).toBe("blob:video-poster"));
    first.unmount();

    const second = renderHook(() => useAgentCanvasVideoPoster(asset));
    await waitFor(() => expect(second.result.current).toBe("blob:video-poster"));

    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(posterApi.loadVideoPosterRecordForAsset).toHaveBeenCalledTimes(2);

    const nextAsset = { ...asset, version_id: "version-video-2" };
    const next = renderHook(() => useAgentCanvasVideoPoster(nextAsset));
    await waitFor(() => expect(next.result.current).toBe("blob:video-poster"));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
    next.unmount();
    second.unmount();
  });
});
