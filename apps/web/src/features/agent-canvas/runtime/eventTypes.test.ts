import { describe, expect, it } from "vitest";

import { AGENT_CANVAS_SSE_EVENT_TYPES } from "./eventTypes.ts";

describe("Agent Canvas SSE subscriptions", () => {
  it("subscribes to current and canonical chat, graph, runtime, and editing events", () => {
    expect(AGENT_CANVAS_SSE_EVENT_TYPES).toEqual(expect.arrayContaining([
      "chat_turn_queued",
      "concept_proposal_created",
      "concept_options_ready",
      "script_artifact_created",
      "binding_created",
      "binding_removed",
      "asset_published",
      "provider_inputs_resolved",
      "node_run_started",
      "editing_export_completed",
      "agent_command_plan_created",
      "agent_command_confirmation_required",
      "agent_command_confirmation_invalidated",
      "agent_command_plan_replanned",
      "agent_command_plan_applied",
      "agent_command_plan_rejected",
      "agent_action_receipt_created",
      "agent_planning_continuation_queued",
      "canvas_variation_draft_saved",
      "canvas_variation_draft_discarded",
      "canvas_variation_materialized",
      "canvas_layout_updated",
    ]));
  });
});
