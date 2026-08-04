import { describe, expect, it } from "vitest";

import { AGENT_CANVAS_SSE_EVENT_TYPES } from "./eventTypes.ts";

describe("Agent Canvas SSE subscriptions", () => {
  it("subscribes only to the final authoring, runtime, and editing event contract", () => {
    expect(AGENT_CANVAS_SSE_EVENT_TYPES).toEqual(expect.arrayContaining([
      "agent_turn_queued",
      "guidance_decision_completed",
      "specialist_work_started",
      "specialist_work_completed",
      "specialist_work_failed",
      "proposal_created",
      "proposal_action_applied",
      "guidance_state_updated",
      "draft_node_created",
      "binding_created",
      "binding_deleted",
      "project_asset_published",
      "execution_queued",
      "execution_partial_failed",
      "node_generation_started",
      "node_blocked",
      "provider_task_polled",
      "node_output_published",
      "runtime_snapshot_updated",
      "editing_export_progress",
      "editing_export_completed",
    ]));
    expect(AGENT_CANVAS_SSE_EVENT_TYPES).not.toEqual(expect.arrayContaining([
      "asset_published",
      "node_run_started",
      "execution_partial_completed",
      "canvas_variation_materialized",
      "specialist_activity_started",
      "creative_proposal_created",
      "creative_proposal_resolved",
      "production_recipe_created",
      "planning_topic_updated",
    ]));
  });
});
