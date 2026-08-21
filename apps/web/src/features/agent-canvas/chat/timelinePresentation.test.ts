import { describe, expect, it } from "vitest";

import type { ChatTimelinePresentationViewItemV2 } from "../../../types-v2.ts";
import { localizeTimelinePresentationItem } from "./timelinePresentation.ts";

function mediaReviewPresentation(
  responseLocale: string,
  allowedActions: unknown,
): ChatTimelinePresentationViewItemV2 {
  return {
    presentation_key: "turn:turn-review-1:media-review-wait",
    presentation_revision: 1,
    source_entry_ids: ["entry-review-1"],
    message_key: "media_review.pending_action",
    message_args: {
      allowed_actions: allowedActions,
      media_title: "Storyboard Grid 1",
    },
    response_locale: responseLocale,
    item: {
      item_type: "message",
      message_id: "message-review-1",
      conversation_id: "conversation-1",
      speaker: "adcraft_video_agent",
      text: "Backend fallback content",
      linked_node_ids: [],
      script_node_id: null,
      proposal_id: null,
      sequence: 7,
      created_at: "2026-08-20T10:00:00Z",
    },
  };
}

function supersededActivityPresentation(
  responseLocale: string,
): ChatTimelinePresentationViewItemV2 {
  return {
    presentation_key: "activity:storyboard-1:superseded",
    presentation_revision: 1,
    source_entry_ids: ["activity-entry-43"],
    message_key: "expert_activity.superseded",
    message_args: {
      capability_display_name: "Storyboard Artist",
    },
    response_locale: responseLocale,
    item: {
      item_type: "expert_activity",
      activity_id: "activity-storyboard-1",
      turn_id: "turn-storyboard-1",
      capability_id: "storyboard_design",
      capability_display_name: "Storyboard Artist",
      status: "superseded",
      sequence: 43,
      started_at: "2026-08-21T06:17:00Z",
      finished_at: "2026-08-21T06:18:00Z",
      message: null,
      error_code: "guidance_revision_conflict",
      elapsed_ms: 60000,
      attempt_stage: "initial",
      retryable: false,
      validation_paths: [],
      suggested_actions: [],
      completion_mode: null,
      warning_code: null,
    },
  };
}

describe("media review timeline presentation", () => {
  it("localizes the pending review title and canonical actions in English", () => {
    expect(localizeTimelinePresentationItem(
      mediaReviewPresentation("en-US", ["accept", "retry", "replace"]),
    )).toMatchObject({
      item_type: "message",
      text: "Storyboard Grid 1 is waiting for review. Available actions: Accept, Retry, and Replace.",
    });
  });

  it("localizes the pending review title and canonical actions in Chinese", () => {
    expect(localizeTimelinePresentationItem(
      mediaReviewPresentation("zh-CN", ["accept", "retry", "replace", "exclude"]),
    )).toMatchObject({
      item_type: "message",
      text: "Storyboard Grid 1 正在等待审核。可用操作：接受、重试、替换和排除。",
    });
  });

  it("falls back to backend content for unsupported review arguments", () => {
    expect(localizeTimelinePresentationItem(
      mediaReviewPresentation("zh-CN", ["accept", "future_action"]),
    )).toMatchObject({
      item_type: "message",
      text: "Backend fallback content",
    });
  });
});

describe("expert activity timeline presentation", () => {
  it("localizes expert_activity_superseded without failure semantics", () => {
    expect(localizeTimelinePresentationItem(
      supersededActivityPresentation("zh-CN"),
    )).toMatchObject({
      item_type: "expert_activity",
      status: "superseded",
      presentation_text: "Storyboard Artist 任务已被后续进度取代。",
    });
  });
});
