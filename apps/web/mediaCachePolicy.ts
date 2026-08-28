export const API_METADATA_CACHE_CONTROL = "no-store, no-cache, must-revalidate";
export const VERSIONED_MEDIA_CACHE_CONTROL = "public, max-age=31536000, immutable";
export const REVALIDATED_MEDIA_CACHE_CONTROL = "public, max-age=0, must-revalidate";

export function isVersionedAssetContentRequest(requestUrl: string) {
  const url = new URL(requestUrl, "http://adcraft.local");
  return /^\/api\/v2\/assets\/[^/]+\/content$/.test(url.pathname)
    && (url.searchParams.has("v") || url.searchParams.has("cache_key"));
}

export function mediaCacheControl(requestUrl: string) {
  const url = new URL(requestUrl, "http://adcraft.local");
  return url.searchParams.has("v") || url.searchParams.has("cache_key")
    ? VERSIONED_MEDIA_CACHE_CONTROL
    : REVALIDATED_MEDIA_CACHE_CONTROL;
}
