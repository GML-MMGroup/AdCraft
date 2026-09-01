export type MediaAssetLike = {
  asset_id?: string | null;
  public_url?: string | null;
  remote_url?: string | null;
  url?: string | null;
  media_url?: string | null;
  local_path?: string | null;
  thumbnail_path?: string | null;
  thumbnail_url?: string | null;
  poster_path?: string | null;
  poster_url?: string | null;
  preview_path?: string | null;
  preview_url?: string | null;
  file_path?: string | null;
  proxy_path?: string | null;
  content_hash?: string | number | null;
  file_hash?: string | number | null;
  output_hash?: string | number | null;
  hash?: string | number | null;
  etag?: string | number | null;
  updated_at?: string | number | null;
  node_run_id?: string | number | null;
  version?: string | number | null;
  version_id?: string | null;
};

const EXTERNAL_MEDIA_URL_PATTERN = /^(https?:\/\/|\/\/|data:|blob:)/i;

export function mediaAssetOriginalPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(firstMediaPath(asset?.public_url, asset?.remote_url, asset?.url, asset?.media_url, asset?.local_path), asset);
}

/**
 * Return the immutable AssetVersion content endpoint when the backend identity
 * is available. Display URLs remain a fallback for older/library responses.
 */
export function mediaAssetContentPath(asset?: MediaAssetLike | null) {
  const assetId = stringValue(asset?.asset_id);
  const versionId = stringValue(asset?.version_id);
  if (assetId && versionId) {
    return `/api/v2/assets/${encodeURIComponent(assetId)}/content?v=${encodeURIComponent(versionId)}`;
  }
  return mediaAssetOriginalPath(asset);
}

export function mediaAssetPreviewPath(asset?: MediaAssetLike | null) {
  const previewPath = mediaAssetPreviewRenditionPath(asset);
  return withMediaVersion(previewPath || firstMediaPath(asset?.public_url, asset?.remote_url, asset?.url, asset?.media_url, asset?.local_path), asset);
}

/**
 * Return only a backend-provided derived preview rendition. Unlike
 * mediaAssetPreviewPath this never falls back to the original content URL,
 * which lets canvas nodes avoid downloading source media during first paint.
 */
export function mediaAssetPreviewRenditionPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(firstMediaPath(
    asset?.thumbnail_path,
    asset?.thumbnail_url,
    asset?.preview_path,
    asset?.preview_url,
  ), asset);
}

export function mediaAssetCanvasPreviewRenditionPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(firstMediaPath(
    canvasPreviewCandidate(asset?.thumbnail_path),
    canvasPreviewCandidate(asset?.thumbnail_url),
    canvasPreviewCandidate(asset?.preview_path),
    canvasPreviewCandidate(asset?.preview_url),
  ), asset);
}

export function versionedMediaPath(path?: string | null, asset?: MediaAssetLike | null) {
  return withMediaVersion(path ?? "", asset);
}

export function mediaAssetPosterPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(
    firstMediaPath(asset?.poster_path, asset?.poster_url, asset?.thumbnail_path, asset?.thumbnail_url, asset?.preview_path, asset?.preview_url),
    asset,
  );
}

/** Return only a backend-provided poster/preview rendition, never source media. */
export function mediaAssetPosterRenditionPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(firstMediaPath(
    asset?.poster_path,
    asset?.poster_url,
    asset?.thumbnail_path,
    asset?.thumbnail_url,
    asset?.preview_path,
    asset?.preview_url,
  ), asset);
}

/** Return only a derived poster safe for canvas video cards. */
export function mediaAssetCanvasPosterRenditionPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(firstMediaPath(
    canvasPreviewCandidate(asset?.poster_path),
    canvasPreviewCandidate(asset?.poster_url),
    canvasPreviewCandidate(asset?.thumbnail_path),
    canvasPreviewCandidate(asset?.thumbnail_url),
    canvasPreviewCandidate(asset?.preview_path),
    canvasPreviewCandidate(asset?.preview_url),
  ), asset);
}

export function usesDerivedMediaPreview(asset?: MediaAssetLike | null) {
  const preview = stripMediaVersion(mediaAssetPreviewPath(asset));
  const original = stripMediaVersion(mediaAssetOriginalPath(asset));
  return Boolean(preview && original && preview !== original);
}

function withMediaVersion(path: string, asset?: MediaAssetLike | null) {
  if (!path) return "";
  if (EXTERNAL_MEDIA_URL_PATTERN.test(path)) return path;
  if (/[?&](v|cache_key)=/.test(path)) return path;
  const version = mediaVersionKey(asset);
  if (!version) return path;
  const separator = path.includes("?") ? "&" : "?";
  return path + separator + "v=" + encodeURIComponent(version);
}

function mediaVersionKey(asset?: MediaAssetLike | null) {
  return firstMediaPath(
    stringValue(asset?.version_id),
    stringValue(asset?.content_hash),
    stringValue(asset?.file_hash),
    stringValue(asset?.output_hash),
    stringValue(asset?.hash),
    cleanEtag(stringValue(asset?.etag)),
    stringValue(asset?.updated_at),
    stringValue(asset?.node_run_id),
    stringValue(asset?.version),
  );
}

function stripMediaVersion(path: string) {
  return path.replace(/([?&])(v|cache_key)=[^&]+(&)?/, (_match, prefix, _key, suffix) => (suffix ? prefix : ""));
}

function firstMediaPath(...values: Array<string | null | undefined>) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function canvasPreviewCandidate(path?: string | null) {
  const value = firstMediaPath(path);
  return isOriginalContentPath(value) ? "" : value;
}

function isOriginalContentPath(path: string) {
  const normalized = path.split(/[?#]/, 1)[0];
  return /\/api\/v2\/assets\/[^/]+\/content$/i.test(normalized);
}

function stringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function cleanEtag(value: string) {
  return value.replace(/^W\//, "").replace(/^"|"$/g, "");
}
