import { describe, expect, it } from "vitest";

import { normalizeWorkflowAssetListResponseV2 } from "../api/v2Normalizers.ts";
import type { WorkflowAssetListRowV2 } from "../types-v2.ts";
import { resolveV2ProjectCover } from "./v2ProjectCover.ts";

describe("resolveV2ProjectCover", () => {
  it("uses the newest generated product image instead of non-product media", () => {
    const cover = resolveV2ProjectCover("scene-cover", [
      asset({
        asset_id: "scene-cover",
        version_id: "scene-version",
        semantic_type: "scene_reference_board",
        node_id: "scene-node",
        created_at: "2026-08-25T11:00:00Z",
      }),
      asset({
        asset_id: "older-product",
        version_id: "z-older-version",
        semantic_type: "product_main",
        node_id: "product-main",
        created_at: "2026-08-24T11:00:00Z",
      }),
      asset({
        asset_id: "newer-product",
        version_id: "a-newer-version",
        semantic_type: "product_packshot",
        node_id: "product-packshot",
        created_at: "2026-08-25T10:00:00Z",
      }),
      asset({
        asset_id: "final-video",
        version_id: "final-version",
        media_type: "video",
        semantic_type: "final_composition",
        node_id: "final-composition",
        created_at: "2026-08-25T12:00:00Z",
      }),
    ]);

    expect(cover?.assetId).toBe("newer-product");
    expect(cover?.mediaType).toBe("image");
  });

  it("uses canonical media URLs returned by the workflow asset list", () => {
    const response = normalizeWorkflowAssetListResponseV2({
      workflow_id: "workflow-1",
      assets: [{
        asset_id: "product-asset",
        version_id: "product-version",
        media_type: "image",
        source_type: "generated",
        semantic_type: "product",
        status: "ready",
        media_url: "/api/v2/assets/product-asset/content",
        preview_url: "/api/v2/assets/product-asset/content",
        created_at: "2026-08-25T10:00:00Z",
      }],
    });

    expect(resolveV2ProjectCover(null, response.assets)?.mediaPath).toBe("/api/v2/assets/product-asset/content?v=product-version");
  });
});

function asset(overrides: Partial<WorkflowAssetListRowV2>): WorkflowAssetListRowV2 {
  return {
    asset_id: "asset",
    version_id: "version",
    media_type: "image",
    source_type: "generated",
    public_url: "/api/v2/assets/asset/content",
    semantic_type: "product_main",
    state: "selected",
    status: "ready",
    ...overrides,
  };
}
