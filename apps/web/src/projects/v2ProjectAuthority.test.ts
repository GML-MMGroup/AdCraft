import { describe, expect, it } from "vitest";

import { normalizeProjectV2ListResponse } from "../api/v2Normalizers.ts";
import { projectSummaryToListItem } from "./v2ProjectAuthority.ts";

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
          preview_url: "/api/v2/assets/cover-1/preview?v=version-4",
          poster_url: "/api/v2/assets/cover-1/poster?v=version-4",
        },
      }],
      next_cursor: null,
    }).items;

    expect(projectSummaryToListItem(project).cover).toEqual({
      assetId: "cover-1",
      versionId: "version-4",
      mediaType: "video",
      mediaPath: "/api/v2/assets/cover-1/preview?v=version-4",
      posterPath: "/api/v2/assets/cover-1/poster?v=version-4",
    });
    expect(projectSummaryToListItem(project).coverState).toBe("ready");
    expect(project.cover_version_id).toBe("version-4");
    expect(project.cover_source).toBe("manual");
  });
});
