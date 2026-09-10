import { describe, expect, it } from "vitest";
import type { AgentCanvasChatTurnV2, ChatCapabilityActivityV2, ChatProposalCardV2 } from "../../../../types-v2.ts";
import type { StageThreadUnit } from "../stageThreadProjection.ts";
import { resolveAgentRoleMotionState, resolveStageThreadRoleMotionState } from "./resolveAgentRoleMotionState.ts";

function turn(overrides: Partial<AgentCanvasChatTurnV2> = {}): AgentCanvasChatTurnV2 {
  return { turn_id: "own", workflow_id: "workflow-1", conversation_id: "conversation-1", status: "running",
    turn_kind: "capability", request: {}, error_code: null, error_message: null, creation_mode: null,
    guidance_session_revision: null, continuation: null, retry_of_turn_id: null, retry_attempt_no: 0,
    retryable: false, operation_stage: "running", operation_failure: null,
    created_at: "2026-09-03T00:00:00Z", updated_at: "2026-09-03T00:00:00Z", ...overrides };
}

function activity(overrides: Partial<ChatCapabilityActivityV2> = {}): ChatCapabilityActivityV2 {
  return { item_type: "expert_activity", activity_id: "activity-1", turn_id: "own",
    capability_id: "scene_design", capability_display_name: "Scene Designer", status: "working", sequence: 1,
    started_at: "2026-09-03T00:00:00Z", finished_at: null, message: null, error_code: null,
    elapsed_ms: null, attempt_stage: null, retryable: false, validation_paths: [], suggested_actions: [],
    completion_mode: null, warning_code: null, ...overrides };
}

function proposal(status: "queued" | "working" | "failed" | "completed" = "working"): ChatProposalCardV2 {
  return { item_type: "proposal", sequence: 2, created_at: "2026-09-03T00:00:00Z", proposal: {
    proposal_id: "proposal-1", workflow_id: "workflow-1", turn_id: "proposal-turn", video_skill_run_id: null,
    topic_id: null, occurrence_id: null, occurrence_index: null, occurrence_count: null, character_phase: null,
    creative_direction_snapshot_id: null, proposal_revision: 1, source_proposal_id: null, proposal_kind: "scene",
    capability_id: "scene_design", capability_display_name: "Scene Designer", options: [], proposed_references: [],
    target_node_id: null, target_node_revision: null, proposal_purpose: null, availability: "applied",
    application_count: 0, latest_application: null, guidance_session_id: "guidance-1", guidance_session_revision: 1,
    actions: [], created_at: "2026-09-03T00:00:00Z", updated_at: "2026-09-03T00:00:00Z",
    materialization: { materialization_id: "materialization-1", option_id: "option-1",
      turn_id: "materialization-turn", status, attempt_no: 1, retryable: false, error: null,
      created_at: "2026-09-03T00:00:00Z", updated_at: "2026-09-03T00:00:00Z" } } };
}

function unit(overrides: Partial<StageThreadUnit> = {}): StageThreadUnit {
  return { unit_type: "stage_thread", key: "stage:scene_design", capability_id: "scene_design",
    capability_display_name: "Scene Designer", sequence: 1, status: "working", planning: [],
    activities: [activity()], proposals: [], receipts: [], selected_option: null, completed_activity_count: 0,
    ...overrides };
}

describe("resolveAgentRoleMotionState", () => {
  it.each([["working", "working"], ["failed", "idle"], ["queued", "waiting"], ["completed", "idle"],
    ["waiting_user", "waiting"], ["superseded", "idle"]] as const)("maps %s stage status to %s", (status, expected) => {
    expect(resolveAgentRoleMotionState({ status, turnId: "own" })).toBe(expected);
  });

  it("keeps provider waiting working", () => {
    expect(resolveAgentRoleMotionState({ status: "working", turnId: "own",
      turn: turn({ turn_id: "own", status: "running", operation_stage: "provider_waiting" }) })).toBe("working");
  });

  it.each(["queued", "completed", "failed", "superseded"] as const)(
    "stops a working role when its owning turn status is %s",
    (status) => {
      expect(resolveAgentRoleMotionState({ status: "working", turnId: "own",
        turn: turn({ turn_id: "own", status }) })).toBe("idle");
    },
  );

  it("ignores a terminal turn belonging to another role", () => {
    expect(resolveAgentRoleMotionState({ status: "working", turnId: "own",
      turn: turn({ turn_id: "other", status: "failed" }) })).toBe("working");
  });
});

describe("resolveStageThreadRoleMotionState", () => {
  it("uses the latest same-role activity so newer work revives independently", () => {
    const stage = unit({ activities: [activity({ sequence: 1, status: "failed", turn_id: "old" }),
      activity({ sequence: 3, status: "working", turn_id: "new" })] });
    expect(resolveStageThreadRoleMotionState(stage, { old: turn({ turn_id: "old", status: "failed" }),
      new: turn({ turn_id: "new", status: "running" }) })).toBe("working");
  });

  it("uses the materialization turn and keeps queued materialization gently waiting", () => {
    expect(resolveStageThreadRoleMotionState(unit({ activities: [], proposals: [proposal()] }), {
      "materialization-turn": turn({ turn_id: "materialization-turn", status: "failed" }),
    })).toBe("idle");
    expect(resolveStageThreadRoleMotionState(unit({ activities: [], proposals: [proposal("queued")] }), {})).toBe("waiting");
  });

  it("keeps a working materialization active from its own running turn, not the failed proposal turn", () => {
    expect(resolveStageThreadRoleMotionState(unit({ activities: [], proposals: [proposal()] }), {
      "proposal-turn": turn({ turn_id: "proposal-turn", status: "failed" }),
      "materialization-turn": turn({ turn_id: "materialization-turn", status: "running" }),
    })).toBe("working");
  });

  it("keeps a working materialization active before its owning turn is hydrated", () => {
    expect(resolveStageThreadRoleMotionState(unit({ activities: [], proposals: [proposal()] }), {
      "proposal-turn": turn({ turn_id: "proposal-turn", status: "failed" }),
    })).toBe("working");
  });

  it("keeps non-working and receipt-led threads static", () => {
    expect(resolveStageThreadRoleMotionState(unit({ status: "completed" }), {})).toBe("idle");
    expect(resolveStageThreadRoleMotionState(unit({ activities: [], receipts: [{ item_type: "action_receipt",
      sequence: 4, created_at: "2026-09-03T00:00:00Z", action_receipt: { receipt_id: "receipt-1" },
    } as StageThreadUnit["receipts"][number]] }), {})).toBe("idle");
  });
});
