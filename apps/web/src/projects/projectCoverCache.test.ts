import { beforeEach, describe, expect, it } from "vitest";

import type { V2ProjectCover } from "./v2ProjectCover.ts";
import {
  loadProjectCoverCache,
  saveProjectCoverCache,
} from "./projectCoverCache.ts";

const cover: V2ProjectCover = {
  assetId: "asset-1",
  versionId: "version-1",
  mediaType: "image",
  mediaPath: "/api/v2/assets/asset-1/content?v=version-1",
  posterPath: null,
};

describe("project cover cache", () => {
  beforeEach(() => window.localStorage.clear());

  it("returns a cached cover for the exact project identity", () => {
    saveProjectCoverCache("workflow-1|updated-1", cover);

    expect(loadProjectCoverCache("workflow-1|updated-1")).toEqual(cover);
    expect(loadProjectCoverCache("workflow-1|updated-2")).toBeUndefined();
  });

  it("does not return expired covers", () => {
    window.localStorage.setItem("adcraft-project-cover-cache-v1", JSON.stringify({
      "workflow-1|updated-1": { cover, savedAt: Date.now() - 25 * 60 * 60 * 1000 },
    }));

    expect(loadProjectCoverCache("workflow-1|updated-1")).toBeUndefined();
  });
  it("migrates cached preview paths to the immutable content path", () => {
    const previewCover: V2ProjectCover = {
      ...cover,
      mediaPath: "/api/v2/assets/asset-1/preview",
    };
    saveProjectCoverCache("workflow-1|preview", previewCover);

    expect(loadProjectCoverCache("workflow-1|preview")?.mediaPath)
      .toBe("/api/v2/assets/asset-1/content?v=version-1");
  });

  it("preserves and versions a dedicated preview path", () => {
    const previewCover: V2ProjectCover = {
      ...cover,
      previewPath: "/api/v2/assets/asset-1/preview",
    };
    saveProjectCoverCache("workflow-1|preview-rendition", previewCover);

    expect(loadProjectCoverCache("workflow-1|preview-rendition")?.previewPath)
      .toBe("/api/v2/assets/asset-1/preview?v=version-1");
  });
});
