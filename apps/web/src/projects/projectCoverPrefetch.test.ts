import { afterEach, describe, expect, it, vi } from "vitest";

import type { V2ProjectCover } from "./v2ProjectCover.ts";
import { __resetProjectCoverPrefetchForTests, prefetchProjectCover } from "./projectCoverPrefetch.ts";

const primeStableMedia = vi.hoisted(() => vi.fn(() => Promise.resolve("blob:cover")));

vi.mock("../workflow/stableMediaCache.ts", () => ({ primeStableMedia }));

const imageCover: V2ProjectCover = {
  assetId: "asset-1",
  versionId: "version-1",
  mediaType: "image",
  mediaPath: "/api/v2/assets/asset-1/preview?v=version-1",
  posterPath: null,
};

describe("project cover prefetch", () => {
  afterEach(() => {
    __resetProjectCoverPrefetchForTests();
    primeStableMedia.mockClear();
  });

  it("prefetches only high-priority covers and deduplicates the exact URL", () => {
    prefetchProjectCover(imageCover, 2);
    expect(primeStableMedia).not.toHaveBeenCalled();

    prefetchProjectCover(imageCover, 3);
    prefetchProjectCover(imageCover, 3);
    expect(primeStableMedia).toHaveBeenCalledOnce();
    expect(primeStableMedia).toHaveBeenCalledWith(imageCover.mediaPath);
  });

  it("prefetches a video poster instead of the original video", () => {
    const videoCover: V2ProjectCover = {
      ...imageCover,
      mediaType: "video",
      mediaPath: "/api/v2/assets/video/preview?v=version-2",
      posterPath: "/api/v2/assets/video/poster?v=version-2",
    };
    prefetchProjectCover(videoCover, 3);
    expect(primeStableMedia).toHaveBeenCalledWith(videoCover.posterPath);
  });
});
