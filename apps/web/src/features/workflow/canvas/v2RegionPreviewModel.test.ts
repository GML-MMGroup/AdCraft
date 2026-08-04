import { describe, expect, it } from "vitest";

import {
  normalizeAssetVersionV2,
  normalizeWorkflowItemV2,
  normalizeWorkflowRuntimeV2,
  normalizeWorkflowSlotV2,
} from "../../../api/v2Normalizers.ts";
import { buildV2RegionPreviewModel } from "./v2RegionPreviewModel.ts";

describe("buildV2RegionPreviewModel", () => {
  it("previews a live working asset before a stale selected asset", () => {
    const persistedSlot = normalizeWorkflowSlotV2({
      slot_id: "character-main-slot",
      node_id: "character-generation",
      item_id: "character-item",
      slot_type: "character_main_image",
      media_type: "image",
      required: true,
      status: "running",
      selected_asset_id: "selected-asset",
      selected_version_id: "selected-version",
    });
    const model = buildV2RegionPreviewModel({
      items: [
        normalizeWorkflowItemV2({
          item_id: "character-item",
          node_id: "character-generation",
          item_type: "character",
          display_name: "Character",
          status: "running",
          lifecycle_state: "active",
        }),
      ],
      slots: [persistedSlot],
      assetVersions: [
        normalizeAssetVersionV2({
          asset_id: "selected-asset",
          version_id: "selected-version",
          media_type: "image",
          source_type: "generated",
          public_url: "/media/selected.jpg",
        }),
        normalizeAssetVersionV2({
          asset_id: "working-asset",
          version_id: "working-version",
          media_type: "image",
          source_type: "generated",
          public_url: "/media/working.jpg",
        }),
      ],
      runtime: normalizeWorkflowRuntimeV2({
        workflow_id: "workflow-1",
        execution_status: "running",
        slot_runtime: {
          "character-main-slot": {
            slot_id: "character-main-slot",
            node_id: "character-generation",
            item_id: "character-item",
            status: "completed",
            current_working_asset_id: "working-asset",
            current_working_version_id: "working-version",
          },
        },
      }),
    });

    expect(model.items[0].slots[0].asset?.version_id).toBe("working-version");
    expect(model.items[0].slots[0].runtimeStatus).toBe("completed");
    expect(persistedSlot.current_working_asset_id).toBeUndefined();
  });
});
