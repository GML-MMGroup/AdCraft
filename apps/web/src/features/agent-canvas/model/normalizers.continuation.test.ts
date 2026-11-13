import { describe, expect, it } from "vitest";
import { normalizeAgentCanvasChatTimelineResponseV2 } from "./normalizers";

const continuation = {
  continuation_id: "continuation-1",
  workflow_id: "workflow-1",
  conversation_id: "conversation-1",
  source_turn_id: "source-1",
  continuation_turn_id: "turn-1",
  operation: "next_action",
  occurrence_id: null,
  character_phase: null,
  action_owner: null,
  payload_digest: "digest-1",
  status: "completed",
  attempt_count: 0,
  max_attempts: 5,
  next_attempt_at: "2026-11-03T08:34:55.686434Z",
  lease_owner: null,
  lease_generation: 1,
  lease_expires_at: null,
  last_error_code: null,
  last_error_message: null,
  created_at: "2026-11-03T08:34:45.816696Z",
  updated_at: "2026-11-03T08:34:55.686434Z",
};

function timelineWith(fields: Record<string, unknown>) {
  return normalizeAgentCanvasChatTimelineResponseV2({
    workflow_id: "workflow-1",
    conversation_id: "conversation-1",
    continuations: [{ ...continuation, ...fields }],
    items: [],
    next_cursor: 0,
  });
}

describe("continuation runtime wait metadata", () => {
  it.each([
    {},
    { runtime_wait_started_at: null, runtime_wait_count: 0 },
    { runtime_wait_started_at: "2026-11-03T08:34:45.816696Z", runtime_wait_count: 2 },
  ])("keeps the conversation readable with supported metadata %j", fields => {
    expect(timelineWith(fields).continuations[0]).toMatchObject({
      continuation_id: "continuation-1",
      delivery_status: "completed",
      attempt_count: 0,
    });
  });

  it.each([
    { runtime_wait_started_at: "invalid-date" },
    { runtime_wait_count: -1 },
    { runtime_wait_count: 0.5 },
    { runtime_wait_count: "2" },
    { runtime_wait_count: null },
  ])("rejects malformed metadata %j", fields => {
    expect(() => timelineWith(fields)).toThrow(/runtime_wait_/);
  });

  it("still rejects undeclared continuation fields", () => {
    expect(() => timelineWith({ unknown_field: true })).toThrow(/unknown field/);
  });
});
