import { describe, expect, it } from "vitest";

import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import { projectChatEvents } from "./projectChatEvents.ts";

function event(
  seq: number,
  eventType: string,
  payload: Record<string, unknown>,
): CanvasRuntimeEventV2 {
  return {
    seq,
    workflow_id: "workflow-1",
    event_type: eventType,
    execution_id: null,
    node_id: null,
    asset_id: null,
    binding_id: null,
    created_at: `2026-07-28T00:00:0${seq}Z`,
    payload,
  };
}

describe("projectChatEvents", () => {
  it("updates one capability activity row when canonical events are replayed", () => {
    const items = projectChatEvents([
      event(1, "expert_activity_started", {
        activity_id: "activity-1",
        turn_id: "turn-1",
        capability_id: "character_design",
        capability_display_name: "Character Designer",
      }),
      event(2, "expert_activity_completed", {
        activity_id: "activity-1",
        turn_id: "turn-1",
        capability_id: "character_design",
        capability_display_name: "Character Designer",
      }),
      event(2, "expert_activity_completed", {
        activity_id: "activity-1",
        turn_id: "turn-1",
        capability_id: "character_design",
        capability_display_name: "Character Designer",
      }),
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      item_type: "expert_activity",
      capability_id: "character_design",
      capability_display_name: "Character Designer",
      status: "completed",
    });
  });

  it("projects canonical failed capability activity and ignores retired aliases", () => {
    const items = projectChatEvents([
      event(1, "specialist_activity_started", {
        activity_id: "retired-activity",
        turn_id: "turn-retired",
        specialist: "scene_designer",
      }),
      event(2, "expert_activity_started", {
        activity_id: "activity-2",
        turn_id: "turn-2",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
      }),
      event(3, "expert_activity_failed", {
        activity_id: "activity-2",
        turn_id: "turn-2",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        error_code: "agent_transport_failed",
        retryable: true,
        suggested_actions: ["retry", "revise_request"],
      }),
    ]);

    expect(items).toEqual([
      expect.objectContaining({
        activity_id: "activity-2",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        status: "failed",
        error_code: "agent_transport_failed",
        suggested_actions: ["retry", "revise_request"],
      }),
    ]);
  });

  it("ignores capability events without a stable activity id", () => {
    expect(projectChatEvents([
      event(4, "expert_activity_started", {
        turn_id: "turn-3",
        capability_id: "product_design",
        capability_display_name: "Product Designer",
        operation: "internal_product_operation",
      }),
    ])).toEqual([]);
  });

  it("does not synthesize proposals from partial SSE payloads", () => {
    const items = projectChatEvents([
      event(3, "concept_options_ready", {
        proposal_id: "proposal-1",
        turn_id: "turn-1",
        capability_id: "scene_design",
        capability_display_name: "Scene Designer",
        proposal_kind: "scene",
        options: [
          { option_id: "option-1", title: "Morning", public_summary: "Soft daylight." },
          { option_id: "option-2", title: "Night", public_summary: "Neon city." },
        ],
        workflow_revision: 2,
      }),
      event(4, "proposal_selected", {
        proposal_id: "proposal-1",
        option_id: "option-2",
      }),
    ]);

    expect(items).toEqual([]);
  });

  it("does not project retired script artifact events", () => {
    const scriptEvent = event(5, "script_artifact_created", {
      entry_id: "artifact-1",
      script_node_id: "node-script-1",
      source_turn_id: "turn-1",
    });
    scriptEvent.node_id = "node-script-1";

    expect(projectChatEvents([scriptEvent])).toEqual([]);
  });
});
