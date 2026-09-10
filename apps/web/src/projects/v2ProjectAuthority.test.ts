import { describe, expect, it } from "vitest";

import { normalizeProjectV2ListResponse } from "../api/v2Normalizers.ts";
import {
  loadAllBackendProjectPagesWithEtag,
  projectSummaryToListItem,
} from "./v2ProjectAuthority.ts";

const cachedProject = {
  project_id: "cached-project",
  workflow_id: "cached-workflow",
  name: "Cached campaign",
  status: "active" as const,
  is_favorite: false,
  cover_asset_id: null,
  project_version: 1,
  updated_at: "2026-09-03T00:00:00Z",
};

describe("project cover authority", () => {
  it("normalizes the backend cover identity and rendition URLs", () => {
    const [project] = normalizeProjectV2ListResponse({
      items: [{
        project_id: "project-1",
        workflow_id: "workflow-1",
        name: "Curtain campaign",
        status: "active",
        is_favorite: false,
        cover_asset_id: "cover-1",
        cover_version_id: "version-4",
        cover_state: "ready",
        cover_source: "manual",
        cover_updated_at: "2026-08-30T07:59:00Z",
        project_version: 3,
        updated_at: "2026-08-30T08:00:00Z",
        cover: {
          asset_id: "cover-1",
          version_id: "version-4",
          media_type: "video",
          preview_url: null,
          poster_url: "/api/v2/assets/cover-1/poster?v=version-4&size=320",
        },
      }],
      next_cursor: null,
    }).items;

    expect(projectSummaryToListItem(project).cover).toEqual({
      assetId: "cover-1",
      versionId: "version-4",
      mediaType: "video",
      mediaPath: "/api/v2/assets/cover-1/poster?v=version-4&size=320",
      posterPath: "/api/v2/assets/cover-1/poster?v=version-4&size=320",
    });
    expect(projectSummaryToListItem(project).coverState).toBe("ready");
    expect(project.cover_version_id).toBe("version-4");
    expect(project.cover_source).toBe("manual");
  });

  it.each([
    "scene_main",
    "character_main",
    "storyboard_grid",
    "video_poster",
  ] as const)("accepts the backend %s cover source", (coverSource) => {
    const [project] = normalizeProjectV2ListResponse({
      items: [{
        project_id: "project-1",
        workflow_id: "workflow-1",
        name: "Campaign",
        status: "active",
        is_favorite: false,
        cover_asset_id: null,
        cover_version_id: null,
        cover_state: "none",
        cover_source: coverSource,
        project_version: 1,
        updated_at: "2026-09-03T00:00:00Z",
        cover: null,
      }],
      next_cursor: null,
    }).items;

    expect(project.cover_source).toBe(coverSource);
  });

  it("reuses a complete cached catalog when the first page is not modified", async () => {
    const loadPage = async () => ({
      value: null,
      etag: '"active-v1"',
      notModified: true,
    });

    await expect(loadAllBackendProjectPagesWithEtag(loadPage, {
      projects: [cachedProject],
      etag: '"active-v1"',
    })).resolves.toEqual({
      projects: [cachedProject],
      etag: '"active-v1"',
      notModified: true,
    });
  });

  it("keeps an ETag only when the complete catalog fits in one page", async () => {
    const singlePage = await loadAllBackendProjectPagesWithEtag(async () => ({
      value: { items: [cachedProject], next_cursor: null },
      etag: '"active-v2"',
      notModified: false,
    }));
    const pages = [
      {
        value: { items: [cachedProject], next_cursor: "next" },
        etag: '"page-v1"',
        notModified: false,
      },
      {
        value: { items: [], next_cursor: null },
        etag: '"page-v2"',
        notModified: false,
      },
    ];
    const multiPage = await loadAllBackendProjectPagesWithEtag(async () => pages.shift()!);

    expect(singlePage.etag).toBe('"active-v2"');
    expect(multiPage.etag).toBeNull();
  });
});
