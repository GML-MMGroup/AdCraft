import { describe, expect, it } from "vitest";

import type {
  AgentActionReceiptV2,
  AgentCapabilityIdV2,
  ChatCapabilityActivityV2,
  ChatMessageV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
} from "../../../types-v2.ts";
import { buildStageThreadTimeline } from "./stageThreadProjection.ts";

function activity(
  capabilityId: AgentCapabilityIdV2,
  sequence: number,
  status: ChatCapabilityActivityV2["status"] = "completed",
  activityId = `${capabilityId}-${sequence}`,
): ChatCapabilityActivityV2 {
  return {
    item_type: "expert_activity",
    activity_id: activityId,
    turn_id: `turn-${activityId}`,
    capability_id: capabilityId,
    capability_display_name: capabilityId === "script_authoring" ? "Script Writer" : "World Setting Designer",
    status,
    sequence,
    started_at: "2026-08-27T00:00:00Z",
    finished_at: status === "working" ? null : "2026-08-27T00:00:10Z",
    message: status === "failed" ? "The operation failed." : null,
    error_code: status === "failed" ? "provider_failed" : null,
    elapsed_ms: status === "working" ? null : 10_000,
    attempt_stage: "initial",
    retryable: status === "failed",
    validation_paths: [],
    suggested_actions: status === "failed" ? ["retry"] : [],
    completion_mode: null,
    warning_code: null,
  };
}

function planning(sequence: number): ChatMessageV2 {
  return {
    item_type: "message",
    message_kind: "planning_progress",
    message_id: `planning-${sequence}`,
    conversation_id: "conversation-1",
    speaker: "adcraft_video_agent",
    text: "Preparing editable Draft.",
    linked_node_ids: [],
    script_node_id: null,
    proposal_id: "proposal-world",
    capability_id: "world_setting",
    sequence,
    created_at: "2026-08-27T00:00:01Z",
  };
}

function proposal(sequence: number): ChatProposalCardV2 {
  return {
    item_type: "proposal",
    sequence,
    created_at: "2026-08-27T00:00:02Z",
    proposal: {
      proposal_id: "proposal-world",
      workflow_id: "workflow-1",
      turn_id: "turn-world",
      video_skill_run_id: null,
      topic_id: "topic-world",
      creative_direction_snapshot_id: null,
      proposal_revision: 1,
      source_proposal_id: null,
      proposal_kind: "world_setting",
      capability_id: "world_setting",
      capability_display_name: "World Setting Designer",
      options: [
        { option_id: "option-a", title: "Quiet Gallery", public_summary: "A restrained gallery world.", key_decisions: [] },
        { option_id: "option-b", title: "Silk Pavilion", public_summary: "A flowing silk interior.", key_decisions: [] },
      ],
      proposed_references: [],
      target_node_id: null,
      target_node_revision: null,
      proposal_purpose: null,
      availability: "applied",
      application_count: 1,
      latest_application: {
        application_id: "application-world",
        option_id: "option-b",
        action: "select_option",
        receipt_id: "receipt-world",
        created_node_ids: ["node-world"],
        queued_execution_ids: [],
        created_at: "2026-08-27T00:00:03Z",
      },
      materialization: null,
      guidance_session_id: "session-1",
      guidance_session_revision: 2,
      actions: [],
      created_at: "2026-08-27T00:00:02Z",
      updated_at: "2026-08-27T00:00:03Z",
    },
  };
}

function receipt(status: AgentActionReceiptV2["status"] = "applied") {
  return {
    item_type: "action_receipt" as const,
    sequence: 4,
    created_at: "2026-08-27T00:00:03Z",
    action_receipt: {
      receipt_id: "receipt-world",
      workflow_id: "workflow-1",
      plan_id: null,
      action_id: "action-world",
      proposal_id: "proposal-world",
      proposal_option_id: "option-b",
      proposal_action: "select_option" as const,
      actor_kind: "user" as const,
      idempotency_key: "key-world",
      status,
      summary: status === "applied" ? "Draft saved to canvas." : "Draft could not be saved.",
      created_node_ids: status === "applied" ? ["node-world"] : [],
      updated_node_ids: [],
      deleted_node_ids: [],
      created_binding_ids: [],
      deleted_binding_ids: [],
      queued_execution_ids: [],
      run_queue_errors: [],
      operation_results: [],
      workflow_revision: 3,
      before_workflow_revision: 2,
      placement_hints: [],
      continuation_turn_id: null,
      superseded_by: null,
      error_code: status === "failed" ? "materialization_failed" : null,
      error_message: status === "failed" ? "Draft could not be saved." : null,
      created_at: "2026-08-27T00:00:03Z",
    },
  };
}

describe("buildStageThreadTimeline", () => {
  it("groups typed planning, activity, proposal, and receipt records into one thread", () => {
    const units = buildStageThreadTimeline([
      planning(2),
      activity("world_setting", 1),
      proposal(3),
      receipt(),
    ]);

    expect(units).toHaveLength(1);
    expect(units[0]).toMatchObject({
      unit_type: "stage_thread",
      capability_id: "world_setting",
      status: "completed",
      planning: [{ message_id: "planning-2" }],
      activities: [{ activity_id: "world_setting-1" }],
      proposals: [{ proposal: { proposal_id: "proposal-world" } }],
      receipts: [{ action_receipt: { receipt_id: "receipt-world" } }],
    });
  });

  it("projects the applied proposal option as the completed thread result", () => {
    const [unit] = buildStageThreadTimeline([activity("world_setting", 1), proposal(2)]);

    expect(unit).toMatchObject({
      unit_type: "stage_thread",
      selected_option: {
        option_id: "option-b",
        title: "Silk Pavilion",
      },
    });
  });

  it("aggregates repeated Script Writer executions into one revision count", () => {
    const units = buildStageThreadTimeline([
      activity("script_authoring", 10, "completed", "script-1"),
      activity("script_authoring", 20, "completed", "script-2"),
      activity("script_authoring", 30, "completed", "script-3"),
    ]);

    expect(units).toHaveLength(1);
    expect(units[0]).toMatchObject({
      unit_type: "stage_thread",
      capability_id: "script_authoring",
      completed_activity_count: 3,
    });
  });

  it("keeps only the highest revision of each document", () => {
    const units = buildStageThreadTimeline([
      {
        item_type: "agent_document",
        document_id: "document-1",
        document_kind: "anchor_registry",
        revision: 1,
        content_digest: "digest-1",
        title: "Anchor Registry",
        sequence: 8,
        created_at: "2026-08-27T00:00:08Z",
      },
      {
        item_type: "agent_document",
        document_id: "document-1",
        document_kind: "anchor_registry",
        revision: 3,
        content_digest: "digest-3",
        title: "Anchor Registry",
        sequence: 18,
        created_at: "2026-08-27T00:00:18Z",
      },
    ]);

    expect(units).toHaveLength(1);
    expect(units[0]).toMatchObject({
      unit_type: "item",
      item: { item_type: "agent_document", revision: 3 },
    });
  });

  it("retains failed receipts inside the owning thread", () => {
    const units = buildStageThreadTimeline([
      activity("world_setting", 1),
      proposal(2),
      receipt("failed"),
    ] as ChatTimelineItemV2[]);

    expect(units[0]).toMatchObject({
      unit_type: "stage_thread",
      status: "failed",
      receipts: [{ action_receipt: { status: "failed", error_code: "materialization_failed" } }],
    });
  });

  it("does not let an older failed attempt override a newer completed activity", () => {
    const units = buildStageThreadTimeline([
      activity("script_authoring", 10, "failed", "script-failed"),
      activity("script_authoring", 20, "completed", "script-recovered"),
    ]);

    expect(units[0]).toMatchObject({
      unit_type: "stage_thread",
      status: "completed",
      completed_activity_count: 1,
    });
  });

  it("keeps proposal receipts standalone unless the applied proposal references them", () => {
    const supersededProposal = proposal(2);
    supersededProposal.proposal.availability = "superseded";
    supersededProposal.proposal.latest_application = null;
    const deferredReceipt = receipt();
    deferredReceipt.action_receipt.receipt_id = "receipt-deferred";
    deferredReceipt.action_receipt.proposal_action = "defer_topic";

    const units = buildStageThreadTimeline([
      activity("world_setting", 1, "superseded"),
      supersededProposal,
      deferredReceipt,
    ]);

    expect(units).toHaveLength(2);
    expect(units.find((unit) => unit.unit_type === "stage_thread")).toMatchObject({
      status: "superseded",
      receipts: [],
    });
    expect(units.find((unit) => unit.unit_type === "item")).toMatchObject({
      item: { item_type: "action_receipt", action_receipt: { receipt_id: "receipt-deferred" } },
    });
  });

  it("keeps only the latest unassociated planning status while the Agent is working", () => {
    const first = planning(2);
    first.message_id = "planning-unassociated-1";
    first.capability_id = null;
    first.proposal_id = null;
    const latest = planning(8);
    latest.message_id = "planning-unassociated-2";
    latest.capability_id = null;
    latest.proposal_id = null;

    const units = buildStageThreadTimeline([first, latest], {
      showUnassociatedPlanning: true,
    });

    expect(units).toHaveLength(1);
    expect(units[0]).toMatchObject({
      unit_type: "item",
      item: { item_type: "message", message_id: "planning-unassociated-2" },
    });
  });
});
