import { describe, expect, it, vi } from "vitest";
import type { WorkflowRuntimeV2, WorkflowSlotV2 } from "../../../types-v2.ts";
import type { CanvasNode } from "../types.ts";
import {
  createWorkflowDisplayNodeProjector,
  type WorkflowDisplayNodeProjectionInput,
} from "./workflowDisplayNodeProjector.ts";

function canvasNode(id: string): CanvasNode {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data: {
      title: id,
      description: "",
      status: "pending",
      nodeType: "image-generation",
      kind: "image-generation",
      family: "Image",
      category: "Generation",
      contentPreview: "",
      outputCount: 0,
      previewAssets: [],
      inputPorts: [],
      outputPorts: [],
    },
  };
}

function input(
  flowNodes: CanvasNode[],
  effectiveNodeStatusById: Record<string, string>,
): WorkflowDisplayNodeProjectionInput {
  return {
    flowNodes,
    effectiveNodeStatusById,
    candidateSummaryByNodeId: {},
    dynamicItemRunningByNodeId: {},
    v2AssetVersions: [],
    slotVersionAssets: [],
    v2SlotRuntimeStatusById: {},
    v2SlotDraftsById: {},
    v2ReferenceAssetsBySlotId: {},
    v2LibraryReferenceOptions: [],
    callbacks: {
      onOpenMedia: vi.fn(),
    },
  };
}

function slot(slotId: string, nodeId: string): WorkflowSlotV2 {
  return {
    slot_id: slotId,
    node_id: nodeId,
    item_id: `${nodeId}-item`,
    slot_type: "image",
    media_type: "image",
    status: "pending",
    metadata: {},
  };
}

function runtime(runningSlotIds: string[]): WorkflowRuntimeV2 {
  return {
    workflow_id: "workflow-1",
    execution_status: "running",
    running_slot_ids: runningSlotIds,
    running_item_ids: [],
    running_node_ids: [],
    waiting_slot_ids: [],
    waiting_item_ids: [],
    waiting_node_ids: [],
    failed_slot_ids: [],
    failed_item_ids: [],
    failed_node_ids: [],
    completed_slot_ids: [],
    completed_item_ids: [],
    completed_node_ids: [],
    blocked_slot_ids: [],
    blocked_item_ids: [],
    blocked_node_ids: [],
    skipped_slot_ids: [],
    skipped_item_ids: [],
    skipped_node_ids: [],
    node_runtime: {},
    item_runtime: {},
    slot_runtime: {},
    events_cursor: 1,
  };
}

describe("workflow display node projection", () => {
  it("keeps unaffected display node references stable when one status changes", () => {
    const sourceNodes = [canvasNode("first"), canvasNode("second")];
    const projector = createWorkflowDisplayNodeProjector();
    const firstInput = input(sourceNodes, {});
    const firstProjection = projector.project(firstInput);
    const secondProjection = projector.project({
      ...firstInput,
      effectiveNodeStatusById: { first: "running" },
    });

    expect(secondProjection[0]).not.toBe(firstProjection[0]);
    expect(secondProjection[0].data.status).toBe("running");
    expect(secondProjection[1]).toBe(firstProjection[1]);
  });

  it("scopes runtime updates to the node that owns the changed slot", () => {
    const first = canvasNode("first");
    const second = canvasNode("second");
    first.data.isV2Region = true;
    first.data.v2Slots = [slot("first-slot", "first")];
    second.data.isV2Region = true;
    second.data.v2Slots = [slot("second-slot", "second")];
    const projector = createWorkflowDisplayNodeProjector();
    const baseline = {
      ...input([first, second], {}),
      v2Runtime: runtime([]),
    };
    const firstProjection = projector.project(baseline);
    const secondProjection = projector.project({
      ...baseline,
      v2Runtime: runtime(["first-slot"]),
    });

    expect(secondProjection[0]).not.toBe(firstProjection[0]);
    expect(secondProjection[1]).toBe(firstProjection[1]);
  });

  it("indexes a stable runtime only once while source node positions change", () => {
    const first = canvasNode("first");
    const second = canvasNode("second");
    first.data.isV2Region = true;
    first.data.v2Slots = [slot("first-slot", "first")];
    second.data.isV2Region = true;
    second.data.v2Slots = [slot("second-slot", "second")];
    const stableRuntime = runtime(["first-slot"]);
    let valueReads = 0;
    let runtimeFieldReads = 0;
    Object.defineProperty(stableRuntime.running_slot_ids, 0, {
      configurable: true,
      get() {
        valueReads += 1;
        return "first-slot";
      },
    });
    Object.defineProperty(stableRuntime, "execution_status", {
      configurable: true,
      get() {
        runtimeFieldReads += 1;
        return "running";
      },
    });
    const projector = createWorkflowDisplayNodeProjector();
    const baseline = {
      ...input([first, second], {}),
      v2Runtime: stableRuntime,
    };

    projector.project(baseline);
    const readsAfterInitialProjection = valueReads;
    const fieldReadsAfterInitialProjection = runtimeFieldReads;
    projector.project({
      ...baseline,
      flowNodes: [
        { ...first, position: { x: 100, y: 80 } },
        second,
      ],
    });

    expect(readsAfterInitialProjection).toBeGreaterThan(0);
    expect(valueReads).toBe(readsAfterInitialProjection);
    expect(runtimeFieldReads).toBe(fieldReadsAfterInitialProjection);
  });
});
