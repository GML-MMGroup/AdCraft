import { v2Api } from "../../../../api/v2Client.ts";
import type { WorkflowAssetListRowV2 } from "../../../../types-v2.ts";
import type { V2StructuredChatTarget } from "../operations/v2SlotOperationTypes.ts";

export type V2AssetMentionCategory = "Products" | "Characters" | "Scenes" | "Other";

export type V2AssetMentionOption = {
  id: string;
  label: string;
  category: V2AssetMentionCategory;
  locator: string | null;
  target: V2StructuredChatTarget;
};

type OwnerLike = {
  owner_display_name?: string | null;
  ownerDisplayName?: string | null;
  owner_type?: string | null;
  ownerType?: string | null;
};

export async function loadV2AssetMentionOptions(workflowId: string): Promise<V2AssetMentionOption[]> {
  const response = await v2Api.listWorkflowAssets(workflowId);
  const ownerRows = await Promise.all(
    response.assets.map(async (asset) => {
      try {
        const owner = await v2Api.assetOwner(workflowId, asset.asset_id);
        return { ...asset, ...(owner.owner ?? {}) };
      } catch {
        return asset;
      }
    }),
  );
  return buildV2AssetMentionOptions(ownerRows);
}

export function buildV2AssetMentionOptions(assets: Array<WorkflowAssetListRowV2 | Record<string, unknown>>): V2AssetMentionOption[] {
  return assets.map((asset) => {
    const assetRecord = asset as Record<string, unknown> & OwnerLike;
    const assetId = stringValue(assetRecord.asset_id ?? assetRecord.id);
    const versionId = stringValue(assetRecord.version_id);
    const ownerDisplayName = stringValue(assetRecord.owner_display_name ?? assetRecord.ownerDisplayName ?? assetRecord.display_name ?? assetRecord.filename) || assetId;
    const ownerType = stringValue(assetRecord.owner_type ?? assetRecord.ownerType ?? assetRecord.semantic_type);
    const target: V2StructuredChatTarget = {
      target_type: "asset",
      asset_id: assetId,
      version_id: versionId || undefined,
      display_name: ownerDisplayName,
      mention_text: `@${ownerDisplayName}`,
    };
    return {
      id: versionId ? `${assetId}@${versionId}` : assetId,
      label: ownerDisplayName,
      category: categoryFromOwner(ownerType),
      locator: assetId && versionId ? `asset:${assetId}@${versionId}` : null,
      target,
    };
  }).filter((option) => Boolean(option.target.asset_id));
}

function categoryFromOwner(ownerType: string): V2AssetMentionCategory {
  if (/product/i.test(ownerType)) return "Products";
  if (/character|role/i.test(ownerType)) return "Characters";
  if (/scene|location/i.test(ownerType)) return "Scenes";
  return "Other";
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}
