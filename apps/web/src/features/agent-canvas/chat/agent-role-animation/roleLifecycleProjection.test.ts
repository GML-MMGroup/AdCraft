import { describe, expect, it } from "vitest";
import type {
  AgentCanvasChatTurnV2,
  ChatCapabilityActivityV2,
  ChatProposalCardV2,
  ChatMessageV2,
} from "../../../../types-v2.ts";
import { buildStageThreadTimeline, type StageThreadUnit } from "../stageThreadProjection.ts";
import { normalizeAgentCanvasChatTimelineV2 } from "../../model/normalizers.ts";
import { mergeRoleLifecycles, projectRoleLifecycles, roleTerminal, useTimelineRoleLifecycles } from "./roleLifecycleProjection.ts";
import { renderHook } from "@testing-library/react";

function turn(id: string, status: AgentCanvasChatTurnV2["status"], request: Record<string, unknown> = {}): AgentCanvasChatTurnV2 {
  return { turn_id: id, workflow_id: "workflow-1", conversation_id: "conversation-1", status,
    turn_kind: "capability", request, error_code: null, error_message: null, creation_mode: null,
    guidance_session_revision: null, continuation: null, retry_of_turn_id: null, retry_attempt_no: 0,
    retryable: false, operation_stage: null, operation_failure: null,
    created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z" };
}

function activity(id: string, turnId: string, status: ChatCapabilityActivityV2["status"], sequence = 1): ChatCapabilityActivityV2 {
  return { item_type: "expert_activity", activity_id: id, turn_id: turnId, capability_id: "character_design",
    capability_display_name: "Character Designer", status, sequence, started_at: "2026-09-07T00:00:00Z",
    finished_at: null, message: null, error_code: null, elapsed_ms: null, attempt_stage: null,
    retryable: false, validation_paths: [], suggested_actions: [], completion_mode: null, warning_code: null };
}

function proposal(occurrenceId: string, turnId: string, nodeIds: string[], sequence = 2): ChatProposalCardV2 {
  return { item_type: "proposal", sequence, created_at: "2026-09-07T00:00:00Z", proposal: {
    proposal_id: `proposal-${occurrenceId}`, workflow_id: "workflow-1", turn_id: `proposal-turn-${occurrenceId}`,
    video_skill_run_id: null, topic_id: null, occurrence_id: occurrenceId, occurrence_index: 1,
    occurrence_count: 2, character_phase: "main", creative_direction_snapshot_id: null, proposal_revision: 1,
    source_proposal_id: null, proposal_kind: "character", capability_id: "character_design",
    capability_display_name: "Character Designer", options: [], proposed_references: [], target_node_id: nodeIds[0] ?? null,
    target_node_revision: null, proposal_purpose: null, availability: "applied", application_count: 1,
    latest_application: { application_id: `application-${occurrenceId}`, option_id: "option-1", action: "select_option",
      receipt_id: `receipt-${occurrenceId}`, created_node_ids: nodeIds, queued_execution_ids: [],
      created_at: "2026-09-07T00:00:00Z" }, guidance_session_id: "session-1", guidance_session_revision: 1,
    actions: [], created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z",
    materialization: { materialization_id: `materialization-${occurrenceId}`, option_id: "option-1", turn_id: turnId,
      status: "completed", attempt_no: 1, retryable: false, error: null,
      created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z" } } };
}

function thread(proposals: ChatProposalCardV2[] = []): StageThreadUnit {
  return { unit_type: "stage_thread", key: "stage:character_design", capability_id: "character_design",
    capability_display_name: "Character Designer", sequence: 1, status: "working", planning: [],
    activities: [], proposals, receipts: [], selected_option: null, completed_activity_count: 0 };
}


function input(activities: ChatCapabilityActivityV2[] = [activity("a", "t", "working")]) {
  return { workflowId: "workflow-1", threads: [{ ...thread(), activities }], turnsById: {} as Record<string, AgentCanvasChatTurnV2> };
}
function state(value = input()) {
  return projectRoleLifecycles(value).get("stage:character_design")!;
}

function planning(card: ChatProposalCardV2, metadata: Record<string, unknown> = {}, presentation = false): ChatMessageV2 {
  const entry = {
    entry_id: "planning-selected", workflow_id: "workflow-1", conversation_id: "conversation-1",
    entry_type: "planning_progress", sequence_no: 8, speaker: null,
    content: "Preparing the selected direction.", created_at: "2026-09-07T00:00:00Z",
    metadata: { capability_id: card.proposal.capability_id, proposal_id: card.proposal.proposal_id,
      materialization_id: card.proposal.materialization?.materialization_id, status: "queued", ...metadata },
  };
  const normalized = normalizeAgentCanvasChatTimelineV2({
    workflow_id: "workflow-1", conversation_id: "conversation-1", items: [entry], next_cursor: 8,
    ...(presentation ? { presentation_items: [{ ...entry, presentation_key: "planning:selected",
      presentation_revision: 1, source_entry_ids: [entry.entry_id], message_key: "planning_progress.next_action",
      message_args: {}, response_locale: "en-US" }] } : {}),
  });
  return (presentation ? normalized.presentationItems![0]!.item : normalized.items[0]) as ChatMessageV2;
}

describe("planning ownership through the real Timeline normalizer", () => {
  it.each([false, true])("settles a completed World Setting despite later queued planning (presentation=%s)", presentation => {
    const card = proposal("world", "materialization-turn", [], 7);
    card.proposal.capability_id = "world_setting";
    card.proposal.proposal_kind = "world_setting";
    const message = planning(card, {}, presentation);
    expect(message.metadata).toMatchObject({ materialization_id: "materialization-world", status: "queued" });
    const threads = buildStageThreadTimeline([card, message]).filter((unit): unit is StageThreadUnit => unit.unit_type === "stage_thread");
    const result = projectRoleLifecycles({ workflowId: "workflow-1", threads, turnsById: {} }).get("stage:world_setting");
    expect(result).toMatchObject({ motionState: "idle", terminal: "completed", sequence: 8,
      attemptKey: "materialization:materialization-world:1" });
  });

  it.each(["queued", "working", "completed", "failed"] as const)("inherits owning materialization %s, not planning copy", status => {
    const card = proposal("one", "m", [], 7);
    card.proposal.materialization!.status = status;
    expect(state({ ...input(), threads: [{ ...thread([card]), planning: [planning(card)] }] }).motionState)
      .toBe(status === "queued" || status === "working" ? "working" : "idle");
  });

  it("accepts terminal hydration at the planning sequence and rejects stale working refresh", () => {
    const card = proposal("one", "m", [], 7);
    const message = planning(card);
    const before = { ...input([]), threads: [{ ...thread(), planning: [message] }] };
    const after = { ...before, threads: [{ ...thread([card]), planning: [message] }] };
    const pending = projectRoleLifecycles(before);
    const settled = mergeRoleLifecycles(pending, projectRoleLifecycles(after));
    expect(settled.get("stage:character_design")).toMatchObject({ motionState: "idle", sequence: 8 });
    card.proposal.materialization!.status = "working";
    expect(mergeRoleLifecycles(settled, projectRoleLifecycles(after)).get("stage:character_design")?.motionState).toBe("idle");
    card.proposal.materialization!.attempt_no = 2;
    expect(mergeRoleLifecycles(settled, projectRoleLifecycles(after)).get("stage:character_design")?.motionState).toBe("working");
  });

  it("uses legacy proposal-only planning identity without requiring a Turn", () => {
    const card = proposal("one", "m", [], 7);
    const message = planning(card, { materialization_id: undefined });
    expect(state({ ...input(), threads: [{ ...thread([card]), planning: [message] }] }).motionState).toBe("idle");
  });

  it.each([
    { materialization_id: "unrelated-materialization" },
    { proposal_id: "unrelated-proposal" },
  ])("does not use another task's terminal when explicit identity differs: %j", metadata => {
    const card = proposal("one", "m", [], 7);
    const message = planning(card, metadata);
    expect(state({ ...input(), threads: [{ ...thread([card]), planning: [message] }] }).motionState).toBe("working");
  });

  it("does not inherit a terminal from a cross-workflow proposal", () => {
    const card = proposal("one", "m", [], 7);
    const message = planning(card);
    card.proposal.workflow_id = "different-workflow";
    expect(state({ ...input(), threads: [{ ...thread([card]), planning: [message] }] }).motionState).toBe("working");
  });

  it("keeps a genuinely new unassociated planning task working after old work completed", () => {
    const card = proposal("one", "m", [], 7);
    const message = planning(card, { proposal_id: undefined, materialization_id: undefined, turn_id: "new-turn" });
    expect(state({ ...input(), threads: [{ ...thread([card]), planning: [message] }] }).motionState).toBe("working");
  });

  it("preserves exact Turn terminal for standalone planning", () => {
    const message = planning(proposal("one", "m", []), { proposal_id: undefined, materialization_id: undefined, turn_id: "planning-turn" });
    expect(state({ ...input([]), threads: [{ ...thread(), planning: [message] }], turnsById: { "planning-turn": turn("planning-turn", "completed") } }).motionState).toBe("idle");
  });
});
describe("Timeline role presentation lifecycle", () => {
  it("starts without Turn hydration", () => {
    expect(state().motionState).toBe("working");
  });
  it.each(["queued", "running"] as const)("ignores %s intermediate Turn state", status => {
    expect(state({ ...input(), turnsById: { t: turn("t", status) } }).motionState).toBe("working");
  });
  it.each(["reserved", "provider_waiting", "waiting", "publishing"])("ignores operation stage %s", stage => {
    expect(state({ ...input(), turnsById: { t: { ...turn("t", "running"), operation_stage: stage } } }).motionState).toBe("working");
  });
  it.each(["completed", "failed", "superseded"] as const)("settles explicit activity %s even with stale running Turn", status => {
    expect(state({ ...input([activity("a", "t", status)]), turnsById: { t: turn("t", "running") } }))
      .toMatchObject({ terminal: status, motionState: "idle" });
  });
  it.each(["completed", "failed", "superseded"] as const)("settles exact Turn %s even with stale working activity", status => {
    expect(state({ ...input(), turnsById: { t: turn("t", status) } }))
      .toMatchObject({ terminal: status, motionState: "idle" });
  });
  it("settles explicitly cancelled operation without adding a new wire status", () => {
    expect(state({ ...input(), turnsById: { t: { ...turn("t", "running"), operation_stage: "cancelled" } } }))
      .toMatchObject({ terminal: "cancelled", motionState: "idle" });
    expect(roleTerminal("cancelled")).toBe("cancelled");
  });
  it("ignores unrelated and cross-workflow terminal turns", () => {
    expect(state({ ...input(), turnsById: { other: turn("other", "failed"), t: { ...turn("t", "failed"), workflow_id: "elsewhere" } } }).motionState).toBe("working");
  });
  it("does not use a previous activity terminal to stop a new attempt", () => {
    expect(state(input([activity("old", "old", "failed", 1), activity("new", "new", "working", 2)])).motionState).toBe("working");
  });
  it("open proposal keeps working without consulting its completed creation Turn", () => {
    const card = proposal("one", "m", []);
    card.proposal.materialization = null;
    card.proposal.availability = "open";
    expect(state({ ...input(), threads: [thread([card])], turnsById: { [card.proposal.turn_id]: turn(card.proposal.turn_id, "completed") } }).motionState).toBe("working");
  });
  it.each(["queued", "working", "completed", "failed"] as const)("uses materialization %s only for an explicit terminal", status => {
    const card = proposal("one", "m", []);
    card.proposal.materialization!.status = status;
    expect(state({ ...input(), threads: [thread([card])] }).motionState)
      .toBe(status === "queued" || status === "working" ? "working" : "idle");
  });
  it("hands motion from the previous role to the newly entered role", () => {
    const first = input().threads[0]!;
    const second = { ...first, key: "stage:scene_design", capability_id: "scene_design" as const,
      activities: [activity("second", "second", "working", 2)] };
    const both = projectRoleLifecycles({ ...input(), threads: [first, second] });
    expect([...both.values()].map(x => x.motionState)).toEqual(["idle", "working"]);
    first.activities = [activity("a", "t", "completed")];
    expect([...projectRoleLifecycles({ ...input(), threads: [first, second] }).values()].map(x => x.motionState)).toEqual(["idle", "working"]);
  });
  it("keeps a completed role working while the conversation can still hand off", () => {
    const completed = input([activity("a", "t", "completed")]);
    expect(projectRoleLifecycles({ ...completed, conversationWorking: true })
      .get("stage:character_design")?.motionState).toBe("working");

    const next = {
      ...completed,
      conversationWorking: true,
      threads: [
        completed.threads[0]!,
        {
          ...completed.threads[0]!,
          key: "stage:scene_design",
          capability_id: "scene_design" as const,
          activities: [activity("scene", "scene-turn", "working", 2)],
        },
      ],
    };
    const projected = projectRoleLifecycles(next);
    expect(projected.get("stage:character_design")?.motionState).toBe("idle");
    expect(projected.get("stage:scene_design")?.motionState).toBe("working");
  });
  it("keeps terminal across stale refresh and permits a newer retry", () => {
    const done = projectRoleLifecycles(input([activity("a", "t", "failed")]));
    const stale = mergeRoleLifecycles(done, projectRoleLifecycles(input()));
    expect(stale.get("stage:character_design")?.motionState).toBe("idle");
    const retry = mergeRoleLifecycles(stale, projectRoleLifecycles(input([activity("retry", "retry", "working", 2)])));
    expect(retry.get("stage:character_design")?.motionState).toBe("working");
    expect(mergeRoleLifecycles(retry, done).get("stage:character_design")?.motionState).toBe("working");
  });
  it("resets retained evidence on Workflow change", () => {
    const { result, rerender } = renderHook(useTimelineRoleLifecycles, { initialProps: input([activity("a", "t", "failed")]) });
    rerender(input());
    expect(result.current.get("stage:character_design")?.motionState).toBe("idle");
    rerender({ ...input(), workflowId: "workflow-2" });
    expect(result.current.get("stage:character_design")?.motionState).toBe("working");
  });
  it("does not compare proposal revision against materialization attempt number", () => {
    const card = proposal("one", "m", []);
    card.proposal.proposal_revision = 5;
    const materialization = card.proposal.materialization!;
    card.proposal.materialization = null;
    const before = projectRoleLifecycles({ ...input(), threads: [thread([card])] });
    card.proposal.materialization = { ...materialization, status: "queued" };
    const started = mergeRoleLifecycles(before, projectRoleLifecycles({ ...input(), threads: [thread([card])] }));
    expect(started.get("stage:character_design")?.motionState).toBe("working");
    card.proposal.materialization.status = "failed";
    const failed = mergeRoleLifecycles(started, projectRoleLifecycles({ ...input(), threads: [thread([card])] }));
    card.proposal.materialization = { ...materialization, status: "queued", attempt_no: 2 };
    const retry = mergeRoleLifecycles(failed, projectRoleLifecycles({ ...input(), threads: [thread([card])] }));
    expect(retry.get("stage:character_design")?.motionState).toBe("working");
    expect(mergeRoleLifecycles(retry, failed).get("stage:character_design")?.motionState).toBe("working");
  });
  it("retains completed historical roles on reload", () => {
    expect(state(input([activity("a", "t", "completed")])).motionState).toBe("idle");
  });
});
