import type { ProjectV2Summary } from "../types-v2.ts";

const PROJECT_CATALOG_CACHE_KEY = "adcraft-project-catalog-cache-v1";
const PROJECT_CATALOG_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const PROJECT_CATALOG_CACHE_FRESH_AGE_MS = 10 * 1000;

export type ProjectCatalogCache = {
  active: ProjectV2Summary[];
  trashed: ProjectV2Summary[];
  activeEtag: string | null;
  trashedEtag: string | null;
  activeSavedAt: number;
  trashedSavedAt: number;
};

export type ProjectCatalogCacheScope = "active" | "trashed" | "both";

export function loadProjectCatalogCache(storage: Storage | undefined = getStorage()): ProjectCatalogCache | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(PROJECT_CATALOG_CACHE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    const normalized = normalizeProjectCatalogCache(parsed);
    if (!normalized) return null;
    const now = Date.now();
    const activeExpired = now - normalized.activeSavedAt > PROJECT_CATALOG_CACHE_MAX_AGE_MS;
    const trashedExpired = now - normalized.trashedSavedAt > PROJECT_CATALOG_CACHE_MAX_AGE_MS;
    if (activeExpired && trashedExpired) return null;
    return {
      active: activeExpired ? [] : normalized.active,
      trashed: trashedExpired ? [] : normalized.trashed,
      activeEtag: activeExpired ? null : normalized.activeEtag,
      trashedEtag: trashedExpired ? null : normalized.trashedEtag,
      activeSavedAt: activeExpired ? 0 : normalized.activeSavedAt,
      trashedSavedAt: trashedExpired ? 0 : normalized.trashedSavedAt,
    };
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

export function isProjectCatalogCacheFresh(
  value: ProjectCatalogCache | null,
  scope: ProjectCatalogCacheScope,
  now = Date.now(),
) {
  if (!value) return false;
  const activeFresh = now - value.activeSavedAt <= PROJECT_CATALOG_CACHE_FRESH_AGE_MS;
  const trashedFresh = now - value.trashedSavedAt <= PROJECT_CATALOG_CACHE_FRESH_AGE_MS;
  if (scope === "active") return activeFresh;
  if (scope === "trashed") return trashedFresh;
  return activeFresh && trashedFresh;
}

function normalizeProjectCatalogCache(value: unknown): ProjectCatalogCache | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ProjectCatalogCache> & { savedAt?: unknown };
  if (
    !Array.isArray(candidate.active)
    || !Array.isArray(candidate.trashed)
    || !candidate.active.every(isProjectSummary)
    || !candidate.trashed.every(isProjectSummary)
  ) return null;
  const legacySavedAt = Number.isFinite(candidate.savedAt) ? Number(candidate.savedAt) : null;
  const activeSavedAt = Number.isFinite(candidate.activeSavedAt)
    ? Number(candidate.activeSavedAt)
    : legacySavedAt;
  const trashedSavedAt = Number.isFinite(candidate.trashedSavedAt)
    ? Number(candidate.trashedSavedAt)
    : legacySavedAt;
  if (activeSavedAt === null || trashedSavedAt === null) return null;
  const activeEtag = candidate.activeEtag;
  const trashedEtag = candidate.trashedEtag;
  if (activeEtag !== undefined && activeEtag !== null && typeof activeEtag !== "string") return null;
  if (trashedEtag !== undefined && trashedEtag !== null && typeof trashedEtag !== "string") return null;
  return {
    active: candidate.active,
    trashed: candidate.trashed,
    activeEtag: activeEtag ?? null,
    trashedEtag: trashedEtag ?? null,
    activeSavedAt,
    trashedSavedAt,
  };
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
