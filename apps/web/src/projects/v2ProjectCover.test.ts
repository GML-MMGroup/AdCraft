import { describe, expect, it } from "vitest";

import { resolveV2ProjectCoverSummary } from "./v2ProjectCover.ts";

describe("resolveV2ProjectCoverSummary", () => {
  it("uses the exact image rendition returned by the project summary", () => {
    expect(resolveV2ProjectCoverSummary({
      asset_id: "product-main",
      version_id: "version-7",
      media_type: "image",
      preview_url: "/api/v2/assets/product-main/preview?v=version-7&size=320",
      poster_url: null,
    })).toEqual({
      assetId: "product-main",
      versionId: "version-7",
      mediaType: "image",
      mediaPath: "/api/v2/assets/product-main/preview?v=version-7&size=320",
      posterPath: null,
    });
  });

  it("uses the exact poster rendition returned for a video cover", () => {
    expect(resolveV2ProjectCoverSummary({
      asset_id: "final-video",
      version_id: "version-9",
      media_type: "video",
      preview_url: null,
      poster_url: "/api/v2/assets/final-video/poster?v=version-9&size=320",
    })).toEqual({
      assetId: "final-video",
      versionId: "version-9",
      mediaType: "video",
      mediaPath: "/api/v2/assets/final-video/poster?v=version-9&size=320",
      posterPath: "/api/v2/assets/final-video/poster?v=version-9&size=320",
    });
  });

  it("does not synthesize a rendition when the summary is incomplete", () => {
    expect(resolveV2ProjectCoverSummary(null)).toBeNull();
    expect(resolveV2ProjectCoverSummary({
      asset_id: "video",
      version_id: "version",
      media_type: "video",
      preview_url: "/api/v2/assets/video/preview?v=version&size=320",
      poster_url: null,
    })).toBeNull();
  });
});
