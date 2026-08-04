import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";

export type ResolvedPublishedAsset = {
  asset: ProjectAssetSummaryV2;
  nodeId: string | null;
};

export function resolvePublishedAssets(
  assets: ProjectAssetSummaryV2[],
  pending: ReadonlyMap<string, string | null>,
): {
  matches: ResolvedPublishedAsset[];
  unresolvedAssetIds: string[];
} {
  const assetsById = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const matches: ResolvedPublishedAsset[] = [];
  const unresolvedAssetIds: string[] = [];

  pending.forEach((nodeId, assetId) => {
    const asset = assetsById.get(assetId);
    if (asset) matches.push({ asset, nodeId });
    else unresolvedAssetIds.push(assetId);
  });
  return { matches, unresolvedAssetIds };
}
