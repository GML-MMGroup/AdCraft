import type { AssetVersionV2, WorkflowItemV2, WorkflowRuntimeV2, WorkflowSlotV2 } from "../../../../types-v2.ts";
import {
  assetByAssetId,
  selectedAssetForSlot,
  usableAssetVersionUrl,
  workingVersionForSlot,
} from "../../../../workflow-v2/selectors.ts";

export type V2RegionSlotDisplayRole = "main" | "multi_view" | "supplemental";

export type V2RegionFunctionalSlotView = {
  slot: WorkflowSlotV2;
  displayRole: V2RegionSlotDisplayRole;
  runtimeStatus: string;
  runtimeErrorCode: string | null;
  runtimeMessage: string | null;
  selectedAsset?: AssetVersionV2;
  workingAsset?: AssetVersionV2;
  previewAsset?: AssetVersionV2;
  previewUrl?: string | null;
  referenceAssets: AssetVersionV2[];
  hasUnselectedWorkingVersion: boolean;
};

export type V2RegionFunctionalItemView = {
  item: WorkflowItemV2;
  title: string;
  summary: string;
  prompt: string;
  runtimeStatus: string;
  slots: V2RegionFunctionalSlotView[];
};

export type V2RegionFunctionalModel = {
  title: string;
  items: V2RegionFunctionalItemView[];
  totalSlots: number;
  completedSlots: number;
  runningSlots: number;
  waitingSlots: number;
  failedSlots: number;
};

export function buildV2RegionFunctionalModel({
  title,
  items,
  slots,
  assetVersions,
  runtime,
  slotRuntimeStatusById = {},
  referenceAssetsBySlotId = {},
}: {
  title: string;
  items: WorkflowItemV2[];
  slots: WorkflowSlotV2[];
  assetVersions: AssetVersionV2[];
  runtime?: WorkflowRuntimeV2;
  slotRuntimeStatusById?: Record<string, string>;
  referenceAssetsBySlotId?: Record<string, AssetVersionV2[]>;
}): V2RegionFunctionalModel {
  const assets = assetByAssetId({ asset_versions: assetVersions });
  const slotsByItemId = new Map<string, WorkflowSlotV2[]>();

  for (const slot of slots) {
    if (!isRenderableFunctionalSlot(slot)) continue;
    slotsByItemId.set(slot.item_id, [...(slotsByItemId.get(slot.item_id) ?? []), slot]);
  }

  const viewItems = items
    .filter((item) => item.lifecycle_state !== "archived")
    .map((item) => {
      const itemSlots = [...(slotsByItemId.get(item.item_id) ?? [])].sort(compareRegionSlots);
      const slotViews = itemSlots.map((slot) => {
        const selectedAsset = selectedAssetForSlot(slot, assets);
        const workingAsset = workingVersionForSlot(slot, assets);
        const previewAsset = workingAsset ?? selectedAsset;
        const runtimeRecord = runtime?.slot_runtime?.[slot.slot_id];
        const runtimeStatus = slotRuntimeStatusById[slot.slot_id] ?? runtimeRecord?.status ?? slot.status;
        const runtimeMetadataErrorCode = stringMetadataValue(runtimeRecord?.metadata, "generation_error_code");
        const runtimeMetadataMessage = stringMetadataValue(runtimeRecord?.metadata, "generation_error_message");

        return {
          slot,
          displayRole: regionSlotDisplayRole(slot),
          runtimeStatus,
          runtimeErrorCode: runtimeRecord?.error?.code ?? runtimeMetadataErrorCode,
          runtimeMessage: runtimeRecord?.error?.message ?? runtimeMetadataMessage ?? runtimeRecord?.waiting_reason ?? null,
          selectedAsset,
          workingAsset,
          previewAsset,
          previewUrl: previewAsset ? usableAssetVersionUrl(previewAsset) : null,
          referenceAssets: referenceAssetsBySlotId[slot.slot_id] ?? [],
            hasUnselectedWorkingVersion: Boolean(
              workingAsset &&
                (!selectedAsset ||
                  workingAsset.asset_id !== selectedAsset.asset_id ||
                  workingAsset.version_id !== selectedAsset.version_id),
            ),
        };
      });
      const statuses = slotViews.map((slot) => slot.runtimeStatus);

      return {
        item,
        title: item.display_name || item.item_id,
        summary: compactItemSummary(item),
        prompt: item.item_prompt ?? "",
        runtimeStatus: itemRuntimeStatus(item.status, statuses),
        slots: slotViews,
      };
    });

  const allSlots = viewItems.flatMap((item) => item.slots);
  return {
    title,
    items: viewItems,
    totalSlots: allSlots.length,
    completedSlots: allSlots.filter((slot) => isCompletedStatus(slot.runtimeStatus)).length,
    runningSlots: allSlots.filter((slot) => slot.runtimeStatus === "running").length,
    waitingSlots: allSlots.filter((slot) => slot.runtimeStatus === "waiting").length,
    failedSlots: allSlots.filter((slot) => slot.runtimeStatus === "failed").length,
  };
}

export function regionSlotDisplayRole(slot: Pick<WorkflowSlotV2, "slot_type">): V2RegionSlotDisplayRole {
  if (slot.slot_type.endsWith("_main_image")) return "main";
  if (slot.slot_type.includes("three_view") || slot.slot_type.includes("multi_view")) return "multi_view";
  return "supplemental";
}

function compareRegionSlots(left: WorkflowSlotV2, right: WorkflowSlotV2) {
  const roleOrder = { main: 0, multi_view: 1, supplemental: 2 };
  const mediaOrder = mediaPreviewOrder(left.media_type) - mediaPreviewOrder(right.media_type);
  return roleOrder[regionSlotDisplayRole(left)] - roleOrder[regionSlotDisplayRole(right)] || mediaOrder || left.slot_id.localeCompare(right.slot_id);
}

export function isV2BgmFunctionalSlot(slot: WorkflowSlotV2): boolean {
  return slot.slot_type === "bgm_audio" && slot.media_type === "audio";
}

function isRenderableFunctionalSlot(slot: WorkflowSlotV2) {
  return isImageSlot(slot) || isStoryboardVideoSlot(slot) || isV2BgmFunctionalSlot(slot);
}

function isImageSlot(slot: Pick<WorkflowSlotV2, "media_type">) {
  return slot.media_type === "image";
}

function isStoryboardVideoSlot(slot: WorkflowSlotV2) {
  return slot.media_type === "video" && isStoryboardShotSlot(slot);
}

function isStoryboardShotSlot(slot: Pick<WorkflowSlotV2, "node_id" | "slot_type">) {
  return slot.node_id === "storyboard" || slot.slot_type === "shot_video_segment" || slot.slot_type.startsWith("shot_");
}

function mediaPreviewOrder(mediaType: string) {
  if (mediaType === "image") return 0;
  if (mediaType === "video") return 1;
  return 2;
}

function compactItemSummary(item: WorkflowItemV2) {
  const source = item.description || item.item_prompt || item.display_name || item.item_id;
  return source.length > 180 ? `${source.slice(0, 177)}...` : source;
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

function stringMetadataValue(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}
