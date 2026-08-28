import { describe, expect, it } from "vitest";

import type { AgentAssetBrowserItem } from "./assetSelection.ts";
import { toImageBindingSource, toSourceNodeSelection } from "./assetSelection.ts";

describe("toSourceNodeSelection", () => {
  it("preserves image dimensions for adaptive Ready source-node sizing", () => {
    const item: AgentAssetBrowserItem = {
      id: "project:asset-1",
      assetId: "asset-1",
      source: "project",
      mediaType: "image",
      displayName: "Portrait reference",
      previewUrl: "/portrait-preview.webp",
      mediaUrl: "/portrait.webp",
      status: "ready",
      tags: [],
      identity: {
        source: "project",
        assetId: "asset-1",
        entityId: null,
        versionId: null,
      },
      projectAsset: {
        asset_id: "asset-1",
        project_id: "project-1",
        workflow_id: "workflow-1",
        media_type: "image",
        source_type: "uploaded",
        display_name: "Portrait reference",
        mime_type: "image/webp",
        status: "ready",
        size_bytes: 0,
        storage_key: null,
        preview_url: "/portrait-preview.webp",
        media_url: "/portrait.webp",
        width: 1080,
        height: 1920,
        duration_seconds: null,
        checksum: "portrait",
        source_semantic_role: null,
        source_node_id: null,
        source_execution_id: null,
        provider: null,
        model_id: null,
        prompt_provenance: {},
        quality_metadata: {},
        created_at: "2026-08-05T00:00:00Z",
      },
    };

    expect(toSourceNodeSelection(item)).toMatchObject({
      assetId: "asset-1",
      mediaType: "image",
      width: 1080,
      height: 1920,
    });
  });
});

describe("toImageBindingSource", () => {
  it("requires and preserves the immutable AssetVersion identity", () => {
    expect(toImageBindingSource({
      source: "project",
      assetId: "asset-product-1",
      entityId: null,
      versionId: "version-product-1",
      mediaType: "image",
      displayName: "Product main",
    })).toEqual({
      kind: "image_asset",
      source_asset_id: "asset-product-1",
      source_asset_version_id: "version-product-1",
    });
  });

  it("rejects a new image binding when the AssetVersion is unavailable", () => {
    expect(() => toImageBindingSource({
      source: "project",
      assetId: "legacy-asset",
      entityId: null,
      versionId: null,
      mediaType: "image",
      displayName: "Legacy image",
    })).toThrowError(/immutable asset version/i);
  });
});
