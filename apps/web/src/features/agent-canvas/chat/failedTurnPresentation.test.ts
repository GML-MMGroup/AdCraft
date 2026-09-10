import { describe, expect, it } from "vitest";

import type {
  AgentCanvasChatTurnV2,
  ChatMessageV2,
  ChatTimelineItemV2,
} from "../../../types-v2.ts";
import { projectFailedMessageTurns } from "./failedTurnPresentation.ts";

function message({
  messageId,
  speaker = "user",
  turnId,
}: {
  messageId: string;
  speaker?: ChatMessageV2["speaker"];
  turnId?: string;
}): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "conversation",
    message_id: messageId,
    conversation_id: "conversation-1",
    speaker,
    text: messageId,
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    metadata: turnId ? { turn_id: turnId } : {},
    sequence: 1,
    created_at: "2026-09-03T10:00:00Z",
  };
}

function turn(
  turnId: string,
  overrides: Partial<AgentCanvasChatTurnV2> = {},
): AgentCanvasChatTurnV2 {
  return {
    turn_id: turnId,
    workflow_id: "workflow-1",
    conversation_id: "conversation-1",
    status: "failed",
    turn_kind: "message",
    request: {},
    error_code: "agent_runtime_unavailable",
    error_message: "The agent runtime is unavailable.",
    creation_mode: null,
    guidance_session_revision: null,
    continuation: null,
    retry_of_turn_id: null,
    retry_attempt_no: 0,
    retryable: true,
    operation_stage: "failed",
    operation_failure: null,
    created_at: "2026-09-03T10:00:00Z",
    updated_at: "2026-09-03T10:00:01Z",
    ...overrides,
  };
}

describe("failed Turn presentation", () => {
  it("maps a failed message Turn to its structured source user message", () => {
    const items: ChatTimelineItemV2[] = [
      message({ messageId: "user-message-1", turnId: "turn-1" }),
    ];

    const projected = projectFailedMessageTurns(items, {
      "turn-1": turn("turn-1"),
    });

    expect(projected.get("user-message-1")?.turn_id).toBe("turn-1");
  });

  it("does not infer a failed Turn for a message without structured identity", () => {
    const items: ChatTimelineItemV2[] = [
      message({ messageId: "user-message-1" }),
    ];

    expect(projectFailedMessageTurns(items, {
      "turn-1": turn("turn-1"),
    })).toHaveLength(0);
  });

  it("excludes Agent messages and non-message Turns", () => {
    const items: ChatTimelineItemV2[] = [
      message({ messageId: "agent-message", speaker: "adcraft_video_agent", turnId: "turn-1" }),
      message({ messageId: "user-message", turnId: "turn-capability" }),
    ];

    expect(projectFailedMessageTurns(items, {
      "turn-1": turn("turn-1"),
      "turn-capability": turn("turn-capability", { turn_kind: "capability" }),
    })).toHaveLength(0);
  });

  it("excludes message Turns that are not failed", () => {
    const items: ChatTimelineItemV2[] = [
      message({ messageId: "user-message", turnId: "turn-running" }),
    ];

    expect(projectFailedMessageTurns(items, {
      "turn-running": turn("turn-running", { status: "running" }),
    })).toHaveLength(0);
  });

  it("removes the source failure after its retry Turn completes", () => {
    const items: ChatTimelineItemV2[] = [
      message({ messageId: "user-message", turnId: "turn-original" }),
    ];

    expect(projectFailedMessageTurns(items, {
      "turn-original": turn("turn-original"),
      "turn-retry": turn("turn-retry", {
        status: "completed",
        retry_of_turn_id: "turn-original",
        retry_attempt_no: 1,
      }),
    })).toHaveLength(0);
  });

  it("uses the latest failed retry Turn for the source user message", () => {
    const items: ChatTimelineItemV2[] = [
      message({ messageId: "user-message", turnId: "turn-original" }),
    ];

    const projected = projectFailedMessageTurns(items, {
      "turn-original": turn("turn-original", { retry_attempt_no: 0 }),
      "turn-retry": turn("turn-retry", {
        retry_of_turn_id: "turn-original",
        retry_attempt_no: 1,
        error_code: "agent_deadline_exceeded",
      }),
    });

    expect(projected.get("user-message")?.turn_id).toBe("turn-retry");
  });
});
