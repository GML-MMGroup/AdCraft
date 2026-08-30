import type { CanvasNodeV2, ProjectAssetSummaryV2, ProjectCoverV2 } from "../types-v2.ts";
import { mediaAssetContentPath } from "../workflow/mediaPreview.ts";

export type V2ProjectCover = {
  assetId: string;
  versionId: string;
  mediaType: "image" | "video";
  mediaPath: string;
  posterPath: string | null;
};

export function resolveV2ProjectCoverSummary(summary: ProjectCoverV2 | null | undefined): V2ProjectCover | null {
  if (!summary || !summary.asset_id || !summary.version_id || !summary.preview_url) return null;
  if (summary.media_type === "video" && !summary.poster_url) return null;
  return {
    assetId: summary.asset_id,
    versionId: summary.version_id,
    mediaType: summary.media_type,
    mediaPath: summary.preview_url,
    posterPath: summary.media_type === "video" ? summary.poster_url : null,
  };
}

type ProductCoverCandidate = {
  cover: V2ProjectCover;
  createdAt: number;
};

const PRODUCT_MAIN_ROLES = new Set(["product_main", "product_main_image"]);
const PRODUCT_MULTIVIEW_ROLES = new Set([
  "product_multiview",
  "product_multi_view",
  "product_multi_view_grid",
  "product_view_board",
]);

export function resolveV2ProjectCover(
  coverAssetId: string | null | undefined,
  assets: readonly ProjectAssetSummaryV2[],
  sourceNodes: readonly CanvasNodeV2[] = [],
): V2ProjectCover | null {
  const sourceNodeRoles = new Map(sourceNodes.map((node) => [node.node_id, nodeRecipeRole(node)]));
  const productImages = assets.filter((asset): asset is ProjectAssetSummaryV2 & { media_type: "image" } => (
    isProductMainCoverAsset(asset, sourceNodeRoles)
  ));

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

export function needsV2ProjectCoverNodeAuthority(assets: readonly ProjectAssetSummaryV2[]) {
  const coarseProductAssets = assets.filter((asset) => {
    if (!isUsableGeneratedImage(asset)) return false;
    const roles = publicAssetRoles(asset);
    return roles.includes("product") && !roles.some((role) => PRODUCT_MAIN_ROLES.has(role) || PRODUCT_MULTIVIEW_ROLES.has(role));
  });
  if (coarseProductAssets.length === 0) return false;
  const provenanceRoots = coarseProductAssets.filter((asset) => {
    const sources = asset.generation_provenance.source_asset_version_ids;
    return Array.isArray(sources) && sources.length === 0;
  });
  if (provenanceRoots.length !== 1 || !provenanceRoots[0].version_id) return true;
  const root = provenanceRoots[0];
  return coarseProductAssets.some((asset) => {
    if (asset.asset_id === root.asset_id && asset.version_id === root.version_id) return false;
    const sources = asset.generation_provenance.source_asset_version_ids;
    return !Array.isArray(sources) || !sources.includes(root.version_id);
  });
}

function coverFromUsableAsset(asset: ProjectAssetSummaryV2 & { media_type: "image" }): V2ProjectCover | null {
  if (!asset.version_id) return null;
  const mediaPath = mediaAssetContentPath(asset);
  if (!mediaPath) return null;
  return {
    assetId: asset.asset_id,
    versionId: asset.version_id,
    mediaType: "image",
    mediaPath,
    posterPath: null,
  };
}

function isProductMainCoverAsset(asset: ProjectAssetSummaryV2, sourceNodeRoles: ReadonlyMap<string, string>) {
  if (!isUsableGeneratedImage(asset)) return false;
  const sourceNodeRole = sourceNodeRoles.get(asset.source_node_id ?? "") ?? "";
  if (PRODUCT_MULTIVIEW_ROLES.has(sourceNodeRole)) return false;
  if (PRODUCT_MAIN_ROLES.has(sourceNodeRole)) return true;

  const roles = publicAssetRoles(asset);
  if (roles.some((role) => PRODUCT_MULTIVIEW_ROLES.has(role))) return false;
  if (roles.some((role) => PRODUCT_MAIN_ROLES.has(role))) return true;
  if (!roles.includes("product")) return false;

  const sources = asset.generation_provenance.source_asset_version_ids;
  return Array.isArray(sources) && sources.length === 0;
}

function isUsableGeneratedImage(asset: ProjectAssetSummaryV2): asset is ProjectAssetSummaryV2 & { media_type: "image" } {
  return asset.media_type === "image" && asset.status === "ready" && asset.source_type === "generated";
}

function publicAssetRoles(asset: ProjectAssetSummaryV2) {
  return [normalize(asset.source_semantic_role), normalize(asset.semantic_type)].filter(Boolean);
}

function nodeRecipeRole(node: CanvasNodeV2) {
  const recipeId = typeof node.metadata.prompt_recipe_id === "string" ? normalize(node.metadata.prompt_recipe_id) : "";
  const recipeRole = recipeId.split(".").at(-1) ?? "";
  return recipeRole || normalize(node.creative_role);
}

function timestamp(value: string | null | undefined) {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalize(value: string | null | undefined) {
  return value?.trim().toLowerCase() ?? "";
}
