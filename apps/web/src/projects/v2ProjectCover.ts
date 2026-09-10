import type { ProjectCoverV2 } from "../types-v2.ts";

export type V2ProjectCover = {
  assetId: string;
  versionId: string;
  mediaType: "image" | "video";
  mediaPath: string;
  previewPath?: string | null;
  posterPath: string | null;
};

export function resolveV2ProjectCoverSummary(summary: ProjectCoverV2 | null | undefined): V2ProjectCover | null {
  if (!summary || !summary.asset_id || !summary.version_id) return null;
  const mediaPath = summary.media_type === "video" ? summary.poster_url : summary.preview_url;
  if (!mediaPath) return null;
  return {
    assetId: summary.asset_id,
    versionId: summary.version_id,
    mediaType: summary.media_type,
    mediaPath,
    posterPath: summary.media_type === "video" ? summary.poster_url : null,
  };
}
