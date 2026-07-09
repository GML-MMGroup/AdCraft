import type { AssetVersionV2, WorkflowItemV2, WorkflowRuntimeV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import { assetByAssetId, selectedAssetForSlot, workingVersionForSlot } from "../../../workflow-v2/selectors.ts";

export type V2RegionPreviewSlot = {
  slot: WorkflowSlotV2;
  asset?: AssetVersionV2;
  runtimeStatus: string;
};

export type V2RegionPreviewItem = {
  item: WorkflowItemV2;
  slots: V2RegionPreviewSlot[];
  runtimeStatus: string;
};

export type V2RegionPreviewModel = {
  items: V2RegionPreviewItem[];
  totalSlots: number;
  completedSlots: number;
  runningSlots: number;
  waitingSlots: number;
  failedSlots: number;
};

export function buildV2RegionPreviewModel({
  items,
  slots,
  assetVersions,
  runtime,
  slotRuntimeStatusById = {},
}: {
  items: WorkflowItemV2[];
  slots: WorkflowSlotV2[];
  assetVersions: AssetVersionV2[];
  runtime?: WorkflowRuntimeV2;
  slotRuntimeStatusById?: Record<string, string>;
}): V2RegionPreviewModel {
  const assets = assetByAssetId({ asset_versions: assetVersions });
  const slotsByItemId = new Map<string, WorkflowSlotV2[]>();
  for (const slot of slots) {
    if (!isRenderableRegionSlot(slot)) continue;
    slotsByItemId.set(slot.item_id, [...(slotsByItemId.get(slot.item_id) ?? []), slot]);
  }

  const renderableItems = items.filter((item) => item.lifecycle_state !== "archived");
  const previewItems = renderableItems.map((item) => {
    const renderableSlots = slotsByItemId.get(item.item_id) ?? [];
    const previewSlots = renderableSlots.map((slot) => {
      const runtimeStatus = slotRuntimeStatusById[slot.slot_id] ?? runtime?.slot_runtime?.[slot.slot_id]?.status ?? slot.status;
      return {
        slot,
        asset: selectedAssetForSlot(slot, assets) ?? workingVersionForSlot(slot, assets),
        runtimeStatus,
      };
    });
    const statuses = previewSlots.map((slot) => slot.runtimeStatus);
    return {
      item,
      slots: previewSlots,
      runtimeStatus: itemRuntimeStatus(item.status, statuses),
    };
  });

  const allSlots = previewItems.flatMap((item) => item.slots);
  return {
    items: previewItems,
    totalSlots: allSlots.length,
    completedSlots: allSlots.filter((slot) => isCompletedStatus(slot.runtimeStatus)).length,
    runningSlots: allSlots.filter((slot) => slot.runtimeStatus === "running").length,
    waitingSlots: allSlots.filter((slot) => slot.runtimeStatus === "waiting").length,
    failedSlots: allSlots.filter((slot) => slot.runtimeStatus === "failed").length,
  };
}

function itemRuntimeStatus(fallbackStatus: string, statuses: string[]) {
  if (statuses.includes("running")) return "running";
  if (statuses.includes("waiting")) return "waiting";
  if (statuses.includes("failed")) return "failed";
  if (statuses.length && statuses.every(isCompletedStatus)) return "completed";
  return fallbackStatus;
}

function isCompletedStatus(status: string) {
  return ["completed", "skipped"].includes(String(status).toLowerCase());
}

function isRenderableRegionSlot(slot: WorkflowSlotV2) {
  return slot.media_type !== "text";
}
