import type { CanvasRuntimeEventV2 } from "../../../types-v2.ts";

export type AgentCanvasRuntimeRefreshPolicy = {
  refreshRuntime: boolean;
  refreshWorkflow: boolean;
  refreshAssets: boolean;
  refreshChat: boolean;
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
  "guided_action_applied",
  "command_plan_committed",
  "action_receipt_created",
  "creative_proposal_resolved",
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
  "specialist_activity_started",
  "specialist_activity_completed",
  "specialist_activity_failed",
  "creative_proposal_created",
  "creative_proposal_resolved",
  "guided_action_created",
  "guided_action_applied",
  "command_plan_created",
  "command_plan_committed",
  "command_plan_rejected",
  "action_receipt_created",
  "creative_topic_updated",
  "creative_direction_updated",
  "creation_mode_resolved",
  "production_recipe_created",
  "production_recipe_revised",
  "planning_topic_updated",
]);

const NODE_DETAIL_EVENTS = new Set([
  "node_output_published",
  "node_ready",
  "node_failed",
  "node_blocked",
  "node_skipped",
  "node_cancelled",
]);

export function runtimeEventPolicy(
  event: CanvasRuntimeEventV2,
): AgentCanvasRuntimeRefreshPolicy {
  const type = event.event_type;
  const editing = type.startsWith("editing_export_");
  const projectAssetPublished = type === "project_asset_published";
  const publishesOutput = type === "node_output_published";

  return {
    refreshRuntime: projectAssetPublished || RUNTIME_EVENTS.has(type),
    refreshWorkflow: editing || AUTHORING_EVENTS.has(type),
    refreshAssets: projectAssetPublished || publishesOutput,
    refreshChat: CHAT_EVENTS.has(type),
    refreshNodeId: NODE_DETAIL_EVENTS.has(type) ? event.node_id : null,
    refreshEditingNodeId: editing ? event.node_id : null,
  };
}
