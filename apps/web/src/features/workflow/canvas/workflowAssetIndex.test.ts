import { describe, expect, it } from "vitest";
import type { AssetVersionV2, WorkflowItemV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import { createWorkflowAssetIndex } from "./workflowAssetIndex.ts";

function asset(
  assetId: string,
  scope: Partial<Pick<AssetVersionV2, "node_id" | "item_id" | "slot_id">> = {},
): AssetVersionV2 {
  return {
    asset_id: assetId,
    version_id: `${assetId}-v1`,
    media_type: "image",
    source_type: "generated",
    semantic_type: "image",
    public_url: `/media/${assetId}.png`,
    ...scope,
  };
}

function item(itemId: string, nodeId: string): WorkflowItemV2 {
  return {
    item_id: itemId,
    node_id: nodeId,
    item_type: "image",
    status: "pending",
    metadata: {},
  };
}

function slot(slotId: string, nodeId: string, itemId: string, references: string[] = []): WorkflowSlotV2 {
  return {
    slot_id: slotId,
    node_id: nodeId,
    item_id: itemId,
    slot_type: "image",
    media_type: "image",
    status: "pending",
    explicit_reference_ids: references,
    metadata: {},
  };
}

describe("workflow asset index", () => {
  it("selects only node, item, slot, and explicit-reference assets", () => {
    const nodeAsset = asset("node-a", { node_id: "node-a" });
    const slotAsset = asset("slot-a", { slot_id: "slot-a" });
    const otherAsset = asset("other", { node_id: "node-b" });
    const referenceAsset = asset("reference");
    const index = createWorkflowAssetIndex(
      [nodeAsset, slotAsset, otherAsset, referenceAsset],
      [],
    );

    const result = index.assetsForNode({
      nodeId: "node-a",
      items: [item("item-a", "node-a")],
      slots: [slot("slot-a", "node-a", "item-a", ["reference"])],
      localAssets: [],
    });

    expect(result.map((entry) => entry.asset_id)).toEqual([
      "node-a",
      "slot-a",
      "reference",
    ]);
  });

  it("returns a stable node asset array until that node's asset inputs change", () => {
    const localAssets = [asset("node-a", { node_id: "node-a" })];
    const items = [item("item-a", "node-a")];
    const slots = [slot("slot-a", "node-a", "item-a")];
    const index = createWorkflowAssetIndex(localAssets, []);
    const scope = { nodeId: "node-a", items, slots, localAssets };

    expect(index.assetsForNode(scope)).toBe(index.assetsForNode(scope));
  });

  it("includes implicit reference assets even when another node owns the asset", () => {
    const implicitReference = asset("shared-reference", { node_id: "source-node" });
    const targetSlot = slot("target-slot", "target-node", "target-item");
    targetSlot.implicit_reference_ids = ["shared-reference"];
    const index = createWorkflowAssetIndex([implicitReference], []);

    const result = index.assetsForNode({
      nodeId: "target-node",
      items: [item("target-item", "target-node")],
      slots: [targetSlot],
      localAssets: [],
    });

    expect(result.map((entry) => entry.asset_id)).toEqual(["shared-reference"]);
  });
});
