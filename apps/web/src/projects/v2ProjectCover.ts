import type { WorkflowAssetListRowV2 } from "../types-v2.ts";
import { mediaAssetOriginalPath, mediaAssetPosterPath } from "../workflow/mediaPreview.ts";

export type V2ProjectCover = {
  assetId: string;
  versionId: string;
  mediaType: "image" | "video";
  mediaPath: string;
  posterPath: string | null;
};

type ProductCoverCandidate = {
  cover: V2ProjectCover;
  createdAt: number;
};

const EXCLUDED_STATES = new Set(["working", "history", "reference", "implicit_reference", "archived", "rejected"]);
const EXCLUDED_STATUSES = new Set(["queued", "running", "waiting", "pending", "blocked", "failed", "partial_failed", "cancelled", "cancellation_requested"]);

export function resolveV2ProjectCover(
  coverAssetId: string | null | undefined,
  assets: readonly WorkflowAssetListRowV2[],
): V2ProjectCover | null {
  const productImages = assets.filter(isProductCoverAsset);

  if (coverAssetId) {
    const explicit = productImages.find((asset) => asset.asset_id === coverAssetId);
    const cover = explicit ? coverFromUsableAsset(explicit) : null;
    if (cover) return cover;
  }

  const candidates = productImages
    .map((asset): ProductCoverCandidate | null => {
      const cover = coverFromUsableAsset(asset);
      return cover ? { cover, createdAt: timestamp(asset.created_at) } : null;
    })
    .filter((candidate): candidate is ProductCoverCandidate => Boolean(candidate));
  candidates.sort((left, right) => right.createdAt - left.createdAt || right.cover.versionId.localeCompare(left.cover.versionId));
  return candidates[0]?.cover ?? null;
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

function isProductCoverAsset(asset: WorkflowAssetListRowV2): asset is WorkflowAssetListRowV2 & { media_type: "image" } {
  if (!isCoverAsset(asset) || asset.media_type !== "image") return false;
  const nodeId = normalize(asset.node_id);
  const semanticType = normalize(asset.semantic_type);
  const metadataRole = normalize(typeof asset.metadata?.creative_role === "string" ? asset.metadata.creative_role : null);
  return nodeId.includes("product") || semanticType.includes("product") || metadataRole === "product";
}

function timestamp(value: string | undefined) {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalize(value: string | null | undefined) {
  return value?.trim().toLowerCase() ?? "";
}
