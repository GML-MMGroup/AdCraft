import { describe, expect, it } from "vitest";

import type { WorkflowSlotV2, WorkflowV2SlotRuntime } from "../../../../types-v2.ts";
import { slotWithRuntimeAssetPointers } from "./v2RuntimeSlotOverlay.ts";

function slot(overrides: Partial<WorkflowSlotV2> = {}): WorkflowSlotV2 {
  return {
    slot_id: "slot-1",
    node_id: "character-generation",
    item_id: "character-1",
    slot_type: "character_main_image",
    media_type: "image",
    required: true,
    status: "completed",
    selected_asset_id: "old-selected-asset",
    selected_version_id: "old-selected-version",
    current_working_asset_id: "old-working-asset",
    current_working_version_id: "old-working-version",
    ...overrides,
  };
}

function runtimeSlot(overrides: Partial<WorkflowV2SlotRuntime> = {}): WorkflowV2SlotRuntime {
  return {
    slot_id: "slot-1",
    node_id: "character-generation",
    item_id: "character-1",
    status: "completed",
    ...overrides,
  };
}

describe("slotWithRuntimeAssetPointers", () => {
  it("clears the stale version when runtime replaces only the selected asset id", () => {
    const persistedSlot = slot();

    const displaySlot = slotWithRuntimeAssetPointers(
      persistedSlot,
      runtimeSlot({ selected_asset_id: "new-selected-asset" }),
    );

    expect(displaySlot.selected_asset_id).toBe("new-selected-asset");
    expect(displaySlot.selected_version_id).toBeNull();
    expect(persistedSlot.selected_asset_id).toBe("old-selected-asset");
    expect(persistedSlot.selected_version_id).toBe("old-selected-version");
  });

  it("clears the stale asset id when runtime replaces only the working version id", () => {
    const displaySlot = slotWithRuntimeAssetPointers(
      slot(),
      runtimeSlot({ current_working_version_id: "new-working-version" }),
    );

    expect(displaySlot.current_working_asset_id).toBeNull();
    expect(displaySlot.current_working_version_id).toBe("new-working-version");
  });

  it("preserves a persisted pointer pair when runtime omits both fields", () => {
    const persistedSlot = slot();

    expect(slotWithRuntimeAssetPointers(persistedSlot, runtimeSlot())).toBe(persistedSlot);
  });

  it("honors an explicit runtime clear for both selected pointers", () => {
    const displaySlot = slotWithRuntimeAssetPointers(
      slot(),
      runtimeSlot({ selected_asset_id: null, selected_version_id: null }),
    );

    expect(displaySlot.selected_asset_id).toBeNull();
    expect(displaySlot.selected_version_id).toBeNull();
  });
});
