import { beforeEach, describe, expect, it } from "vitest";

import type { ProjectV2Summary } from "../types-v2.ts";
import {
  loadProjectCatalogCache,
  saveProjectCatalogCache,
  type ProjectCatalogCache,
} from "./projectCatalogCache.ts";

const project: ProjectV2Summary = {
  project_id: "project-1",
  workflow_id: "workflow-1",
  name: "Campaign",
  status: "active",
  is_favorite: false,
  cover_asset_id: null,
  project_version: 1,
  updated_at: "2026-08-28T00:00:00Z",
};

describe("project catalog cache", () => {
  beforeEach(() => window.localStorage.clear());

  it("round-trips project metadata through local storage", () => {
    const value: ProjectCatalogCache = {
      active: [project],
      trashed: [],
      savedAt: Date.now(),
    };

    saveProjectCatalogCache(value);

    expect(loadProjectCatalogCache()).toEqual(value);
  });

  it("ignores expired or malformed cache entries", () => {
    window.localStorage.setItem("adcraft-project-catalog-cache-v1", JSON.stringify({
      active: [project],
      trashed: [],
      savedAt: Date.now() - 25 * 60 * 60 * 1000,
    }));
    expect(loadProjectCatalogCache()).toBeNull();

    window.localStorage.setItem("adcraft-project-catalog-cache-v1", "not-json");
    expect(loadProjectCatalogCache()).toBeNull();
  });
});
