import { describe, expect, it } from "vitest";

import type { ChatMessageV2, ChatTimelineItemV2 } from "../../../types-v2.ts";
import { projectNaturalMessagePresentation } from "./naturalMessagePresentation.ts";

function message(
  messageId: string,
  speaker: ChatMessageV2["speaker"],
  text = "Message",
): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "conversation",
    message_id: messageId,
    conversation_id: "conversation-1",
    speaker,
    text,
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence: Number(messageId.replace(/\D/g, "")) || 1,
    created_at: "2026-08-27T00:00:00Z",
  };
}

describe("projectNaturalMessagePresentation", () => {
  it("shows Agent identity only at the start of a consecutive Agent run", () => {
    const result = projectNaturalMessagePresentation([
      message("message-1", "adcraft_video_agent"),
      message("message-2", "adcraft_video_agent"),
      message("message-3", "user"),
      message("message-4", "adcraft_video_agent"),
    ]);

    expect(result.get("message-1")).toEqual({
      messageId: "message-1",
      showAgentIdentity: true,
      startsSpeakerRun: true,
    });
    expect(result.get("message-2")).toMatchObject({
      showAgentIdentity: false,
      startsSpeakerRun: false,
    });
    expect(result.get("message-4")).toMatchObject({
      showAgentIdentity: true,
      startsSpeakerRun: true,
    });
  });

  it("uses any typed non-message item as a run boundary", () => {
    const boundary = { item_type: "proposal_pointer" } as ChatTimelineItemV2;
    const result = projectNaturalMessagePresentation([
      message("message-1", "adcraft_video_agent"),
      boundary,
      message("message-2", "adcraft_video_agent"),
    ]);

    expect(result.get("message-2")?.showAgentIdentity).toBe(true);
  });

  it("keeps consecutive user messages distinct without Agent identity", () => {
    const result = projectNaturalMessagePresentation([
      message("message-1", "user", "Summary:"),
      message("message-2", "user", "Arbitrary text"),
    ]);

    expect(result.get("message-1")).toMatchObject({
      showAgentIdentity: false,
      startsSpeakerRun: true,
    });
    expect(result.get("message-2")).toMatchObject({
      showAgentIdentity: false,
      startsSpeakerRun: false,
    });
  });

  it("does not use message text to determine grouping", () => {
    const result = projectNaturalMessagePresentation([
      message("message-1", "adcraft_video_agent", "Next action: choose a style"),
      message("message-2", "adcraft_video_agent", "结果：已完成"),
    ]);

    expect(result.get("message-2")?.showAgentIdentity).toBe(false);
  });
});
