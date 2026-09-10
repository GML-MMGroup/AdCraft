import { useEffect, useState, type RefObject } from "react";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mediaAssetContentPath, mediaAssetPosterPath } from "../../../workflow/mediaPreview.ts";

type GeneratedPosterState = {
  key: string;
  url: string;
};

type GeneratedPosterCacheEntry = GeneratedPosterState & {
  lastAccessed: number;
};

const generatedPosterUrls = new Map<string, GeneratedPosterCacheEntry>();
const MAX_GENERATED_POSTER_URLS = 100;

function fallbackPosterKey(asset?: ProjectAssetSummaryV2 | null) {
  if (
    !asset
    || asset.media_type !== "video"
    || asset.preview_url
    || !asset.media_url
  ) return "";
  return [asset.asset_id, asset.version_id ?? asset.checksum, mediaAssetContentPath(asset)].join(":");
}

export function useAgentCanvasVideoPoster(
  asset?: ProjectAssetSummaryV2 | null,
  videoRef?: RefObject<HTMLVideoElement | null>,
) {
  const fallbackKey = fallbackPosterKey(asset);
  const assetId = asset?.asset_id ?? "";
  const checksum = asset?.checksum ?? "";
  const createdAt = asset?.created_at ?? null;
  const displayName = asset?.display_name ?? "Video output";
  const mediaUrl = asset ? mediaAssetContentPath(asset) : "";
  const mimeType = asset?.mime_type ?? "video/mp4";
  const projectId = asset?.project_id || asset?.workflow_id || "local-project";
  const versionId = asset?.version_id ?? null;
  const workflowId = asset?.workflow_id || "local-workflow";
  const previewUrl = asset ? mediaAssetPosterPath(asset) || null : null;
  const [generatedPoster, setGeneratedPoster] = useState<GeneratedPosterState>({
    key: "",
    url: "",
  });

  useEffect(() => {
    // A poster generated in an earlier session can be reused without
    // reactivating the source video. Only the explicit preview dialog passes a
    // video ref and is allowed to generate a missing poster.
    if (!fallbackKey || videoRef) return;

    let cancelled = false;
    void import("../../../workflow/videoPosterCache.ts")
      .then(({ loadVideoPosterRecordForAsset }) => loadVideoPosterRecordForAsset(projectId, workflowId, {
        asset_id: assetId,
        asset_type: "video",
        version: versionId ?? checksum,
      }))
      .then((record) => {
        if (cancelled || !record?.poster_blob) return;
        setGeneratedPoster(getGeneratedPosterState(fallbackKey, record.poster_blob));
      })
      .catch(() => {
        // A missing cache entry is expected for a newly generated video.
      });

    return () => {
      cancelled = true;
    };
  }, [assetId, checksum, fallbackKey, projectId, versionId, videoRef, workflowId]);

  useEffect(() => {
    if (!fallbackKey || !assetId || !mediaUrl || !videoRef) return;

    let cancelled = false;
    const video = videoRef.current;
    if (!video) return;
    let captureRequested = false;
    const capture = () => {
      if (cancelled || captureRequested) return;
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      if (duration > 0 && video.currentTime <= 0) return;
      captureRequested = true;
      void import("../../../workflow/videoPosterCache.ts")
        .then(({ ensureVideoPosterFromElement }) => ensureVideoPosterFromElement({
          projectId,
          workflowId,
          asset: {
            asset_id: assetId,
            asset_type: "video",
            media_type: "video",
            filename: displayName,
            mime_type: mimeType,
            public_url: mediaUrl,
            version: versionId ?? checksum,
            updated_at: createdAt ?? undefined,
          },
          sourceUrl: mediaUrl,
          video,
        }))
        .then((record) => {
          if (cancelled || !record?.poster_blob) return;
          setGeneratedPoster(getGeneratedPosterState(fallbackKey, record.poster_blob));
        })
        .catch(() => {
          // The native video remains the visible first-frame fallback.
        });
    };
    video.addEventListener("loadeddata", capture);
    video.addEventListener("seeked", capture);
    if (video.readyState >= 2) capture();

    return () => {
      cancelled = true;
      video.removeEventListener("loadeddata", capture);
      video.removeEventListener("seeked", capture);
    };
  }, [
    assetId,
    checksum,
    createdAt,
    displayName,
    fallbackKey,
    mediaUrl,
    mimeType,
    projectId,
    versionId,
    videoRef,
    workflowId,
  ]);

  if (previewUrl) return previewUrl;
  return generatedPoster.key === fallbackKey ? generatedPoster.url : null;
}

function getGeneratedPosterState(key: string, blob: Blob): GeneratedPosterState {
  const existing = generatedPosterUrls.get(key);
  if (existing) {
    existing.lastAccessed = Date.now();
    generatedPosterUrls.delete(key);
    generatedPosterUrls.set(key, existing);
    return existing;
  }
  const next = {
    key,
    url: URL.createObjectURL(blob),
    lastAccessed: Date.now(),
  };
  generatedPosterUrls.set(key, next);
  while (generatedPosterUrls.size > MAX_GENERATED_POSTER_URLS) {
    const oldestKey = generatedPosterUrls.keys().next().value;
    if (typeof oldestKey !== "string") break;
    const oldest = generatedPosterUrls.get(oldestKey);
    generatedPosterUrls.delete(oldestKey);
    if (oldest) URL.revokeObjectURL(oldest.url);
  }
  return next;
}
