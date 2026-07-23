import type { WorkflowAssetListRowV2 } from "../types-v2.ts";
import { mediaAssetOriginalPath, mediaAssetPosterPath } from "../workflow/mediaPreview.ts";

export type V2ProjectCover = {
  assetId: string;
  versionId: string;
  mediaType: "image" | "video";
  mediaPath: string;
  posterPath: string | null;
};

type RankedCover = V2ProjectCover & { rank: number };

const EXCLUDED_STATES = new Set(["working", "history", "reference", "implicit_reference", "archived", "rejected"]);
const EXCLUDED_STATUSES = new Set(["queued", "running", "waiting", "pending", "blocked", "failed", "partial_failed", "cancelled", "cancellation_requested"]);

export function resolveV2ProjectCover(
  coverAssetId: string | null | undefined,
  assets: readonly WorkflowAssetListRowV2[],
): V2ProjectCover | null {
  const usableAssets = assets.filter(isCoverAsset);

  if (coverAssetId) {
    const explicit = usableAssets.find((asset) => asset.asset_id === coverAssetId);
    const cover = explicit ? coverFromUsableAsset(explicit) : null;
    if (cover) return cover;
  }

  const candidates = usableAssets
    .map(coverFromAsset)
    .filter((cover): cover is RankedCover => Boolean(cover));
  candidates.sort((left, right) => left.rank - right.rank || right.versionId.localeCompare(left.versionId));
  return candidates[0] ? removeRank(candidates[0]) : null;
}

function coverFromAsset(asset: WorkflowAssetListRowV2 & { media_type: "image" | "video" }): RankedCover | null {
  const cover = coverFromUsableAsset(asset);
  if (!cover) return null;
  const rank = coverRank(asset);
  return rank === null ? null : { ...cover, rank };
}

function coverFromUsableAsset(asset: WorkflowAssetListRowV2 & { media_type: "image" | "video" }): V2ProjectCover | null {
  const mediaPath = mediaAssetOriginalPath(asset);
  if (!mediaPath) return null;
  return {
    assetId: asset.asset_id,
    versionId: asset.version_id,
    mediaType: asset.media_type,
    mediaPath,
    posterPath: asset.media_type === "video" ? mediaAssetPosterPath(asset) || null : null,
  };
}

function isCoverAsset(asset: WorkflowAssetListRowV2): asset is WorkflowAssetListRowV2 & { media_type: "image" | "video" } {
  return (
    (asset.media_type === "image" || asset.media_type === "video") &&
    !EXCLUDED_STATES.has(normalize(asset.state)) &&
    !EXCLUDED_STATUSES.has(normalize(asset.status)) &&
    normalize(asset.source_type) !== "reference" &&
    normalize(asset.source_type) !== "implicit_reference"
  );
}

function coverRank(asset: WorkflowAssetListRowV2): number | null {
  const nodeId = normalize(asset.node_id);
  const semanticType = normalize(asset.semantic_type);
  if (nodeId === "final-composition" || nodeId === "final_composition" || semanticType.includes("final_composition") || semanticType.includes("final-composition")) return 0;
  if (nodeId === "storyboard" || semanticType.includes("storyboard") || semanticType.includes("shot")) return asset.media_type === "video" ? 1 : 2;
  if (nodeId.includes("product") || semanticType.includes("product")) return 3;
  if (nodeId.includes("scene") || semanticType.includes("scene")) return 4;
  if (nodeId.includes("character") || semanticType.includes("character") || semanticType.includes("role")) return 5;
  return null;
}

function removeRank({ rank: _rank, ...cover }: RankedCover): V2ProjectCover {
  return cover;
}

function normalize(value: string | null | undefined) {
  return value?.trim().toLowerCase() ?? "";
}
