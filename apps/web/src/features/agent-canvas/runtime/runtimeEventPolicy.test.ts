import { describe, expect, it } from "vitest";

import { runtimeEventPolicy } from "./runtimeEventPolicy.ts";

describe("runtimeEventPolicy", () => {
  it("publishes assets immediately and refreshes runtime without waiting for completion", () => {
    expect(runtimeEventPolicy({
      seq: 12,
      workflow_id: "workflow-1",
      event_type: "asset_published",
      execution_id: "execution-1",
      node_id: "node-image-1",
      asset_id: "asset-1",
      binding_id: null,
      created_at: "2026-07-28T00:00:00Z",
      payload: { asset_id: "asset-1" },
    })).toEqual({
      refreshRuntime: true,
      refreshWorkflow: false,
      refreshAssets: true,
      refreshChat: false,
      refreshNodeId: null,
      refreshEditingNodeId: null,
    });
  });

  it("routes chat and authoring events through the shared sequence", () => {
    expect(runtimeEventPolicy({
      seq: 13,
      workflow_id: "workflow-1",
      event_type: "proposal_created",
      execution_id: null,
      node_id: null,
      asset_id: null,
      binding_id: null,
      created_at: "2026-07-28T00:00:01Z",
      payload: {},
    }).refreshChat).toBe(true);

    expect(runtimeEventPolicy({
      seq: 14,
      workflow_id: "workflow-1",
      event_type: "canvas_binding_created",
      execution_id: null,
      node_id: "node-video-1",
      asset_id: null,
      binding_id: "binding-1",
      created_at: "2026-07-28T00:00:02Z",
      payload: {},
    }).refreshWorkflow).toBe(true);
  });

  it("refreshes editing details without treating export as a canvas run", () => {
    const policy = runtimeEventPolicy({
      seq: 15,
      workflow_id: "workflow-1",
      event_type: "editing_export_completed",
      execution_id: null,
      node_id: "node-editing-1",
      asset_id: "asset-final",
      binding_id: null,
      created_at: "2026-07-28T00:00:03Z",
      payload: { export_id: "export-1" },
    });

    expect(policy.refreshEditingNodeId).toBe("node-editing-1");
    expect(policy.refreshWorkflow).toBe(true);
  });

  it("refreshes a completed Script node and the workflow materialized by proposal selection", () => {
    const ready = runtimeEventPolicy({
      seq: 16,
      workflow_id: "workflow-1",
      event_type: "node_ready",
      execution_id: "execution-1",
      node_id: "node-script-1",
      asset_id: null,
      binding_id: null,
      created_at: "2026-07-28T00:00:04Z",
      payload: {},
    });
    expect(ready.refreshNodeId).toBe("node-script-1");

    const selected = runtimeEventPolicy({
      seq: 17,
      workflow_id: "workflow-1",
      event_type: "proposal_selected",
      execution_id: null,
      node_id: "node-script-1",
      asset_id: null,
      binding_id: null,
      created_at: "2026-07-28T00:00:05Z",
      payload: {},
    });
    expect(selected.refreshWorkflow).toBe(true);
    expect(selected.refreshChat).toBe(true);
  });

  it("routes command, receipt, continuation, variation, and layout events without runtime churn", () => {
    const event = (eventType: string) => runtimeEventPolicy({
      seq: 18,
      workflow_id: "workflow-1",
      event_type: eventType,
      execution_id: null,
      node_id: null,
      asset_id: null,
      binding_id: null,
      created_at: "2026-07-28T00:00:06Z",
      payload: {},
    });

    expect(event("agent_command_plan_created")).toMatchObject({
      refreshChat: true,
      refreshWorkflow: false,
      refreshRuntime: false,
    });
    expect(event("agent_command_confirmation_invalidated")).toMatchObject({
      refreshChat: true,
      refreshWorkflow: false,
      refreshRuntime: false,
    });
    expect(event("agent_action_receipt_created")).toMatchObject({
      refreshChat: true,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
    expect(event("agent_planning_continuation_queued")).toMatchObject({
      refreshChat: true,
      refreshWorkflow: false,
      refreshRuntime: false,
    });
    expect(event("canvas_variation_materialized")).toMatchObject({
      refreshChat: false,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
    expect(event("canvas_layout_updated")).toMatchObject({
      refreshChat: false,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
    expect(event("canvas_binding_updated")).toMatchObject({
      refreshChat: false,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
    expect(event("guided_action_applied")).toMatchObject({
      refreshChat: true,
      refreshWorkflow: false,
      refreshRuntime: false,
    });
    expect(event("layout_updated")).toMatchObject({
      refreshChat: false,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
  });
});
