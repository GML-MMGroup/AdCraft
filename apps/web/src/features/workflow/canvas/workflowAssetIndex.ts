import type {
  AssetVersionV2,
  WorkflowItemV2,
  WorkflowSlotV2,
} from "../../../types-v2.ts";
import {
  mergeV2AssetVersions,
  v2AssetById,
} from "../../../workflow-v2/assets.ts";

export type WorkflowAssetNodeScope = {
  nodeId: string;
  items: readonly WorkflowItemV2[];
  slots: readonly WorkflowSlotV2[];
  localAssets: readonly AssetVersionV2[];
};

export type WorkflowAssetIndex = {
  allAssets: AssetVersionV2[];
  byId: Map<string, AssetVersionV2>;
  byNodeId: Map<string, AssetVersionV2[]>;
  byItemId: Map<string, AssetVersionV2[]>;
  bySlotId: Map<string, AssetVersionV2[]>;
  assetsForNode: (scope: WorkflowAssetNodeScope) => AssetVersionV2[];
};

type NodeCacheEntry = {
  items: readonly WorkflowItemV2[];
  slots: readonly WorkflowSlotV2[];
  localAssets: readonly AssetVersionV2[];
  result: AssetVersionV2[];
};

export function createWorkflowAssetIndex(
  workflowAssets: readonly AssetVersionV2[],
  slotVersionAssets: readonly AssetVersionV2[],
): WorkflowAssetIndex {
  const allAssets = mergeV2AssetVersions(
    [...workflowAssets],
    [...slotVersionAssets],
  );
  const byId = v2AssetById(allAssets);
  const byNodeId = groupAssets(allAssets, (asset) => asset.node_id);
  const byItemId = groupAssets(allAssets, (asset) => asset.item_id);
  const bySlotId = groupAssets(allAssets, (asset) => asset.slot_id);
  const nodeCache = new Map<string, NodeCacheEntry>();

  function assetsForNode(scope: WorkflowAssetNodeScope) {
    const cached = nodeCache.get(scope.nodeId);
    if (
      cached
      && cached.items === scope.items
      && cached.slots === scope.slots
      && cached.localAssets === scope.localAssets
    ) {
      return cached.result;
    }

    const selected: AssetVersionV2[] = [];
    const selectedKeys = new Set<string>();
    appendAssets(selected, selectedKeys, byNodeId.get(scope.nodeId));

    for (const item of scope.items) {
      appendAssets(selected, selectedKeys, byItemId.get(item.item_id));
    }
    for (const slot of scope.slots) {
      appendAssets(selected, selectedKeys, bySlotId.get(slot.slot_id));
      for (const referenceId of [
        ...(slot.explicit_reference_ids ?? []),
        ...(slot.media_prompt_asset_ids ?? []),
        slot.selected_asset_id,
        slot.selected_version_id,
        slot.current_working_asset_id,
        slot.current_working_version_id,
        ...(slot.history_version_ids ?? []),
      ]) {
        if (referenceId) appendAsset(selected, selectedKeys, byId.get(referenceId));
      }
    }

    const result = mergeV2AssetVersions([...scope.localAssets], selected);
    nodeCache.set(scope.nodeId, {
      items: scope.items,
      slots: scope.slots,
      localAssets: scope.localAssets,
      result,
    });
    return result;
  }

  return {
    allAssets,
    byId,
    byNodeId,
    byItemId,
    bySlotId,
    assetsForNode,
  };
}

function groupAssets(
  assets: AssetVersionV2[],
  keyForAsset: (asset: AssetVersionV2) => string | null | undefined,
) {
  const result = new Map<string, AssetVersionV2[]>();
  for (const asset of assets) {
    const key = keyForAsset(asset);
    if (!key) continue;
    const group = result.get(key);
    if (group) {
      group.push(asset);
    } else {
      result.set(key, [asset]);
    }
  }
  return result;
}

function appendAssets(
  target: AssetVersionV2[],
  selectedKeys: Set<string>,
  assets: AssetVersionV2[] | undefined,
) {
  for (const asset of assets ?? []) {
    appendAsset(target, selectedKeys, asset);
  }
}

function appendAsset(
  target: AssetVersionV2[],
  selectedKeys: Set<string>,
  asset: AssetVersionV2 | undefined,
) {
  if (!asset) return;
  const key = `${asset.asset_id}:${asset.version_id}`;
  if (selectedKeys.has(key)) return;
  selectedKeys.add(key);
  target.push(asset);
}
