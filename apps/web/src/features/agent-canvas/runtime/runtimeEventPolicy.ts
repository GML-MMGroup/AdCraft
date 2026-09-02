import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";
import { isTerminalRuntimeEvent } from "./runtimeRefreshIdentity.ts";

export type AgentCanvasRuntimeRefreshPolicy = {
  refreshRuntime: boolean;
  refreshWorkflow: boolean;
  refreshAssets: boolean;
  refreshChat: boolean;
  refreshSettings: boolean;
  refreshDocuments: boolean;
  refreshDocumentId: string | null;
  refreshNodeId: string | null;
  refreshEditingNodeId: string | null;
};

const RUNTIME_EVENTS = new Set([
  "execution_queued",
  "execution_started",
  "execution_waiting",
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "execution_cancelled",
  "node_queued",
  "node_generation_started",
  "node_generation_waiting",
  "node_ready",
  "node_failed",
  "node_blocked",
  "node_skipped",
  "node_cancelled",
  "provider_task_submitted",
  "provider_task_waiting",
  "provider_task_polled",
  "provider_task_completed",
  "provider_task_failed",
  "provider_result_download_waiting",
  "provider_result_download_completed",
  "provider_result_download_failed",
  "provider_inputs_resolved",
  "node_output_published",
  "runtime_snapshot_updated",
  "execution_member_skipped_dependency",
]);

const AUTHORING_EVENTS = new Set([
  "project_created",
  "project_updated",
  "project_trashed",
  "project_restored",
  "node_created",
  "node_updated",
  "node_deleted",
  "binding_created",
  "binding_updated",
  "binding_deleted",
  "layout_updated",
  "asset_saved_to_library",
  "asset_deleted",
  "workflow_projection_updated",
  "proposal_action_applied",
  "draft_node_created",
  "node_prompt_preparation_started",
  "node_prompt_preparation_completed",
  "node_prompt_preparation_failed",
  "node_prompt_preparation_queued",
  "node_prompt_preparation_ready",
  "node_prompt_preparation_superseded",
  "storyboard_sequence_materialized",
  "guided_action_applied",
  "command_plan_committed",
  "action_receipt_created",
  "proposal_materialization_completed",
  "guided_draft_materialized",
  "storyboard_fanout_committed",
  "guided_editing_ready",
  "post_ready_effect_completed",
  "guided_media_resume_completed",
  "guided_media_resume_failed",
  "storyboard_sequence_outline_planned",
  "storyboard_segment_materialized",
  "guided_editing_updated",
  "guided_completion_failed",
  "guided_product_source_materialized",
  "guided_product_source_failed",
  "editing_export_imported_to_canvas",
]);

const CHAT_EVENTS = new Set([
  "chat_message_created",
  "agent_turn_queued",
  "agent_turn_waiting",
  "agent_turn_started",
  "agent_turn_completed",
  "agent_turn_failed",
  "agent_turn_interrupted",
  "chat_turn_retry_accepted",
  "agent_operation_queued",
  "agent_operation_started",
  "agent_operation_waiting",
  "agent_operation_retrying",
  "agent_operation_validating",
  "agent_operation_publishing",
  "agent_operation_completed",
  "agent_operation_failed",
  "continuation_queued",
  "continuation_started",
  "continuation_retry_scheduled",
  "continuation_completed",
  "continuation_failed",
  "continuation_superseded",
  "proposal_created",
  "decision_bundle_ready",
  "proposal_ready",
  "proposal_action_applied",
  "proposal_materialization_queued",
  "proposal_materialization_started",
  "proposal_materialization_completed",
  "proposal_materialization_failed",
  "guided_interaction_opened",
  "guided_interaction_submitted",
  "guided_interaction_closed",
  "guided_interaction_superseded",
  "guided_continuation_queued",
  "guidance_awaiting_entered",
  "guidance_awaiting_resumed",
  "guidance_orphan_recovered",
  "guided_media_review_required",
  "guided_media_confirmed",
  "guided_closure_blocked",
  "guided_production_completed",
  "guidance_state_updated",
  "journey_stage_started",
  "journey_stage_changed",
  "journey_stage_waiting_user",
  "journey_stage_failed",
  "journey_stage_recovered",
  "draft_node_created",
  "guided_action_created",
  "guided_action_applied",
  "guided_action_superseded",
  "guidance_advance_accepted",
  "command_plan_created",
  "command_plan_committed",
  "command_plan_rejected",
  "action_receipt_created",
  "post_ready_effect_started",
  "post_ready_effect_completed",
  "post_ready_effect_failed",
  "post_ready_effect_retry_scheduled",
  "guided_media_resume_queued",
  "guided_media_resume_completed",
  "guided_media_resume_failed",
  "storyboard_sequence_outline_planned",
  "storyboard_segment_materialized",
  "guided_editing_updated",
  "guided_completion_failed",
  "guided_product_source_pending",
  "guided_product_source_materialized",
  "guided_product_source_failed",
]);

const NODE_DETAIL_EVENTS = new Set([
  "node_generation_started",
  "node_output_published",
  "node_ready",
  "node_failed",
  "node_blocked",
  "node_skipped",
  "node_cancelled",
  "node_prompt_preparation_started",
  "node_prompt_preparation_completed",
  "node_prompt_preparation_failed",
  "node_prompt_preparation_queued",
  "node_prompt_preparation_ready",
  "node_prompt_preparation_superseded",
  "storyboard_sequence_materialized",
]);

const GUIDED_CANONICAL_REFRESH_EVENTS = new Set([
  "guided_draft_materialized",
  "guided_binding_materialized",
  "storyboard_sequence_planned",
  "editing_prepared",
  "agent_settings_updated",
  "agent_auto_run_requested",
  "agent_auto_run_submitted",
  "agent_auto_run_failed",
  "guided_interaction_opened",
  "guided_interaction_submitted",
  "guided_interaction_closed",
  "guided_interaction_superseded",
  "guided_continuation_queued",
  "guidance_awaiting_entered",
  "guidance_awaiting_resumed",
  "guidance_orphan_recovered",
  "guided_media_review_required",
  "guided_media_confirmed",
  "guided_closure_blocked",
  "guided_editing_ready",
  "guided_production_completed",
  "guided_media_resume_completed",
  "guided_media_resume_failed",
  "storyboard_sequence_outline_planned",
  "storyboard_segment_materialized",
  "guided_editing_updated",
  "guided_completion_failed",
  "guided_product_source_materialized",
  "guided_product_source_failed",
]);

const GUIDED_CHAT_EVENTS = new Set([
  "expert_activity_started",
  "expert_activity_completed",
  "expert_activity_failed",
  "guided_draft_materialized",
  "guided_binding_materialized",
  "storyboard_sequence_planned",
  "editing_prepared",
  "guided_editing_ready",
  "storyboard_fanout_committed",
  "execution_member_skipped_dependency",
  "guided_media_resume_queued",
  "guided_media_resume_completed",
  "guided_media_resume_failed",
  "storyboard_sequence_outline_planned",
  "storyboard_segment_materialized",
  "guided_editing_updated",
  "guided_completion_failed",
]);

const DOCUMENT_EVENTS = new Set([
  "agent_document_created",
  "agent_document_updated",
  "agent_document_revision_created",
  "anchor_registered",
  "agent_working_document_created",
  "agent_working_document_updated",
  "agent_anchor_planned",
  "agent_anchor_activated",
  "agent_anchor_retired",
  "storyboard_plan_revised",
  "storyboard_visual_anchor_frozen",
  "post_ready_effect_completed",
  "storyboard_sequence_outline_planned",
  "storyboard_segment_materialized",
]);

export function runtimeEventPolicy(
  event: CanvasRuntimeEventV2,
): AgentCanvasRuntimeRefreshPolicy {
  const type = event.event_type;
  const editingImported = type === "editing_export_imported_to_canvas";
  const editing = type.startsWith("editing_export_") && !editingImported;
  const productSource = type.startsWith("guided_product_source_");
  const productSourcePending = type === "guided_product_source_pending";
  const editingPrepared = type === "editing_prepared" || type === "guided_editing_ready";
  const projectAssetPublished = type === "project_asset_published";
  const publishesOutput = type === "node_output_published";
  const guidedCanonicalRefresh = GUIDED_CANONICAL_REFRESH_EVENTS.has(type);
  const terminalNode = type.startsWith("node_")
    && isTerminalRuntimeEvent(type)
    && Boolean(event.node_id);
  const documentEvent = DOCUMENT_EVENTS.has(type);
  const documentId = documentEvent
    ? typeof event.payload?.document_id === "string"
      ? event.payload.document_id
      : typeof event.payload?.plan_document_id === "string"
        ? event.payload.plan_document_id
        : null
    : null;

  return {
    refreshRuntime: projectAssetPublished || productSource || editingImported || RUNTIME_EVENTS.has(type) || guidedCanonicalRefresh,
    refreshWorkflow: terminalNode || editing || editingImported || (!productSourcePending && productSource) || AUTHORING_EVENTS.has(type) || guidedCanonicalRefresh,
    refreshAssets: projectAssetPublished || publishesOutput || productSource || editingImported,
    refreshChat: CHAT_EVENTS.has(type) || GUIDED_CHAT_EVENTS.has(type) || documentEvent,
    refreshSettings: type === "agent_settings_updated",
    refreshDocuments: documentEvent,
    refreshDocumentId: documentId,
    refreshNodeId: NODE_DETAIL_EVENTS.has(type) || editingImported ? event.node_id : null,
    refreshEditingNodeId: editing || editingPrepared ? event.node_id : null,
  };
}
