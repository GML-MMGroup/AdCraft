import { beforeEach, describe, expect, it } from "vitest";

import type { V2ProjectCover } from "./v2ProjectCover.ts";
import {
  loadLatestProjectCoverCache,
  loadProjectCoverCache,
  projectCoverCacheKey,
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

  it("keys persisted covers by project and exact asset version", () => {
    const key = projectCoverCacheKey("project/1", cover);

    expect(key).toBe("project:project%2F1:cover:asset-1:version-1");
    saveProjectCoverCache(key, cover);

    expect(loadLatestProjectCoverCache("project/1")).toEqual(cover);
  });

  it("migrates legacy project-only entries to the versioned key", () => {
    saveProjectCoverCache("project:legacy", cover);

    expect(loadLatestProjectCoverCache("legacy")).toEqual(cover);
    const stored = JSON.parse(window.localStorage.getItem("adcraft-project-cover-cache-v1") ?? "{}");
    expect(stored["project:legacy"]).toBeUndefined();
    expect(stored[projectCoverCacheKey("legacy", cover)]).toBeDefined();
  });

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

  it("can return an expired cover for stale-while-revalidate rendering", () => {
    window.localStorage.setItem("adcraft-project-cover-cache-v1", JSON.stringify({
      "workflow-1|updated-1": { cover, savedAt: Date.now() - 25 * 60 * 60 * 1000 },
    }));

    expect(loadProjectCoverCache("workflow-1|updated-1", undefined, { allowStale: true })).toEqual(cover);
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
