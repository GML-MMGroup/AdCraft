import { describe, expect, it } from "vitest";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { resolvePublishedAssets } from "./publishedAssets.ts";

function asset(assetId: string): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    media_type: "image",
    source_type: "generated",
    display_name: assetId,
    mime_type: "image/jpeg",
    status: "ready",
    preview_url: `/api/v2/assets/${assetId}/content`,
    media_url: `/api/v2/assets/${assetId}/content`,
    width: 1024,
    height: 1024,
    duration_seconds: null,
    checksum: `${assetId}-checksum`,
  };
}

describe("resolvePublishedAssets", () => {
  it("resolves every queued publication from one canonical asset response", () => {
    const result = resolvePublishedAssets(
      [asset("asset-1"), asset("asset-2")],
      new Map([
        ["asset-1", "node-1"],
        ["asset-2", "node-2"],
      ]),
    );

    expect(result.matches.map((match) => [match.asset.asset_id, match.nodeId])).toEqual([
      ["asset-1", "node-1"],
      ["asset-2", "node-2"],
    ]);
    expect(result.unresolvedAssetIds).toEqual([]);
  });
});
