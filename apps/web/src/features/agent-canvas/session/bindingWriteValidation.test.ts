import { describe, expect, it } from "vitest";

import type { CanvasBindingCreateRequestV2 } from "../../../types-v2.ts";
import { assertValidCanvasBindingWrite } from "./bindingWriteValidation.ts";

function imageBinding(
  sourceAssetId: string,
  sourceAssetVersionId: string,
): CanvasBindingCreateRequestV2 {
  return {
    source: {
      kind: "image_asset",
      source_asset_id: sourceAssetId,
      source_asset_version_id: sourceAssetVersionId,
    },
    target_node_id: "node-target",
    input_role: "image_reference",
    required: true,
    enabled: true,
    order: 0,
  };
}

describe("assertValidCanvasBindingWrite", () => {
  it("accepts an immutable image asset/version pair", () => {
    expect(() => assertValidCanvasBindingWrite(
      imageBinding("asset-image", "version-image"),
    )).not.toThrow();
  });

  it.each([
    ["", "version-image", "source_asset_id"],
    ["asset-image", "", "source_asset_version_id"],
    ["   ", "version-image", "source_asset_id"],
    ["asset-image", "   ", "source_asset_version_id"],
  ])("rejects incomplete immutable references", (assetId, versionId, field) => {
    expect(() => assertValidCanvasBindingWrite(imageBinding(assetId, versionId))).toThrow(field);
  });
});
