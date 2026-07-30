import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import { runtimeEventPolicy } from "./runtimeEventPolicy.ts";

function event(eventType: string, overrides: Partial<CanvasRuntimeEventV2> = {}): CanvasRuntimeEventV2 {
  return {
    seq: 12,
    workflow_id: "workflow-1",
    event_type: eventType,
    project_id: "project-1",
    execution_id: "execution-1",
    node_id: "node-1",
    asset_id: null,
    binding_id: null,
    conversation_id: null,
    turn_id: null,
    action_id: null,
    created_at: "2026-07-30T00:00:00Z",
    payload: {},
    ...overrides,
  };
}

describe("runtimeEventPolicy", () => {
  it("refreshes the asset read model for final project_asset_published events", () => {
    expect(runtimeEventPolicy(event("project_asset_published", {
      asset_id: "asset-1",
    }))).toEqual({
      refreshRuntime: true,
      refreshWorkflow: false,
      refreshAssets: true,
      refreshChat: false,
      refreshNodeId: null,
      refreshEditingNodeId: null,
    });
  });

  it("refreshes runtime and canonical node state for blocked, published, and ready media", () => {
    const blocked = runtimeEventPolicy(event("node_blocked"));
    expect(blocked).toMatchObject({
      refreshRuntime: true,
      refreshNodeId: "node-1",
      refreshAssets: false,
    });

    const output = runtimeEventPolicy(event("node_output_published", { asset_id: "asset-1" }));
    expect(output).toMatchObject({
      refreshRuntime: true,
      refreshAssets: true,
      refreshNodeId: "node-1",
    });

    expect(runtimeEventPolicy(event("node_ready"))).toMatchObject({
      refreshRuntime: true,
      refreshNodeId: "node-1",
    });
  });

  it("routes final authoring and conversation events without obsolete event aliases", () => {
    expect(runtimeEventPolicy(event("node_created"))).toMatchObject({
      refreshWorkflow: true,
      refreshChat: false,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("creative_proposal_resolved"))).toMatchObject({
      refreshWorkflow: true,
      refreshChat: true,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("canvas_variation_materialized"))).toMatchObject({
      refreshWorkflow: false,
      refreshChat: false,
      refreshRuntime: false,
    });
  });

  it("refreshes editing detail for progress without treating export as a canvas run", () => {
    const policy = runtimeEventPolicy(event("editing_export_progress", {
      execution_id: null,
      node_id: "node-editing-1",
    }));

    expect(policy).toMatchObject({
      refreshRuntime: false,
      refreshWorkflow: true,
      refreshEditingNodeId: "node-editing-1",
    });
  });
});
