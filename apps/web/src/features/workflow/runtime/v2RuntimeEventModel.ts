import type { WorkflowRuntimeEventV2 } from "../../../types-v2.ts";

const V2_SLOT_OPERATION_REFRESH_EVENTS = new Set([
  "slot_working_version_updated",
  "slot_selected_version_updated",
  "slot_versions_updated",
  "reference_attached",
  "reference_removed",
  "asset_version_created",
  "provider_task_waiting",
  "provider_task_completed",
  "provider_task_failed",
  "chat_action_applied",
]);

const V2_RUNTIME_REFRESH_EVENT_TYPES = new Set([
  "workflow_run_started",
  "runtime_snapshot_updated",
  "node_status_changed",
  "slot_status_changed",
  "execution_started",
  "execution_waiting",
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "execution_cancelled",
  "slot_generation_started",
  "slot_generation_waiting",
  "slot_generation_completed",
  "slot_generation_failed",
  "provider_execution_started",
  "provider_execution_waiting",
  "provider_execution_completed",
  "provider_execution_failed",
  ...V2_SLOT_OPERATION_REFRESH_EVENTS,
]);

export const V2_WORKFLOW_REFRESH_EVENT_TYPES = new Set([
  "workflow_run_started",
  "workflow_updated",
  "graph_updated",
  "asset_created",
  "node_status_changed",
  "node_assets_updated",
  "slot_status_changed",
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "slot_generation_started",
  "slot_generation_waiting",
  "slot_generation_completed",
  "slot_generation_failed",
  "provider_execution_started",
  "provider_execution_waiting",
  "provider_execution_completed",
  "provider_execution_failed",
  "provider_task_submitted",
  "provider_task_waiting",
  "provider_task_completed",
  "provider_task_failed",
  "asset_version_created",
  "slot_working_version_created",
  "slot_working_version_updated",
  "slot_working_version_discarded",
  "slot_selected_version_updated",
  "slot_versions_updated",
  "item_working_version_updated",
  "item_selected_version_updated",
  "slot_history_updated",
  "asset_history_updated",
  "slot_prompt_updated",
  "reference_attached",
  "reference_removed",
  "asset_owner_resolved",
  "slot_outdated_hint_added",
  "item_outdated_hint_added",
  "node_outdated_hint_added",
  "slot_outdated_hint_cleared",
  "storyboard_summary_refined",
  "chat_action_applied",
]);

const V2_ASSET_REFRESH_EVENT_TYPES = new Set([
  "asset_version_created",
  "asset_created",
  "node_assets_updated",
  "slot_generation_completed",
  "slot_working_version_created",
  "slot_working_version_updated",
  "slot_selected_version_updated",
  "slot_versions_updated",
  "slot_history_updated",
  "asset_history_updated",
  "runtime_snapshot_updated",
  "provider_execution_completed",
  "provider_task_waiting",
  "provider_task_completed",
  "provider_task_failed",
  "reference_attached",
  "reference_removed",
  "chat_action_applied",
  "item_working_version_updated",
  "item_selected_version_updated",
]);

export const V2_SLOT_VERSION_REFRESH_EVENT_TYPES = new Set([
  "asset_version_created",
  "slot_working_version_created",
  "slot_working_version_updated",
  "slot_working_version_discarded",
  "slot_selected_version_updated",
  "slot_versions_updated",
  "slot_history_updated",
  "asset_history_updated",
  "node_assets_updated",
  "reference_attached",
  "reference_removed",
  "provider_task_waiting",
  "provider_task_completed",
  "provider_task_failed",
  "chat_action_applied",
]);

const V2_PROVIDER_TASK_REFRESH_EVENT_TYPES = new Set([
  "provider_task_submitted",
  "provider_task_waiting",
  "provider_task_completed",
  "provider_task_failed",
]);

export function v2EventRefreshHints(event: WorkflowRuntimeEventV2): string[] {
  const refresh = event.payload?.refresh;
  return Array.isArray(refresh) ? refresh.filter((item): item is string => typeof item === "string") : [];
}

export function v2EventShouldRefreshRuntime(event: WorkflowRuntimeEventV2) {
  return V2_RUNTIME_REFRESH_EVENT_TYPES.has(event.event_type) ||
    v2EventRefreshHints(event).some((hint) => hint === "runtime" || hint === "workflow" || hint === "slot_versions" || hint === "assets");
}

export function v2EventShouldRefreshAssets(event: WorkflowRuntimeEventV2) {
  return V2_ASSET_REFRESH_EVENT_TYPES.has(event.event_type) ||
    v2EventRefreshHints(event).some((hint) => hint === "assets" || hint === "slot_versions" || hint === "workflow");
}

export function v2EventShouldRefreshProviderTasks(event: WorkflowRuntimeEventV2) {
  return V2_PROVIDER_TASK_REFRESH_EVENT_TYPES.has(event.event_type) ||
    event.event_type.startsWith("provider_task_") ||
    Boolean(v2RuntimeEventProviderTaskId(event));
}

export function v2RuntimeEventSlotId(event: WorkflowRuntimeEventV2) {
  return event.slot_id ?? stringFromUnknown(event.payload?.slot_id) ?? stringFromUnknown(event.payload?.target_slot_id) ?? null;
}

export function v2RuntimeEventProviderTaskId(event: WorkflowRuntimeEventV2) {
  return stringFromUnknown(event.payload?.provider_task_id) ?? stringFromUnknown(event.payload?.task_id) ?? stringFromUnknown(event.payload?.remote_task_id) ?? null;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}
