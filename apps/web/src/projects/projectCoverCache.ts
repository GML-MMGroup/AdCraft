import type { V2ProjectCover } from "./v2ProjectCover.ts";
import { mediaAssetContentPath, versionedMediaPath } from "../workflow/mediaPreview.ts";

const PROJECT_COVER_CACHE_KEY = "adcraft-project-cover-cache-v1";
const PROJECT_COVER_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const PROJECT_COVER_CACHE_MAX_ENTRIES = 200;

type ProjectCoverCacheEntry = {
  cover: V2ProjectCover;
  savedAt: number;
};

type ProjectCoverCache = Record<string, ProjectCoverCacheEntry>;

export function loadProjectCoverCache(
  identity: string,
  storage: Storage | undefined = getStorage(),
  options: { allowStale?: boolean } = {},
): V2ProjectCover | undefined {
  if (!storage) return undefined;
  try {
    const raw = storage.getItem(PROJECT_COVER_CACHE_KEY);
    if (!raw) return undefined;
    const parsed: unknown = JSON.parse(raw);
    if (!isProjectCoverCache(parsed)) return undefined;
    const entry = parsed[identity];
    if (!entry || (!options.allowStale && Date.now() - entry.savedAt > PROJECT_COVER_CACHE_MAX_AGE_MS)) return undefined;
    return normalizeProjectCover(entry.cover);
  } catch {
    return undefined;
  }
}

export function saveProjectCoverCache(
  identity: string,
  cover: V2ProjectCover,
  storage: Storage | undefined = getStorage(),
) {
  if (!storage) return;
  try {
    const raw = storage.getItem(PROJECT_COVER_CACHE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    const cache: ProjectCoverCache = isProjectCoverCache(parsed) ? parsed : {};
    cache[identity] = { cover: normalizeProjectCover(cover), savedAt: Date.now() };
    const entries = Object.entries(cache);
    if (entries.length > PROJECT_COVER_CACHE_MAX_ENTRIES) {
      entries
        .sort(([, left], [, right]) => right.savedAt - left.savedAt)
        .slice(PROJECT_COVER_CACHE_MAX_ENTRIES)
        .forEach(([key]) => delete cache[key]);
    }
    storage.setItem(PROJECT_COVER_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Storage can be unavailable or full; the in-memory resource remains authoritative.
  }
}

function isProjectCoverCache(value: unknown): value is ProjectCoverCache {
  if (!value || typeof value !== "object") return false;
  return Object.values(value).every((entry) => (
    Boolean(entry)
    && typeof entry === "object"
    && Number.isFinite((entry as ProjectCoverCacheEntry).savedAt)
    && isProjectCover((entry as ProjectCoverCacheEntry).cover)
  ));
}

function isProjectCover(value: unknown): value is V2ProjectCover {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<V2ProjectCover>;
  return typeof candidate.assetId === "string"
    && typeof candidate.versionId === "string"
    && (candidate.mediaType === "image" || candidate.mediaType === "video")
    && typeof candidate.mediaPath === "string"
    && (candidate.posterPath === null || typeof candidate.posterPath === "string");
}

function normalizeProjectCover(cover: V2ProjectCover): V2ProjectCover {
  const identity = {
    asset_id: cover.assetId,
    version_id: cover.versionId,
    media_url: cover.mediaPath,
  };
  return {
    ...cover,
    mediaPath: mediaAssetContentPath(identity) || cover.mediaPath,
    posterPath: cover.posterPath
      ? versionedMediaPath(cover.posterPath, identity)
      : null,
  };
}

function getStorage(): Storage | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}
