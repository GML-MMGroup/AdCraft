import { describe, expect, it } from "vitest";

import { normalizeWorkflowSlotV2, normalizeWorkflowV2 } from "../../../api/v2Normalizers.ts";
import { sameV2Slots } from "./nodeDataEquality.ts";

describe("V2 slot version identity", () => {
  it("treats a selected version change as a canvas data change", () => {
    const first = normalizeWorkflowSlotV2({
      slot_id: "slot-1",
      node_id: "bgm",
      item_id: "item-1",
      slot_type: "bgm_audio",
      media_type: "audio",
      selected_asset_id: "asset-1",
      selected_version_id: "version-1",
    });
    const second = { ...first, selected_version_id: "version-2" };

    expect(sameV2Slots([first], [second])).toBe(false);
  });

  it("uses the selected version id for an id-only fallback asset", () => {
    const workflow = normalizeWorkflowV2({
      workflow_schema_version: 2,
      workflow_id: "workflow-1",
      nodes: [],
      items: [],
      slots: [{
        slot_id: "slot-1",
        node_id: "bgm",
        item_id: "item-1",
        slot_type: "bgm_audio",
        media_type: "audio",
        selected_asset_id: "asset-1",
        selected_version_id: "version-1",
      }],
    });

    expect(workflow.asset_versions).toEqual([
      expect.objectContaining({
        asset_id: "asset-1",
        version_id: "version-1",
      }),
    ]);
  });
});
