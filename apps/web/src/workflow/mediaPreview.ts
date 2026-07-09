import type { UploadedAsset } from "../types";

type MediaAssetLike = Partial<UploadedAsset>;

const EXTERNAL_MEDIA_URL_PATTERN = /^(https?:\/\/|\/\/|data:|blob:)/i;

export function mediaAssetOriginalPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(firstMediaPath(asset?.public_url, asset?.remote_url, asset?.url, asset?.local_path), asset);
}

export function mediaAssetPreviewPath(asset?: MediaAssetLike | null) {
  const previewPath = firstMediaPath(
    asset?.thumbnail_path,
    asset?.thumbnail_url,
    asset?.poster_path,
    asset?.poster_url,
    asset?.preview_path,
    asset?.preview_url,
  );
  return withMediaVersion(previewPath || firstMediaPath(asset?.public_url, asset?.remote_url, asset?.url, asset?.local_path), asset);
}

export function mediaAssetPosterPath(asset?: MediaAssetLike | null) {
  return withMediaVersion(
    firstMediaPath(asset?.poster_path, asset?.poster_url, asset?.thumbnail_path, asset?.thumbnail_url, asset?.preview_path, asset?.preview_url),
    asset,
  );
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

function stringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function cleanEtag(value: string) {
  return value.replace(/^W\//, "").replace(/^"|"$/g, "");
}
