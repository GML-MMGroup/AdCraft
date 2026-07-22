import { useMemo } from "react";
import type { AssetLibraryEntitySummary, UploadedAsset, WorkflowNode } from "../../../types";
import type { AssetVersionV2, SlotVersionsResponseV2, WorkflowSlotV2, WorkflowV2 } from "../../../types-v2.ts";
import { isAllowedFreeAbsorbTarget } from "../../../workflow-v2/agentRouting.ts";
import { mergeV2AssetVersions } from "../../../workflow-v2/assets.ts";
import { assetByAssetId } from "../../../workflow-v2/selectors.ts";
import type { SlotMicroEditState } from "./slots/useSlotMicroEdit.ts";
import { v2FreeGenerationMediaType } from "./v2PromptModel.ts";
import {
  v2RegionAssetVersionsForNode,
  v2RegionItemsForNode,
  v2RegionSlotsForNode,
} from "./v2RegionNode.ts";

export function useWorkflowV2DerivedState({
  workflowV2,
  selectedPlanNode,
  selectedAssets,
  promptLibraryEntities,
  v2SlotVersionsById,
  workflowAssetVersions,
  hydratedAssetVersions,
  slotDraftsBySlotId,
  visibleCanvasNodes,
}: {
  workflowV2?: WorkflowV2 | null;
  selectedPlanNode?: WorkflowNode | null;
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  v2SlotVersionsById: Record<string, SlotVersionsResponseV2 | undefined>;
  workflowAssetVersions: AssetVersionV2[];
  hydratedAssetVersions: AssetVersionV2[];
  slotDraftsBySlotId: SlotMicroEditState["draftsBySlotId"];
  visibleCanvasNodes: WorkflowNode[];
}) {
  const selectedV2Items = useMemo(() => {
    if (!selectedPlanNode) return [];
    const rawItems = workflowV2?.items.filter((item) => item.node_id === selectedPlanNode.id && item.lifecycle_state !== "archived") ?? [];
    return rawItems.length ? rawItems : v2RegionItemsForNode(selectedPlanNode);
  }, [workflowV2, selectedPlanNode]);

  const selectedV2Slots = useMemo(() => {
    if (!selectedPlanNode) return [];
    const itemIds = new Set(selectedV2Items.map((item) => item.item_id));
    const rawSlots = workflowV2?.slots.filter((slot) => slot.node_id === selectedPlanNode.id || itemIds.has(slot.item_id)) ?? [];
    return rawSlots.length ? rawSlots : v2RegionSlotsForNode(selectedPlanNode);
  }, [workflowV2, selectedPlanNode, selectedV2Items]);

  const allV2Slots = useMemo(() => {
    const visibleSlots = visibleCanvasNodes.flatMap((node) => v2RegionSlotsForNode(node));
    const slotsById = new Map<string, WorkflowSlotV2>();
    for (const slot of [...(workflowV2?.slots ?? []), ...visibleSlots]) {
      if (slot.slot_id && !slotsById.has(slot.slot_id)) slotsById.set(slot.slot_id, slot);
    }
    return Array.from(slotsById.values());
  }, [visibleCanvasNodes, workflowV2?.slots]);

  const selectedV2SlotsByItemId = useMemo(() => {
    const grouped = new Map<string, WorkflowSlotV2[]>();
    for (const slot of selectedV2Slots) {
      grouped.set(slot.item_id, [...(grouped.get(slot.item_id) ?? []), slot]);
    }
    return grouped;
  }, [selectedV2Slots]);

  const slotVersionAssets = useMemo(
    () => Object.values(v2SlotVersionsById).flatMap((entry) => entry?.versions ?? []),
    [v2SlotVersionsById],
  );

  const selectedV2AssetVersions = useMemo(
    () => assetByAssetId({
      asset_versions: mergeV2AssetVersions(
        workflowAssetVersions,
        hydratedAssetVersions,
        slotVersionAssets,
        selectedPlanNode ? v2RegionAssetVersionsForNode(selectedPlanNode) : [],
      ),
    }),
    [hydratedAssetVersions, selectedPlanNode, slotVersionAssets, workflowAssetVersions],
  );

  const v2ReferenceAssetsBySlotId = useMemo(() => {
    if (!workflowV2) return {};
    const assets = selectedV2AssetVersions;
    const next: Record<string, AssetVersionV2[]> = {};
    Object.entries(slotDraftsBySlotId).forEach(([slotId, draft]) => {
      const ids = [
        ...draft.reference_asset_ids,
        ...draft.uploaded_asset_ids,
        ...draft.attachments.map((attachment) => attachment.source_asset_id ?? ""),
      ];
      next[slotId] = ids.map((id) => assets.get(id)).filter((asset): asset is AssetVersionV2 => Boolean(asset));
    });
    return next;
  }, [workflowV2, selectedV2AssetVersions, slotDraftsBySlotId]);

  const selectedV2ReferenceAssets = useMemo(
    () =>
      selectedAssets.map((asset) => ({
        asset_id: asset.library_asset_id ?? asset.library_asset_ids?.[0] ?? asset.asset_id,
        version_id: asset.version_id ?? null,
        display_name: asset.filename,
        media_type: String(asset.media_type ?? asset.asset_type ?? ""),
        public_url: asset.public_url ?? asset.url ?? null,
        preview_url: asset.preview_url ?? asset.thumbnail_url ?? asset.poster_url ?? null,
      })),
    [selectedAssets],
  );

  const v2LibraryReferenceOptions = useMemo(
    () =>
      promptLibraryEntities.map((entity) => ({
        entity_id: entity.entity_id,
        display_name: entity.display_name,
        library_asset_id: entity.preview_asset?.asset_id ?? entity.asset_ids?.[0] ?? null,
        semantic_type: entity.semantic_type ?? null,
      })),
    [promptLibraryEntities],
  );


  const selectedFreeGenerationMediaType = useMemo(
    () => selectedPlanNode ? v2FreeGenerationMediaType(selectedPlanNode, selectedAssets[0]) : null,
    [selectedPlanNode, selectedAssets],
  );

  const selectedFreeAbsorbTargetNodes = useMemo(
    () =>
      selectedPlanNode && (selectedPlanNode.node_type === "free-generation" || selectedPlanNode.id === "free-generation")
        ? visibleCanvasNodes.filter((node) => node.id !== selectedPlanNode.id && isAllowedFreeAbsorbTarget(selectedFreeGenerationMediaType, node.id))
        : [],
    [selectedFreeGenerationMediaType, selectedPlanNode, visibleCanvasNodes],
  );

  return {
    selectedV2Items,
    selectedV2Slots,
    allV2Slots,
    selectedV2SlotsByItemId,
    slotVersionAssets,
    selectedV2AssetVersions,
    v2ReferenceAssetsBySlotId,
    selectedV2ReferenceAssets,
    v2LibraryReferenceOptions,
    selectedFreeGenerationMediaType,
    selectedFreeAbsorbTargetNodes,
  };
}
