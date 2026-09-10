import { describe, expect, it } from "vitest";

import type { ChatTimelinePresentationViewItemV2 } from "../../../types-v2.ts";
import {
  localizeTimelinePresentationItem,
  mergeTimelinePresentationItems,
  visibleTimelinePresentationItems,
} from "./timelinePresentation.ts";

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

function completedActivityPresentation(
  responseLocale: string,
): ChatTimelinePresentationViewItemV2 {
  return {
    presentation_key: "activity:world-setting-1:completed",
    presentation_revision: 1,
    source_entry_ids: ["activity-entry-completed"],
    message_key: "expert_activity.completed",
    message_args: {
      capability_display_name: "World Setting",
    },
    response_locale: responseLocale,
    item: {
      item_type: "expert_activity",
      activity_id: "activity-world-setting-1",
      turn_id: "turn-world-setting-1",
      capability_id: "world_setting",
      capability_display_name: "World Setting Designer",
      status: "completed",
      sequence: 12,
      started_at: "2026-08-21T06:17:00Z",
      finished_at: "2026-08-21T06:18:00Z",
      message: null,
      error_code: null,
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

function acknowledgementPresentation({
  key = "acknowledgement:turn-guided-1",
  revision = 1,
  sequence,
  sourceEntryIds,
  messageId,
  text,
}: {
  key?: string;
  revision?: number;
  sequence: number;
  sourceEntryIds: string[];
  messageId: string;
  text: string;
}): ChatTimelinePresentationViewItemV2 {
  return {
    presentation_key: key,
    presentation_revision: revision,
    source_entry_ids: sourceEntryIds,
    message_key: null,
    message_args: {},
    response_locale: "en-US",
    item: {
      item_type: "message",
      message_id: messageId,
      conversation_id: "conversation-1",
      speaker: "adcraft_video_agent",
      text,
      linked_node_ids: [],
      script_node_id: null,
      proposal_id: null,
      sequence,
      created_at: "2026-09-03T10:00:00Z",
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
  it.each(["en-US", "zh-CN"])(
    "does not manufacture a redundant completion body for %s",
    (responseLocale) => {
      const presentation = completedActivityPresentation(responseLocale);
      expect(localizeTimelinePresentationItem(presentation)).toBe(presentation.item);
    },
  );

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

describe("timeline presentation reconciliation", () => {
  it("uses the later sequence when the same key has the same revision", () => {
    const earlier = acknowledgementPresentation({
      sequence: 20,
      sourceEntryIds: ["receipt-entry"],
      messageId: "receipt-projection",
      text: "Canvas updated.",
    });
    const later = acknowledgementPresentation({
      sequence: 21,
      sourceEntryIds: ["agent-message-entry"],
      messageId: "agent-acknowledgement",
      text: "I applied your selection.",
    });

    const merged = mergeTimelinePresentationItems(
      new Map([[earlier.presentation_key, earlier]]),
      [later],
    );

    expect(merged.get(earlier.presentation_key)).toMatchObject({
      item: {
        message_id: "agent-acknowledgement",
        sequence: 21,
      },
      source_entry_ids: ["receipt-entry", "agent-message-entry"],
    });
  });

  it("keeps the source identity union when an older record is replayed", () => {
    const later = acknowledgementPresentation({
      sequence: 21,
      sourceEntryIds: ["agent-message-entry"],
      messageId: "agent-acknowledgement",
      text: "I applied your selection.",
    });
    const replayedEarlier = acknowledgementPresentation({
      sequence: 20,
      sourceEntryIds: ["receipt-entry", "agent-message-entry"],
      messageId: "receipt-projection",
      text: "Canvas updated.",
    });

    const merged = mergeTimelinePresentationItems(
      new Map([[later.presentation_key, later]]),
      [replayedEarlier, replayedEarlier],
    );

    expect(merged.get(later.presentation_key)).toMatchObject({
      item: { message_id: "agent-acknowledgement" },
      source_entry_ids: ["agent-message-entry", "receipt-entry"],
    });
    expect(merged).toHaveLength(1);
  });

  it("does not coalesce identical prose from different presentation keys", () => {
    const first = acknowledgementPresentation({
      key: "acknowledgement:turn-1",
      sequence: 30,
      sourceEntryIds: ["message-entry-1"],
      messageId: "message-1",
      text: "The workflow is ready.",
    });
    const second = acknowledgementPresentation({
      key: "acknowledgement:turn-2",
      sequence: 31,
      sourceEntryIds: ["message-entry-2"],
      messageId: "message-2",
      text: "The workflow is ready.",
    });

    const merged = mergeTimelinePresentationItems(new Map(), [first, second]);

    expect(visibleTimelinePresentationItems(merged)).toHaveLength(2);
  });
});
