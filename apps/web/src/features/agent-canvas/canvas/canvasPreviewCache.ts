import {
  cachedStableMediaUrl,
  isStableMediaUrl,
  primeStableMedia,
} from "../../../workflow/stableMediaCache.ts";

export type CanvasPreviewStatus = "idle" | "loading" | "ready" | "error";

type CacheEntry = {
  status: CanvasPreviewStatus;
  promise?: Promise<void>;
};

const entries = new Map<string, CacheEntry>();

/**
 * Preview URLs are version-pinned by mediaPreview.ts. Keeping the complete URL
 * as the key prevents an older AssetVersion from being mistaken for a newer one.
 */
export function canvasPreviewCacheKey(url: string): string {
  return url;
}

export function getCanvasPreviewStatus(url: string, cacheKey = canvasPreviewCacheKey(url)): CanvasPreviewStatus {
  return entries.get(cacheKey)?.status ?? "idle";
}

export function cachedCanvasPreviewUrl(url: string): string | null {
  return cachedStableMediaUrl(url);
}

export function preloadCanvasPreview(url: string, cacheKey = canvasPreviewCacheKey(url)): Promise<void> {
  const existing = entries.get(cacheKey);
  if (existing?.status === "ready") return Promise.resolve();
  if (existing?.status === "loading" && existing.promise) return existing.promise;

  if (typeof Image === "undefined") {
    entries.set(cacheKey, { status: "ready" });
    return Promise.resolve();
  }

  const image = new Image();
  image.decoding = "async";
  const promise = new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error(`Canvas preview failed to load: ${url}`));
    image.src = url;
    const decode = image.decode?.();
    if (decode) void decode.then(resolve, reject);
  }).then(
    () => {
      entries.set(cacheKey, { status: "ready" });
    },
    (error: unknown) => {
      entries.set(cacheKey, { status: "error" });
      throw error;
    },
  );
  entries.set(cacheKey, { status: "loading", promise });
  return promise;
}

/**
 * Persist same-origin, versioned previews while warming them. Opaque/external
 * renditions still use the native Image cache and never enter Cache Storage.
 */
export function preloadCanvasPreviewPersistent(
  url: string,
  cacheKey = canvasPreviewCacheKey(url),
): Promise<void> {
  if (!isStableMediaUrl(url)) return preloadCanvasPreview(url, cacheKey);
  const persisted = primeStableMedia(url);
  if (!persisted) return preloadCanvasPreview(url, cacheKey);
  return persisted.then(() => undefined);
}

export function clearCanvasPreviewCache(): void {
  entries.clear();
}
