import type { WorkflowSlotV2, WorkflowV2SlotRuntime } from "../../../../types-v2.ts";

type SlotAssetPointerPatch = Pick<
  WorkflowSlotV2,
  "selected_asset_id" | "selected_version_id" | "current_working_asset_id" | "current_working_version_id"
>;

export function slotWithRuntimeAssetPointers(
  slot: WorkflowSlotV2,
  runtimeSlot: WorkflowV2SlotRuntime | undefined,
): WorkflowSlotV2 {
  if (!runtimeSlot) return slot;

  const runtimePointers: Partial<SlotAssetPointerPatch> = {
    ...pointerPairPatch(
      "selected_asset_id",
      "selected_version_id",
      runtimeSlot.selected_asset_id,
      runtimeSlot.selected_version_id,
    ),
    ...pointerPairPatch(
      "current_working_asset_id",
      "current_working_version_id",
      runtimeSlot.current_working_asset_id,
      runtimeSlot.current_working_version_id,
    ),
  };

  if (!Object.keys(runtimePointers).length) return slot;
  if (Object.entries(runtimePointers).every(([pointer, value]) => slot[pointer as keyof SlotAssetPointerPatch] === value)) {
    return slot;
  }

  return { ...slot, ...runtimePointers };
}

function pointerPairPatch<
  AssetKey extends "selected_asset_id" | "current_working_asset_id",
  VersionKey extends "selected_version_id" | "current_working_version_id",
>(
  assetKey: AssetKey,
  versionKey: VersionKey,
  runtimeAssetId: string | null | undefined,
  runtimeVersionId: string | null | undefined,
): Pick<SlotAssetPointerPatch, AssetKey | VersionKey> | Record<never, never> {
  if (runtimeAssetId === undefined && runtimeVersionId === undefined) return {};
  return {
    [assetKey]: normalizedRuntimePointer(runtimeAssetId),
    [versionKey]: normalizedRuntimePointer(runtimeVersionId),
  } as Pick<SlotAssetPointerPatch, AssetKey | VersionKey>;
}

function normalizedRuntimePointer(value: string | null | undefined): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
