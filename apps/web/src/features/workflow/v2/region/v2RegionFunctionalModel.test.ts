import { describe, expect, it } from "vitest";

import {
  normalizeAssetVersionV2,
  normalizeWorkflowItemV2,
  normalizeWorkflowRuntimeV2,
  normalizeWorkflowSlotV2,
} from "../../../../api/v2Normalizers.ts";
import { buildV2RegionFunctionalModel } from "./v2RegionFunctionalModel.ts";

function item(overrides: Record<string, unknown> = {}) {
  return normalizeWorkflowItemV2({
    item_id: "bgm-item",
    node_id: "bgm",
    item_type: "bgm",
    display_name: "Background music",
    status: "ready",
    lifecycle_state: "active",
    ...overrides,
  });
}

function slot(overrides: Record<string, unknown> = {}) {
  return normalizeWorkflowSlotV2({
    slot_id: "bgm-slot",
    node_id: "bgm",
    item_id: "bgm-item",
    slot_type: "bgm_audio",
    media_type: "audio",
    required: true,
    status: "ready",
    ...overrides,
  });
}

function asset(overrides: Record<string, unknown> = {}) {
  return normalizeAssetVersionV2({
    asset_id: "asset",
    version_id: "version",
    media_type: "audio",
    source_type: "generated",
    semantic_type: "bgm",
    public_url: "/media/bgm.mp3",
    ...overrides,
  });
}

describe("buildV2RegionFunctionalModel", () => {
  it("includes only the canonical BGM audio slot", () => {
    const model = buildV2RegionFunctionalModel({
      title: "BGM",
      items: [item()],
      slots: [
        slot(),
        slot({ slot_id: "voice-slot", slot_type: "voiceover_audio", media_type: "audio" }),
      ],
      runtime: normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-1",
        slot_runtime: {
          "bgm-slot": {
            status: "failed",
            error: { code: "provider_failed", message: "Generation failed", stage: "provider" },
          },
        },
      }),
      assetVersions: [],
    });

    expect(model.items[0].slots.map((entry) => entry.slot.slot_id)).toEqual(["bgm-slot"]);
    expect(model.items[0].slots[0].runtimeErrorCode).toBe("provider_failed");
    expect(model.items[0].slots[0].runtimeMessage).toBe("Generation failed");
  });

  it("resolves selected and unselected working BGM versions independently", () => {
    const model = buildV2RegionFunctionalModel({
      title: "BGM",
      items: [item()],
      slots: [
        slot({
          selected_asset_id: "selected-asset",
          current_working_version_id: "working-version",
        }),
      ],
      assetVersions: [
        asset({ asset_id: "selected-asset", version_id: "selected-version", public_url: "/media/selected.mp3" }),
        asset({ asset_id: "working-asset", version_id: "working-version", public_url: "/media/working.mp3" }),
      ],
    });

    const slotView = model.items[0].slots[0];
    expect(slotView.selectedAsset?.version_id).toBe("selected-version");
    expect(slotView.workingAsset?.version_id).toBe("working-version");
    expect(slotView.previewAsset?.version_id).toBe("working-version");
    expect(slotView.hasUnselectedWorkingVersion).toBe(true);
  });

  it("uses live runtime asset pointers while the workflow slot is still stale", () => {
    const model = buildV2RegionFunctionalModel({
      title: "Character Generation",
      items: [
        item({
          item_id: "character-item",
          node_id: "character-generation",
          item_type: "character",
          display_name: "Character",
          status: "running",
        }),
      ],
      slots: [
        slot({
          slot_id: "character-main-slot",
          item_id: "character-item",
          node_id: "character-generation",
          slot_type: "character_main_image",
          media_type: "image",
          status: "waiting",
          selected_asset_id: null,
          selected_version_id: null,
          current_working_asset_id: null,
          current_working_version_id: null,
        }),
      ],
      assetVersions: [
        asset({
          asset_id: "runtime-selected-asset",
          version_id: "runtime-selected-version",
          media_type: "image",
          semantic_type: "character_main_image",
          public_url: "/media/runtime-selected.jpg",
        }),
        asset({
          asset_id: "runtime-working-asset",
          version_id: "runtime-working-version",
          media_type: "image",
          semantic_type: "character_main_image",
          public_url: "/media/runtime-working.jpg",
        }),
      ],
      runtime: normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-1",
        execution_status: "running",
        slot_runtime: {
          "character-main-slot": {
            slot_id: "character-main-slot",
            item_id: "character-item",
            node_id: "character-generation",
            status: "completed",
            selected_asset_id: "runtime-selected-asset",
            selected_version_id: "runtime-selected-version",
            current_working_asset_id: "runtime-working-asset",
            current_working_version_id: "runtime-working-version",
          },
        },
      }),
    });

    const slotView = model.items[0].slots[0];
    expect(slotView.runtimeStatus).toBe("completed");
    expect(slotView.slot.selected_asset_id).toBe("runtime-selected-asset");
    expect(slotView.slot.current_working_asset_id).toBe("runtime-working-asset");
    expect(slotView.selectedAsset?.version_id).toBe("runtime-selected-version");
    expect(slotView.workingAsset?.version_id).toBe("runtime-working-version");
    expect(slotView.previewUrl).toBe("/media/runtime-working.jpg?v=runtime-working-version");
    expect(slotView.hasUnselectedWorkingVersion).toBe(true);
  });

  it("includes the canonical final video and maps domain failures to blocked or skipped", () => {
    const finalItem = item({
      item_id: "final-item",
      node_id: "final-composition",
      item_type: "final_composition",
      display_name: "Final Composition",
      status: "failed",
    });
    const finalSlot = slot({
      slot_id: "final-slot",
      node_id: "final-composition",
      item_id: "final-item",
      slot_type: "final_video",
      media_type: "video",
      status: "failed",
      selected_asset_id: "final-asset",
      selected_version_id: "final-version",
    });
    const finalAsset = asset({
      asset_id: "final-asset",
      version_id: "final-version",
      media_type: "video",
      semantic_type: "final_video",
      public_url: "/media/final.mp4",
    });
    const waiting = buildV2RegionFunctionalModel({
      title: "Final Composition",
      items: [finalItem],
      slots: [finalSlot],
      assetVersions: [finalAsset],
      runtime: normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-1",
        slot_runtime: {
          "final-slot": {
            status: "failed",
            metadata: { generation_error_code: "composition_inputs_not_settled" },
          },
        },
      }),
    });
    const skipped = buildV2RegionFunctionalModel({
      title: "Final Composition",
      items: [finalItem],
      slots: [finalSlot],
      assetVersions: [finalAsset],
      runtime: normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-1",
        slot_runtime: {
          "final-slot": {
            status: "failed",
            metadata: { generation_error_code: "no_successful_video_segments" },
          },
        },
      }),
    });

    expect(waiting.items[0].slots[0].previewAsset?.version_id).toBe("final-version");
    expect(waiting.items[0].slots[0].runtimeStatus).toBe("blocked");
    expect(waiting.items[0].runtimeStatus).toBe("blocked");
    expect(skipped.items[0].slots[0].runtimeStatus).toBe("skipped");
    expect(skipped.items[0].runtimeStatus).toBe("skipped");
  });
});
