import type { ProjectV2Summary } from "../types-v2.ts";

const PROJECT_CATALOG_CACHE_KEY = "adcraft-project-catalog-cache-v1";
const PROJECT_CATALOG_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export type ProjectCatalogCache = {
  active: ProjectV2Summary[];
  trashed: ProjectV2Summary[];
  savedAt: number;
};

export function loadProjectCatalogCache(storage: Storage | undefined = getStorage()): ProjectCatalogCache | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(PROJECT_CATALOG_CACHE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isProjectCatalogCache(parsed)) return null;
    if (Date.now() - parsed.savedAt > PROJECT_CATALOG_CACHE_MAX_AGE_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveProjectCatalogCache(value: ProjectCatalogCache, storage: Storage | undefined = getStorage()) {
  if (!storage) return;
  try {
    storage.setItem(PROJECT_CATALOG_CACHE_KEY, JSON.stringify(value));
  } catch {
    // Storage can be unavailable or full; the in-memory catalog remains authoritative.
  }
}

function isProjectCatalogCache(value: unknown): value is ProjectCatalogCache {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProjectCatalogCache>;
  return Number.isFinite(candidate.savedAt)
    && Array.isArray(candidate.active)
    && Array.isArray(candidate.trashed)
    && candidate.active.every(isProjectSummary)
    && candidate.trashed.every(isProjectSummary);
}

function isProjectSummary(value: unknown): value is ProjectV2Summary {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ProjectV2Summary>;
  return typeof candidate.project_id === "string"
    && typeof candidate.workflow_id === "string"
    && typeof candidate.name === "string"
    && (candidate.status === "active" || candidate.status === "archived" || candidate.status === "trashed")
    && typeof candidate.is_favorite === "boolean"
    && (candidate.cover_asset_id === null || typeof candidate.cover_asset_id === "string")
    && typeof candidate.project_version === "number"
    && typeof candidate.updated_at === "string";
}

function getStorage(): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}
