import { describe, expect, it } from "vitest";

import type {
  ActiveStyleSkillSummaryV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../../types-v2.ts";
import { buildComposerContextView, hasComposerContext } from "./composerContext.ts";

const style = {
  skill_run_id: "run-secret",
  skill_id: "skill-secret",
  skill_version: "3.4.5",
  title: "Quiet Product Film",
  summary: "Restrained product cinematography.",
  category: "commercial",
  creative_direction_snapshot_id: "snapshot-secret",
} as ActiveStyleSkillSummaryV2;

const assets = [{
  asset_id: "asset-1",
  display_name: "Hero bottle",
  media_type: "image",
  preview_url: "/preview/asset-1",
  media_url: "/content/asset-1",
  storage_key: "secret/storage/key",
  provider: "secret-provider",
}, {
  asset_id: "asset-2",
  display_name: "Second image",
  media_type: "image",
  preview_url: null,
  media_url: "/content/asset-2",
}] as ProjectAssetSummaryV2[];

const nodes = [{
  node_id: "node-1",
  title: "Product Main",
  node_type: "image",
  revision: 42,
}, {
  node_id: "node-2",
  title: "World Setting",
  node_type: "text",
}] as CanvasNodeV2[];

describe("buildComposerContextView", () => {
  it("deduplicates selected authority IDs and exposes display-safe fields only", () => {
    const view = buildComposerContextView({
      activeStyle: style,
      assets,
      nodes,
      selectedAssetIds: ["asset-2", "asset-1", "asset-2"],
      selectedNodeIds: ["node-1", "node-1", "node-2"],
      uploadState: "idle",
    });

    expect(view).toEqual({
      skill: {
        title: "Quiet Product Film",
        summary: "Restrained product cinematography.",
      },
      assets: [{
        assetId: "asset-2",
        displayName: "Second image",
        mediaType: "image",
        thumbnailUrl: "/content/asset-2",
      }, {
        assetId: "asset-1",
        displayName: "Hero bottle",
        mediaType: "image",
        thumbnailUrl: "/content/asset-1",
      }],
      nodes: [{ nodeId: "node-1", title: "Product Main", nodeType: "image" },
        { nodeId: "node-2", title: "World Setting", nodeType: "text" }],
      uploadState: "idle",
    });
    expect(JSON.stringify(view)).not.toMatch(/run-secret|skill-secret|3\.4\.5|storage|provider|revision/i);
  });

  it("drops selections that no longer exist in workflow authority", () => {
    const view = buildComposerContextView({
      activeStyle: null,
      assets,
      nodes,
      selectedAssetIds: ["missing"],
      selectedNodeIds: ["missing"],
      uploadState: "idle",
    });

    expect(view).toEqual({ skill: null, assets: [], nodes: [], uploadState: "idle" });
    expect(hasComposerContext(view)).toBe(false);
  });

  it("keeps upload activity visible even without selected context", () => {
    const view = buildComposerContextView({
      activeStyle: null,
      assets: [],
      nodes: [],
      selectedAssetIds: [],
      selectedNodeIds: [],
      uploadState: "uploading",
    });

    expect(hasComposerContext(view)).toBe(true);
  });
});
