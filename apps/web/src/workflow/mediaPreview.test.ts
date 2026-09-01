import { describe, expect, it } from "vitest";

import {
  mediaAssetContentPath,
  mediaAssetOriginalPath,
  mediaAssetPosterRenditionPath,
  mediaAssetPreviewPath,
  mediaAssetPreviewRenditionPath,
} from "./mediaPreview.ts";

describe("media preview paths", () => {
  it("uses the immutable AssetVersion content endpoint for asset media", () => {
    const asset = {
      asset_id: "asset/one",
      version_id: "version-2",
      media_url: "/legacy/content",
    };

    expect(mediaAssetContentPath(asset)).toBe("/api/v2/assets/asset%2Fone/content?v=version-2");
    expect(mediaAssetOriginalPath(asset)).toBe("/legacy/content?v=version-2");
  });

  it("keeps derived preview endpoints while versioning them", () => {
    expect(mediaAssetPreviewPath({
      asset_id: "asset-1",
      version_id: "version-1",
      preview_url: "/api/v2/assets/asset-1/preview",
      media_url: "/api/v2/assets/asset-1/content",
    })).toBe("/api/v2/assets/asset-1/preview?v=version-1");
  });

  it("does not invent a version when the backend has not supplied one", () => {
    expect(mediaAssetContentPath({ asset_id: "asset-1", media_url: "/media/image.png" })).toBe("/media/image.png");
  });

  it("exposes derived renditions without falling back to source media", () => {
    const sourceOnly = {
      asset_id: "asset-1",
      version_id: "version-1",
      media_url: "/api/v2/assets/asset-1/content",
    };
    expect(mediaAssetPreviewRenditionPath(sourceOnly)).toBe("");
    expect(mediaAssetPosterRenditionPath(sourceOnly)).toBe("");
  });

  it("prefers an exact poster rendition over a preview rendition", () => {
    expect(mediaAssetPosterRenditionPath({
      asset_id: "asset-1",
      version_id: "version-1",
      poster_url: "/api/v2/assets/asset-1/poster",
      preview_url: "/api/v2/assets/asset-1/preview",
    })).toBe("/api/v2/assets/asset-1/poster?v=version-1");
  });
});
