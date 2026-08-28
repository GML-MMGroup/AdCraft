import { describe, expect, it } from "vitest";

import type {
  AgentActionReceiptV2,
  ChatArtifactCardV2,
  ChatMessageV2,
  ChatProposalCardV2,
  GuidanceAwaitingV1,
} from "../../../types-v2.ts";
import {
  buildConversationCanvasLinkIndex,
  conversationLocationForNode,
} from "./conversationCanvasLinks.ts";
import type { StageThreadUnit, StageTimelineUnit } from "./stageThreadProjection.ts";

function message(overrides: Partial<ChatMessageV2> = {}): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "conversation",
    message_id: "message-1",
    conversation_id: "conversation-1",
    speaker: "adcraft_video_agent",
    text: "The storyboard is ready.",
    linked_node_ids: ["node-created"],
    script_node_id: null,
    proposal_id: null,
    capability_id: null,
    sequence: 10,
    created_at: "2026-08-27T00:00:00Z",
    ...overrides,
  };
}

function receipt(overrides: Partial<AgentActionReceiptV2> = {}): AgentActionReceiptV2 {
  return {
    receipt_id: "receipt-1",
    workflow_id: "workflow-1",
    plan_id: null,
    action_id: null,
    proposal_id: null,
    proposal_option_id: null,
    proposal_action: null,
    actor_kind: "agent",
    occurrence_id: null,
    character_phase: null,
    idempotency_key: null,
    status: "applied",
    summary: "Canvas updated",
    created_node_ids: ["node-created"],
    updated_node_ids: [],
    deleted_node_ids: [],
    created_binding_ids: [],
    deleted_binding_ids: [],
    queued_execution_ids: [],
    run_queue_errors: [],
    operation_results: [],
    workflow_revision: 2,
    before_workflow_revision: 1,
    placement_hints: [],
    continuation_turn_id: null,
    superseded_by: null,
    error_code: null,
    error_message: null,
    created_at: "2026-08-27T00:00:01Z",
    ...overrides,
  };
}

function proposal(createdNodeIds: string[]): ChatProposalCardV2 {
  return {
    item_type: "proposal",
    sequence: 12,
    created_at: "2026-08-27T00:00:02Z",
    proposal: {
      proposal_id: "proposal-1",
      workflow_id: "workflow-1",
      turn_id: "turn-1",
      capability_id: "storyboard_design",
      capability_display_name: "Storyboard Artist",
      video_skill_run_id: null,
      topic_id: null,
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "storyboard",
      options: [],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "applied",
      application_count: 1,
      latest_application: {
        application_id: "application-1",
        option_id: "option-1",
        action: "select_option",
        receipt_id: "receipt-1",
        created_node_ids: createdNodeIds,
        queued_execution_ids: [],
        created_at: "2026-08-27T00:00:02Z",
      },
      materialization: null,
      guidance_session_id: "session-1",
      guidance_session_revision: 2,
      actions: [],
      created_at: "2026-08-27T00:00:00Z",
      updated_at: "2026-08-27T00:00:02Z",
    },
  };
}

function thread(overrides: Partial<StageThreadUnit> = {}): StageThreadUnit {
  return {
    unit_type: "stage_thread",
    key: "stage:storyboard_design",
    capability_id: "storyboard_design",
    capability_display_name: "Storyboard Artist",
    sequence: 10,
    status: "completed",
    planning: [],
    activities: [],
    proposals: [],
    receipts: [],
    selected_option: null,
    completed_activity_count: 1,
    ...overrides,
  };
}

function item(itemValue: ChatMessageV2 | ChatArtifactCardV2): StageTimelineUnit {
  const id = itemValue.item_type === "message" ? itemValue.message_id : itemValue.artifact_id;
  return {
    unit_type: "item",
    key: `${itemValue.item_type}:${id}`,
    sequence: itemValue.sequence,
    item: itemValue,
  };
}

describe("buildConversationCanvasLinkIndex", () => {
  it("coalesces stage receipt and proposal results into one forward canvas location", () => {
    const stage = thread({
      proposals: [proposal(["node-created", "node-proposal-only"])],
      receipts: [{
        item_type: "action_receipt",
        sequence: 13,
        created_at: "2026-08-27T00:00:03Z",
        action_receipt: receipt({
          created_node_ids: ["node-created"],
          updated_node_ids: ["node-updated"],
          deleted_node_ids: ["node-deleted"],
        }),
      }],
    });

    const index = buildConversationCanvasLinkIndex([stage], null);
    const location = index.locations.get(stage.key);

    expect(location).toMatchObject({
      key: stage.key,
      createdNodeIds: ["node-created", "node-proposal-only"],
      updatedNodeIds: ["node-updated"],
      deletedNodeIds: ["node-deleted"],
      navigableNodeIds: ["node-created", "node-proposal-only", "node-updated"],
    });
    expect(location?.navigableNodeIds).not.toContain("node-deleted");
  });

  it("chooses creating receipt, latest update receipt, message, then artifact as reverse sources", () => {
    const linkedMessage = message({ sequence: 30, linked_node_ids: ["node-created", "node-updated", "node-message"] });
    const artifact: ChatArtifactCardV2 = {
      item_type: "artifact",
      artifact_id: "artifact-1",
      artifact_kind: "script",
      node_id: "node-artifact",
      title: "Script",
      summary: "Script draft",
      action_label: "View Script",
      source_turn_id: null,
      sequence: 40,
      created_at: "2026-08-27T00:00:04Z",
    };
    const createThread = thread({
      receipts: [{
        item_type: "action_receipt",
        sequence: 11,
        created_at: "2026-08-27T00:00:01Z",
        action_receipt: receipt({ created_node_ids: ["node-created"] }),
      }],
    });
    const oldUpdate = {
      unit_type: "item" as const,
      key: "receipt:old-update",
      sequence: 20,
      item: {
        item_type: "action_receipt" as const,
        sequence: 20,
        created_at: "2026-08-27T00:00:02Z",
        action_receipt: receipt({
          receipt_id: "old-update",
          created_node_ids: [],
          updated_node_ids: ["node-updated"],
        }),
      },
    };
    const latestUpdate = {
      unit_type: "item" as const,
      key: "receipt:latest-update",
      sequence: 21,
      item: {
        item_type: "action_receipt" as const,
        sequence: 21,
        created_at: "2026-08-27T00:00:03Z",
        action_receipt: receipt({
          receipt_id: "latest-update",
          created_node_ids: [],
          updated_node_ids: ["node-updated"],
        }),
      },
    };
    const index = buildConversationCanvasLinkIndex([
      createThread,
      oldUpdate,
      latestUpdate,
      item(linkedMessage),
      item(artifact),
    ], null);

    expect(conversationLocationForNode(index, "node-created")?.key).toBe(createThread.key);
    expect(conversationLocationForNode(index, "node-updated")?.key).toBe("receipt:latest-update");
    expect(conversationLocationForNode(index, "node-message")?.key).toBe("message:message-1");
    expect(conversationLocationForNode(index, "node-artifact")?.key).toBe("artifact:artifact-1");
  });

  it("indexes guidance nodes for forward navigation without inventing a reverse conversation source", () => {
    const awaiting = {
      awaiting_id: "awaiting-1",
      workflow_id: "workflow-1",
      session_id: "session-1",
      checkpoint_id: "checkpoint-1",
      kind: "manual_node_run",
      requires_user_action: true,
      resume_policy: "node_terminal",
      interaction_id: null,
      node_ids: ["node-waiting"],
      stage: "videos",
      stage_revision: 8,
      created_at: "2026-08-27T00:00:00Z",
    } satisfies GuidanceAwaitingV1;

    const index = buildConversationCanvasLinkIndex([], awaiting);

    expect(index.locations.get("guidance:awaiting-1")?.navigableNodeIds).toEqual(["node-waiting"]);
    expect(conversationLocationForNode(index, "node-waiting")).toBeNull();
  });
});
