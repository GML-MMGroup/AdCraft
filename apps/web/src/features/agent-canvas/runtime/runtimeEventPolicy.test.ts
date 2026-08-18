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
      refreshSettings: false,
      refreshDocuments: false,
      refreshDocumentId: null,
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

  it("routes progressive guidance and Draft publication events without obsolete aliases", () => {
    expect(runtimeEventPolicy(event("node_created"))).toMatchObject({
      refreshWorkflow: true,
      refreshChat: false,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("proposal_action_applied"))).toMatchObject({
      refreshWorkflow: true,
      refreshChat: true,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("draft_node_created"))).toMatchObject({
      refreshWorkflow: true,
      refreshChat: true,
      refreshRuntime: false,
    });
    for (const eventType of [
      "expert_activity_started",
      "expert_activity_completed",
      "expert_activity_failed",
      "proposal_created",
      "guidance_state_updated",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshWorkflow: false,
        refreshChat: true,
        refreshRuntime: false,
      });
    }
    expect(runtimeEventPolicy(event("creative_proposal_resolved"))).toMatchObject({
      refreshWorkflow: false,
      refreshChat: false,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("canvas_variation_materialized"))).toMatchObject({
      refreshWorkflow: false,
      refreshChat: false,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("specialist_work_started"))).toMatchObject({
      refreshWorkflow: false,
      refreshChat: false,
      refreshRuntime: false,
    });
  });

  it("refreshes proposal state throughout materialization and Workflow only after publication", () => {
    for (const eventType of [
      "proposal_materialization_queued",
      "proposal_materialization_started",
      "proposal_materialization_failed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: false,
        refreshRuntime: false,
      });
    }
    expect(runtimeEventPolicy(event("proposal_materialization_completed"))).toMatchObject({
      refreshChat: true,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
  });

  it("keeps an Agent turn waiting for the provider in the live chat read model", () => {
    expect(runtimeEventPolicy(event("agent_turn_waiting", { turn_id: "turn-waiting-1" }))).toMatchObject({
      refreshChat: true,
      refreshRuntime: false,
      refreshWorkflow: false,
    });
  });

  it("refreshes the persisted journey projection without inferring runtime failure", () => {
    for (const eventType of [
      "journey_stage_started",
      "journey_stage_changed",
      "journey_stage_waiting_user",
      "journey_stage_failed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: false,
        refreshRuntime: false,
      });
    }
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
    expect(runtimeEventPolicy(event("guided_action_applied"))).toMatchObject({
      refreshChat: true,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
    expect(runtimeEventPolicy(event("layout_updated"))).toMatchObject({
      refreshChat: false,
      refreshWorkflow: true,
      refreshRuntime: false,
    });
  });

  it("refreshes canonical state for guided production and automatic media handoff events", () => {
    for (const eventType of [
      "expert_activity_started",
      "expert_activity_completed",
      "expert_activity_failed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshWorkflow: false,
        refreshRuntime: false,
        refreshChat: true,
      });
    }

    for (const eventType of [
      "guided_draft_materialized",
      "guided_binding_materialized",
      "storyboard_sequence_planned",
      "agent_auto_run_requested",
      "agent_auto_run_submitted",
      "agent_auto_run_failed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshWorkflow: true,
        refreshRuntime: true,
      });
    }

    expect(runtimeEventPolicy(event("agent_settings_updated"))).toMatchObject({
      refreshWorkflow: true,
      refreshRuntime: true,
      refreshSettings: true,
    });
    expect(runtimeEventPolicy(event("editing_prepared", {
      node_id: "node-editing-1",
    }))).toMatchObject({
      refreshWorkflow: true,
      refreshRuntime: true,
      refreshEditingNodeId: "node-editing-1",
    });
  });

  it("refreshes persisted Agent Documents by stable document id", () => {
    expect(runtimeEventPolicy(event("agent_document_updated", {
      payload: { document_id: "doc-plan-1", revision: 4 },
    }))).toMatchObject({
      refreshDocuments: true,
      refreshDocumentId: "doc-plan-1",
      refreshChat: true,
      refreshWorkflow: false,
      refreshRuntime: false,
    });
  });

  it("refreshes canonical guided interaction, document authority, and production-closure projections", () => {
    for (const eventType of [
      "guided_interaction_opened",
      "guided_interaction_submitted",
      "guided_interaction_closed",
      "guidance_awaiting_entered",
      "guidance_awaiting_resumed",
      "guided_media_review_required",
      "guided_media_confirmed",
      "guided_closure_blocked",
      "guided_production_completed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: true,
        refreshRuntime: true,
      });
    }
    for (const eventType of [
      "agent_working_document_created",
      "agent_anchor_activated",
      "storyboard_plan_revised",
      "storyboard_visual_anchor_frozen",
    ]) {
      expect(runtimeEventPolicy(event(eventType, { payload: { document_id: "doc-v3" } }))).toMatchObject({
        refreshDocuments: true,
        refreshDocumentId: "doc-v3",
        refreshChat: true,
      });
    }
    expect(runtimeEventPolicy(event("execution_member_skipped_dependency"))).toMatchObject({
      refreshRuntime: true,
      refreshChat: true,
      refreshWorkflow: false,
    });
  });

  it("keeps recovery operations in the live read model without inferring a node failure", () => {
    for (const eventType of [
      "agent_operation_queued",
      "agent_operation_started",
      "agent_operation_waiting",
      "agent_operation_retrying",
      "agent_operation_validating",
      "agent_operation_publishing",
      "agent_operation_completed",
      "agent_operation_failed",
      "chat_turn_retry_accepted",
      "journey_stage_recovered",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshRuntime: false,
        refreshWorkflow: false,
      });
    }

    for (const eventType of [
      "provider_result_download_waiting",
      "provider_result_download_completed",
      "provider_result_download_failed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshRuntime: true,
        refreshWorkflow: false,
        refreshAssets: false,
      });
    }
  });

  it("refreshes superseded and accepted guidance state from canonical events", () => {
    for (const eventType of [
      "continuation_superseded",
      "guidance_advance_accepted",
      "guided_action_superseded",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: false,
        refreshRuntime: false,
      });
    }
  });

  it("refreshes post-ready progress without downgrading Ready node runtime state", () => {
    for (const eventType of [
      "post_ready_effect_started",
      "post_ready_effect_failed",
      "post_ready_effect_retry_scheduled",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: false,
        refreshRuntime: false,
        refreshDocuments: false,
        refreshNodeId: null,
      });
    }

    expect(runtimeEventPolicy(event("post_ready_effect_completed"))).toMatchObject({
      refreshChat: true,
      refreshWorkflow: true,
      refreshRuntime: false,
      refreshDocuments: true,
      refreshNodeId: null,
    });
  });

  it("refreshes canonical projections for resumed media and production closure events", () => {
    expect(runtimeEventPolicy(event("guided_media_resume_queued"))).toMatchObject({
      refreshChat: true,
      refreshWorkflow: false,
      refreshRuntime: false,
    });
    for (const eventType of [
      "guided_media_resume_completed",
      "guided_media_resume_failed",
      "storyboard_segment_materialized",
      "guided_editing_updated",
      "guided_completion_failed",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: true,
        refreshRuntime: true,
      });
    }
    expect(runtimeEventPolicy(event("storyboard_sequence_outline_planned", {
      payload: { plan_document_id: "doc-storyboard-1", plan_revision: 3 },
    }))).toMatchObject({
      refreshChat: true,
      refreshWorkflow: true,
      refreshDocuments: true,
      refreshDocumentId: "doc-storyboard-1",
    });
  });

  it("refreshes canonical progressive authoring projections from their additive backend events", () => {
    for (const eventType of [
      "decision_bundle_ready",
      "proposal_ready",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshChat: true,
        refreshWorkflow: false,
        refreshRuntime: false,
      });
    }

    for (const eventType of [
      "node_prompt_preparation_started",
      "node_prompt_preparation_completed",
      "node_prompt_preparation_failed",
      "node_prompt_preparation_queued",
      "node_prompt_preparation_ready",
      "node_prompt_preparation_superseded",
      "storyboard_sequence_materialized",
    ]) {
      expect(runtimeEventPolicy(event(eventType))).toMatchObject({
        refreshWorkflow: true,
        refreshNodeId: "node-1",
        refreshRuntime: false,
      });
    }

    for (const eventType of ["agent_document_revision_created", "anchor_registered"]) {
      expect(runtimeEventPolicy(event(eventType, {
        payload: { document_id: "doc-1" },
      }))).toMatchObject({
        refreshDocuments: true,
        refreshDocumentId: "doc-1",
        refreshChat: true,
      });
    }
  });
});
