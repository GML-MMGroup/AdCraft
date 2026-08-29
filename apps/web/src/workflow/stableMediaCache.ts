const MEDIA_CACHE_NAME = "adcraft-media-v1";
const MAX_MEMORY_ENTRIES = 300;
const MAX_PERSISTED_ENTRIES = 300;

type MemoryMediaEntry = {
  objectUrl: string | null;
  promise: Promise<string> | null;
  lastAccessed: number;
};

const memoryMedia = new Map<string, MemoryMediaEntry>();

/** Versioned same-origin media is safe to persist because a new AssetVersion changes the key. */
export function isStableMediaUrl(sourceUrl?: string | null): sourceUrl is string {
  if (!sourceUrl?.trim()) return false;
  if (!/[?&](v|cache_key)=/.test(sourceUrl)) return false;
  if (/^(data:|blob:|https?:\/\/|\/\/)/i.test(sourceUrl)) {
    if (!sourceUrl.startsWith("/")) {
      if (typeof window === "undefined") return false;
      try {
        return new URL(sourceUrl, window.location.href).origin === window.location.origin;
      } catch {
        return false;
      }
    }
  }
  return true;
}

export function cachedStableMediaUrl(sourceUrl?: string | null): string | null {
  if (!sourceUrl) return null;
  const entry = memoryMedia.get(sourceUrl);
  if (!entry?.objectUrl) return null;
  entry.lastAccessed = Date.now();
  touchMemoryEntry(sourceUrl, entry);
  return entry.objectUrl;
}

/**
 * Resolve an image/poster to a browser-local object URL. Requests are shared by
 * URL, and Cache Storage survives page reloads without changing the backend.
 */
export async function loadStableMedia(sourceUrl: string, signal?: AbortSignal): Promise<string> {
  if (!isStableMediaUrl(sourceUrl) || typeof fetch === "undefined") return sourceUrl;

  const existing = memoryMedia.get(sourceUrl);
  if (existing) {
    existing.lastAccessed = Date.now();
    touchMemoryEntry(sourceUrl, existing);
    if (existing.promise) return existing.promise;
    if (existing.objectUrl) return existing.objectUrl;
  }

  const promise = loadStableMediaBlob(sourceUrl, signal).then((blob) => {
    const objectUrl = typeof URL !== "undefined" && typeof URL.createObjectURL === "function"
      ? URL.createObjectURL(blob)
      : null;
    const entry = memoryMedia.get(sourceUrl);
    if (entry) {
      entry.promise = null;
      entry.objectUrl = objectUrl;
      entry.lastAccessed = Date.now();
      touchMemoryEntry(sourceUrl, entry);
    } else {
      const next: MemoryMediaEntry = {
        objectUrl,
        promise: null,
        lastAccessed: Date.now(),
      };
      memoryMedia.set(sourceUrl, next);
      trimMemoryCache();
    }
    return objectUrl ?? sourceUrl;
  }).catch((error) => {
    memoryMedia.delete(sourceUrl);
    throw error;
  });

  memoryMedia.set(sourceUrl, {
    objectUrl: null,
    promise,
    lastAccessed: Date.now(),
  });
  trimMemoryCache();
  return promise;
}

/** Warm the cache without forcing a component to mount an image. */
export function primeStableMedia(sourceUrl?: string | null): Promise<string> | null {
  if (!sourceUrl || !isStableMediaUrl(sourceUrl)) return null;
  return loadStableMedia(sourceUrl).catch(() => sourceUrl);
}

export function __resetStableMediaCacheForTests() {
  for (const entry of memoryMedia.values()) revokeObjectUrl(entry.objectUrl);
  memoryMedia.clear();
}

async function loadStableMediaBlob(sourceUrl: string, signal?: AbortSignal): Promise<Blob> {
  const cache = await openMediaCache();
  if (cache) {
    const cached = await cache.match(sourceUrl);
    if (cached?.ok) return cached.blob();
  }

  const response = await fetch(sourceUrl, {
    credentials: "same-origin",
    cache: "force-cache",
    signal,
  });
  if (!response.ok) throw new Error(`Media request failed with ${response.status}.`);
  const cacheResponse = response.clone();
  const blob = await response.blob();
  if (cache) {
    try {
      await cache.put(sourceUrl, cacheResponse);
      await removeOlderAssetVersions(cache, sourceUrl);
      const keys = await cache.keys();
      const staleKeys = keys.slice(0, Math.max(0, keys.length - MAX_PERSISTED_ENTRIES));
      await Promise.all(staleKeys.map((key) => cache.delete(key)));
    } catch {
      // Cache Storage can be unavailable or full; the memory result remains useful.
    }
  }
  return blob;
}

async function removeOlderAssetVersions(cache: Cache, sourceUrl: string) {
  let current: URL;
  try {
    current = new URL(sourceUrl, typeof window === "undefined" ? "http://adcraft.local" : window.location.href);
  } catch {
    return;
  }
  const keys = await cache.keys();
  await Promise.all(keys.flatMap((key) => {
    let candidate: URL;
    try {
      candidate = new URL(key.url, current.href);
    } catch {
      return [];
    }
    return candidate.pathname === current.pathname && candidate.search !== current.search
      ? [cache.delete(key)]
      : [];
  }));
}

async function openMediaCache(): Promise<Cache | null> {
  if (typeof caches === "undefined") return null;
  try {
    return await caches.open(MEDIA_CACHE_NAME);
  } catch {
    return null;
  }
}

function touchMemoryEntry(sourceUrl: string, entry: MemoryMediaEntry) {
  memoryMedia.delete(sourceUrl);
  memoryMedia.set(sourceUrl, entry);
}

function trimMemoryCache() {
  while (memoryMedia.size > MAX_MEMORY_ENTRIES) {
    const oldest = [...memoryMedia.entries()].sort(([, left], [, right]) => left.lastAccessed - right.lastAccessed)[0];
    if (!oldest) return;
    memoryMedia.delete(oldest[0]);
    revokeObjectUrl(oldest[1].objectUrl);
  }
}

function revokeObjectUrl(sourceUrl: string | null) {
  if (sourceUrl && typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(sourceUrl);
  }
}
