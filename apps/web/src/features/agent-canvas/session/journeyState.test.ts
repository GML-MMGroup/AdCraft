import { describe, expect, it } from "vitest";

import type { GuidedSessionStateV2 } from "../../../types-v2.ts";
import {
  mergeGuidedSessionState,
  journeyStageFromEvent,
} from "./journeyState.ts";

function session(overrides: Partial<GuidedSessionStateV2> = {}): GuidedSessionStateV2 {
  return {
    session_id: "session-1",
    workflow_id: "workflow-1",
    status: "active",
    goal: {
      requested_output: "video",
      delivery_scope: "generated_media",
      summary: "Create a launch film.",
      explicit_constraints: {},
    },
    creative_authority: null,
    current_checkpoint: null,
    narrative_direction: null,
    element_decisions: [],
    current_topic_id: null,
    topics: [],
    active_proposal_id: null,
    active_style_skill_run_id: null,
    completion: {
      authoring: "not_ready",
      delivery: "not_ready",
      editing_preparation: "not_ready",
      editing_node_id: null,
      matching_node_ids: [],
      matching_asset_ids: [],
    },
    journey: {
      policy_version: "fixed_ad_production_v1",
      stage: "foundation_design",
      stage_status: "waiting_user",
      stage_revision: 4,
      foundation_queue: [{
        item_id: "character-1",
        kind: "character",
        occurrence_index: 1,
        requirement_source: "explicit_user",
        required: true,
        status: "active",
        topic_id: "topic-character",
        selected_node_ids: [],
      }],
      foundation_cursor: 0,
      active_action: null,
      suspended_action: null,
      transition_evidence: [],
    },
    revision: 8,
    updated_at: "2026-08-10T00:00:00Z",
    ...overrides,
  };
}

describe("persisted production journey state", () => {
  it("keeps a newer journey when a stale timeline response arrives", () => {
    const current = session();
    const stale = session({
      revision: 7,
      journey: {
        ...current.journey,
        stage: "world_setting",
        stage_revision: 3,
        foundation_cursor: null,
      },
    });

    expect(mergeGuidedSessionState(current, stale)).toBe(current);
  });

  it("accepts a higher session revision when the current stage is unchanged", () => {
    const current = session();
    const latest = session({
      revision: 9,
      journey: {
        ...current.journey,
        active_action: {
          action_id: "action-9",
          action_kind: "invoke_capability:character_design",
          stage: "foundation_design",
          status: "working",
          turn_id: "turn-9",
          foundation_item_id: "character-1",
        },
      },
    });

    expect(mergeGuidedSessionState(current, latest)).toBe(latest);
  });

  it("keeps the persisted journey during a targeted authoring update", () => {
    const current = session();
    const targetedUpdate = session({
      revision: 9,
      narrative_direction: "Keep the established visual direction.",
      journey: current.journey,
    });

    expect(mergeGuidedSessionState(current, targetedUpdate)).toMatchObject({
      narrative_direction: "Keep the established visual direction.",
      journey: {
        stage: "foundation_design",
        stage_revision: 4,
        foundation_cursor: 0,
      },
    });
  });

  it("extracts only a newer persisted journey event", () => {
    const current = session();
    expect(journeyStageFromEvent({
      event_type: "journey_stage_changed",
      payload: {
        session_revision: 9,
        stage_revision: 5,
        stage: "narrative_direction",
      },
    }, current)).toEqual({
      sessionRevision: 9,
      stageRevision: 5,
      stage: "narrative_direction",
    });
    expect(journeyStageFromEvent({
      event_type: "journey_stage_changed",
      payload: {
        session_revision: 7,
        stage_revision: 3,
        stage: "world_setting",
      },
    }, current)).toBeNull();
  });
});
