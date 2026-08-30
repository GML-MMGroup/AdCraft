import { describe, expect, it } from "vitest";

import { normalizeProjectAssetListResponseV2 } from "../features/agent-canvas/model/normalizers.ts";
import type { CanvasNodeV2, ProjectAssetSummaryV2 } from "../types-v2.ts";
import { needsV2ProjectCoverNodeAuthority, resolveV2ProjectCover } from "./v2ProjectCover.ts";

describe("resolveV2ProjectCover", () => {
  it("uses Product Main even when a newer Product Multi-view is the explicit cover", () => {
    const cover = resolveV2ProjectCover("product-multiview", [
      asset({
        asset_id: "scene-cover",
        version_id: "scene-version",
        semantic_type: "scene",
        source_semantic_role: "scene",
        created_at: "2026-08-25T11:00:00Z",
      }),
      asset({
        asset_id: "product-main",
        version_id: "product-main-version",
        semantic_type: "product",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: [] },
        created_at: "2026-08-24T11:00:00Z",
      }),
      asset({
        asset_id: "product-multiview",
        version_id: "product-multiview-version",
        semantic_type: "product",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: ["product-main-version"] },
        created_at: "2026-08-25T10:00:00Z",
      }),
      asset({
        asset_id: "final-video",
        version_id: "final-version",
        media_type: "video",
        semantic_type: "final_composition",
        source_semantic_role: "final_composition",
        created_at: "2026-08-25T12:00:00Z",
      }),
    ]);

    expect(cover?.assetId).toBe("product-main");
    expect(cover?.mediaType).toBe("image");
  });

  it("uses canonical media URLs returned by the Agent Canvas asset list", () => {
    const response = normalizeProjectAssetListResponseV2({
      workflow_id: "workflow-1",
      assets: [{
        asset_id: "product-asset",
        version_id: "product-version",
        project_id: "project-1",
        workflow_id: "workflow-1",
        media_type: "image",
        source_type: "generated",
        semantic_type: "product",
        status: "ready",
        display_name: "Product Main",
        mime_type: "image/jpeg",
        size_bytes: 1024,
        storage_key: "assets/product.jpg",
        media_url: "/api/v2/assets/product-asset/content",
        preview_url: "/api/v2/assets/product-asset/preview",
        width: 2048,
        height: 2048,
        duration_seconds: null,
        checksum: "product-checksum",
        source_semantic_role: "product_main",
        source_node_id: "product-main-node",
        source_execution_id: "product-execution",
        provider: "image-provider",
        model_id: "image-model",
        prompt_provenance: {},
        actual_media_facts: {},
        generation_provenance: { source_asset_version_ids: [] },
        quality_metadata: {},
        created_at: "2026-08-25T10:00:00Z",
      }],
    });

    expect(resolveV2ProjectCover(null, response.assets)?.mediaPath).toBe("/api/v2/assets/product-asset/content?v=product-version");
  });

  it("retains an existing preview rendition separately from the immutable content path", () => {
    const cover = resolveV2ProjectCover(null, [asset({
      asset_id: "product-asset",
      version_id: "version",
      preview_url: "/api/v2/assets/product-asset/preview",
      media_url: "/api/v2/assets/product-asset/content",
    })]);

    expect(cover?.previewPath).toBe("/api/v2/assets/product-asset/preview?v=version");
    expect(cover?.mediaPath).toBe("/api/v2/assets/product-asset/content?v=version");
  });

  it("uses source node authority when Product Main also consumes image references", () => {
    const assets = [
      asset({
        asset_id: "product-main",
        version_id: "product-main-version",
        source_node_id: "product-main-node",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: ["reference-version"] },
        created_at: "2026-08-24T11:00:00Z",
      }),
      asset({
        asset_id: "product-multiview",
        version_id: "product-multiview-version",
        source_node_id: "product-multiview-node",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: ["product-main-version"] },
        created_at: "2026-08-25T11:00:00Z",
      }),
    ];
    const nodes = [
      sourceNode("product-main-node", "adcraft.agent_canvas.product_main"),
      sourceNode("product-multiview-node", "adcraft.agent_canvas.product_multiview"),
    ];

    expect(resolveV2ProjectCover(null, assets, nodes)?.assetId).toBe("product-main");
  });

  it("does not load node authority when exactly one coarse product asset is a provenance root", () => {
    const assets = [
      asset({
        asset_id: "product-main",
        version_id: "product-main-version",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: [] },
      }),
      asset({
        asset_id: "product-multiview",
        version_id: "product-multiview-version",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: ["product-main-version"] },
      }),
    ];

    expect(needsV2ProjectCoverNodeAuthority(assets)).toBe(false);
  });

  it("loads node authority when a newer product asset does not derive from the provenance root", () => {
    const assets = [
      asset({
        asset_id: "older-product-main",
        version_id: "older-product-main-version",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: [] },
      }),
      asset({
        asset_id: "newer-product-main",
        version_id: "newer-product-main-version",
        source_semantic_role: "product",
        generation_provenance: { source_asset_version_ids: ["reference-version"] },
      }),
    ];

    expect(needsV2ProjectCoverNodeAuthority(assets)).toBe(true);
  });
});

function sourceNode(nodeId: string, promptRecipeId: string): CanvasNodeV2 {
  return {
    node_id: nodeId,
    metadata: { prompt_recipe_id: promptRecipeId },
  } as CanvasNodeV2;
}

function asset(overrides: Partial<ProjectAssetSummaryV2>): ProjectAssetSummaryV2 {
  return {
    asset_id: "asset",
    version_id: "version",
    project_id: "project",
    workflow_id: "workflow",
    media_type: "image",
    source_type: "generated",
    semantic_type: "product",
    display_name: "Product",
    mime_type: "image/jpeg",
    status: "ready",
    size_bytes: 1024,
    storage_key: "assets/product.jpg",
    preview_url: "/api/v2/assets/asset/content",
    media_url: "/api/v2/assets/asset/content",
    width: 2048,
    height: 2048,
    duration_seconds: null,
    checksum: "checksum",
    source_semantic_role: "product_main",
    source_node_id: "product-node",
    source_execution_id: "execution",
    provider: "image-provider",
    model_id: "image-model",
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: { source_asset_version_ids: [] },
    quality_metadata: {},
    created_at: "2026-08-25T10:00:00Z",
    ...overrides,
  };
}
