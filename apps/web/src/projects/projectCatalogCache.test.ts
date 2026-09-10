import { beforeEach, describe, expect, it } from "vitest";

import type { ProjectV2Summary } from "../types-v2.ts";
import {
  isProjectCatalogCacheFresh,
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
      activeEtag: '"active-v1"',
      trashedEtag: null,
      activeSavedAt: Date.now(),
      trashedSavedAt: Date.now(),
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

  it("treats each catalog scope as fresh for ten seconds", () => {
    const now = Date.now();
    const value: ProjectCatalogCache = {
      active: [project],
      trashed: [],
      activeEtag: '"active-v1"',
      trashedEtag: '"trashed-v1"',
      activeSavedAt: now - 9_999,
      trashedSavedAt: now - 10_001,
    };

    expect(isProjectCatalogCacheFresh(value, "active", now)).toBe(true);
    expect(isProjectCatalogCacheFresh(value, "trashed", now)).toBe(false);
    expect(isProjectCatalogCacheFresh(value, "both", now)).toBe(false);
  });

  it("expires catalog scopes independently", () => {
    const now = Date.now();
    window.localStorage.setItem("adcraft-project-catalog-cache-v1", JSON.stringify({
      active: [project],
      trashed: [{ ...project, project_id: "trashed-project", status: "trashed" }],
      activeEtag: '"active-v1"',
      trashedEtag: '"trashed-v1"',
      activeSavedAt: now,
      trashedSavedAt: now - 25 * 60 * 60 * 1000,
    }));

    expect(loadProjectCatalogCache()).toEqual({
      active: [project],
      trashed: [],
      activeEtag: '"active-v1"',
      trashedEtag: null,
      activeSavedAt: now,
      trashedSavedAt: 0,
    });
  });
});
