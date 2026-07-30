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
  it("turns specialist events into one activity row instead of chat bubbles", () => {
    const items = projectChatEvents([
      event(1, "specialist_activity_started", {
        activity_id: "activity-1",
        turn_id: "turn-1",
        specialist: "character_designer",
        label: "Character Designer",
        operation: "create_concepts",
      }),
      event(2, "specialist_activity_completed", {
        activity_id: "activity-1",
        turn_id: "turn-1",
        specialist: "character_designer",
        label: "Character Designer",
        operation: "create_concepts",
      }),
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      item_type: "expert_activity",
      label: "Character Designer",
      status: "completed",
    });
  });

  it("does not synthesize proposals from partial SSE payloads", () => {
    const items = projectChatEvents([
      event(3, "concept_options_ready", {
        proposal_id: "proposal-1",
        turn_id: "turn-1",
        specialist_name: "scene_designer",
        proposal_kind: "scene",
        options: [
          { option_id: "option-1", title: "Morning", description: "Soft daylight." },
          { option_id: "option-2", title: "Night", description: "Neon city." },
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
