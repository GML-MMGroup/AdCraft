import { useEffect, useState } from "react";

import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";

type GeneratedPosterState = {
  key: string;
  url: string;
};

function scheduleIdleTask(task: () => void) {
  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
    cancelIdleCallback?: (handle: number) => void;
  };
  if (idleWindow.requestIdleCallback) {
    const handle = idleWindow.requestIdleCallback(task, { timeout: 1200 });
    return () => idleWindow.cancelIdleCallback?.(handle);
  }
  const handle = window.setTimeout(task, 220);
  return () => window.clearTimeout(handle);
}

function fallbackPosterKey(asset?: ProjectAssetSummaryV2 | null) {
  if (
    !asset
    || asset.media_type !== "video"
    || asset.preview_url
    || !asset.media_url
  ) return "";
  return [asset.asset_id, asset.version_id ?? asset.checksum, asset.media_url].join(":");
}

export function useAgentCanvasVideoPoster(asset?: ProjectAssetSummaryV2 | null) {
  const fallbackKey = fallbackPosterKey(asset);
  const assetId = asset?.asset_id ?? "";
  const checksum = asset?.checksum ?? "";
  const createdAt = asset?.created_at ?? null;
  const displayName = asset?.display_name ?? "Video output";
  const mediaUrl = asset?.media_url ?? "";
  const mimeType = asset?.mime_type ?? "video/mp4";
  const projectId = asset?.project_id || asset?.workflow_id || "local-project";
  const versionId = asset?.version_id ?? null;
  const workflowId = asset?.workflow_id || "local-workflow";
  const previewUrl = asset?.preview_url ?? null;
  const [generatedPoster, setGeneratedPoster] = useState<GeneratedPosterState>({
    key: "",
    url: "",
  });

  useEffect(() => {
    if (!fallbackKey || !assetId || !mediaUrl) return;

    let cancelled = false;
    let objectUrl = "";
    const cancelIdleTask = scheduleIdleTask(() => {
      void import("../../../workflow/videoPosterCache.ts")
        .then(({ ensureVideoPoster }) => ensureVideoPoster({
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
          videoUrl: mediaUrl,
        }))
        .then((record) => {
          if (cancelled || !record?.poster_blob) return;
          objectUrl = URL.createObjectURL(record.poster_blob);
          setGeneratedPoster({ key: fallbackKey, url: objectUrl });
        })
        .catch(() => {
          // The video remains playable even when a local first-frame poster cannot be generated.
        });
    });

    return () => {
      cancelled = true;
      cancelIdleTask();
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
    workflowId,
  ]);

  if (previewUrl) return previewUrl;
  return generatedPoster.key === fallbackKey ? generatedPoster.url : null;
}
