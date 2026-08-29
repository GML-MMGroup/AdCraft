import { useEffect, useState, type RefObject } from "react";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { mediaAssetContentPath, mediaAssetPosterPath } from "../../../workflow/mediaPreview.ts";

type GeneratedPosterState = {
  key: string;
  url: string;
};

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
    if (!fallbackKey || !assetId || !mediaUrl || !videoRef) return;

    let cancelled = false;
    let objectUrl = "";
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
          objectUrl = URL.createObjectURL(record.poster_blob);
          setGeneratedPoster({ key: fallbackKey, url: objectUrl });
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
      if (objectUrl) URL.revokeObjectURL(objectUrl);
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
