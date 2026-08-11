import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";

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
  "provider_inputs_resolved",
  "node_output_published",
  "runtime_snapshot_updated",
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
  "storyboard_sequence_materialized",
  "guided_action_applied",
  "command_plan_committed",
  "action_receipt_created",
  "proposal_materialization_completed",
]);

const CHAT_EVENTS = new Set([
  "chat_message_created",
  "agent_turn_queued",
  "agent_turn_started",
  "agent_turn_completed",
  "agent_turn_failed",
  "agent_turn_interrupted",
  "continuation_queued",
  "continuation_started",
  "continuation_retry_scheduled",
  "continuation_completed",
  "continuation_failed",
  "proposal_created",
  "decision_bundle_ready",
  "proposal_ready",
  "proposal_action_applied",
  "proposal_materialization_queued",
  "proposal_materialization_started",
  "proposal_materialization_completed",
  "proposal_materialization_failed",
  "guidance_state_updated",
  "journey_stage_started",
  "journey_stage_changed",
  "journey_stage_waiting_user",
  "journey_stage_failed",
  "draft_node_created",
  "guided_action_created",
  "guided_action_applied",
  "command_plan_created",
  "command_plan_committed",
  "command_plan_rejected",
  "action_receipt_created",
]);

const NODE_DETAIL_EVENTS = new Set([
  "node_output_published",
  "node_ready",
  "node_failed",
  "node_blocked",
  "node_skipped",
  "node_cancelled",
  "node_prompt_preparation_started",
  "node_prompt_preparation_completed",
  "node_prompt_preparation_failed",
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
]);

const GUIDED_CHAT_EVENTS = new Set([
  "expert_activity_started",
  "expert_activity_completed",
  "expert_activity_failed",
  "guided_draft_materialized",
  "guided_binding_materialized",
  "storyboard_sequence_planned",
  "editing_prepared",
]);

const DOCUMENT_EVENTS = new Set([
  "agent_document_created",
  "agent_document_updated",
  "agent_document_revision_created",
  "anchor_registered",
]);

export function runtimeEventPolicy(
  event: CanvasRuntimeEventV2,
): AgentCanvasRuntimeRefreshPolicy {
  const type = event.event_type;
  const editing = type.startsWith("editing_export_");
  const editingPrepared = type === "editing_prepared";
  const projectAssetPublished = type === "project_asset_published";
  const publishesOutput = type === "node_output_published";
  const guidedCanonicalRefresh = GUIDED_CANONICAL_REFRESH_EVENTS.has(type);
  const documentEvent = DOCUMENT_EVENTS.has(type);
  const documentId = documentEvent && typeof event.payload?.document_id === "string"
    ? event.payload.document_id
    : null;

  return {
    refreshRuntime: projectAssetPublished || RUNTIME_EVENTS.has(type) || guidedCanonicalRefresh,
    refreshWorkflow: editing || AUTHORING_EVENTS.has(type) || guidedCanonicalRefresh,
    refreshAssets: projectAssetPublished || publishesOutput,
    refreshChat: CHAT_EVENTS.has(type) || GUIDED_CHAT_EVENTS.has(type) || documentEvent,
    refreshSettings: type === "agent_settings_updated",
    refreshDocuments: documentEvent,
    refreshDocumentId: documentId,
    refreshNodeId: NODE_DETAIL_EVENTS.has(type) ? event.node_id : null,
    refreshEditingNodeId: editing || editingPrepared ? event.node_id : null,
  };
}
