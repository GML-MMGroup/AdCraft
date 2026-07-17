import type {
  V2LinkedContextSummary,
  V2ScriptStructuralDiff,
  WorkflowRuntimeEventV2,
} from "../../../types-v2.ts";
import { isV2SynchronizationEvent } from "../../../workflow-v2/runtime.ts";

export type V2SynchronizationRefreshPlan = {
  isSynchronizationBatch: boolean;
  refreshScreenplayHistory: boolean;
  refreshSelectedScreenplay: boolean;
  refreshWorkflow: boolean;
  refreshWorkflowStructure: boolean;
  refreshSlotPrompts: boolean;
  refreshReferences: boolean;
  refreshAssets: boolean;
  nodeIds: string[];
  itemIds: string[];
  slotIds: string[];
  transactionIds: string[];
  scriptVersionIds: string[];
};

export const V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES = new Set([
  "final_composition_render_queued",
  "final_composition_render_started",
  "final_composition_render_progress",
  "final_composition_render_completed",
  "final_composition_render_failed",
  "final_composition_render_cancelled",
]);

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
  "storyboard_summary_refined",
  "chat_action_applied",
  "final_timeline_created",
  "final_timeline_updated",
  "final_composition_render_completed",
  "final_composition_render_failed",
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
  "final_composition_render_completed",
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

export function createV2SynchronizationRefreshPlan(events: WorkflowRuntimeEventV2[]): V2SynchronizationRefreshPlan {
  const plan: V2SynchronizationRefreshPlan = {
    isSynchronizationBatch: false,
    refreshScreenplayHistory: false,
    refreshSelectedScreenplay: false,
    refreshWorkflow: false,
    refreshWorkflowStructure: false,
    refreshSlotPrompts: false,
    refreshReferences: false,
    refreshAssets: false,
    nodeIds: [],
    itemIds: [],
    slotIds: [],
    transactionIds: [],
    scriptVersionIds: [],
  };
  const nodeIds = new Set<string>();
  const itemIds = new Set<string>();
  const slotIds = new Set<string>();
  const transactionIds = new Set<string>();
  const scriptVersionIds = new Set<string>();

  for (const event of events) {
    if (!isV2SynchronizationEvent(event.event_type)) continue;
    plan.isSynchronizationBatch = true;
    const refresh = v2EventRefreshHints(event);

    if (event.event_type === "script_version_created") {
      plan.refreshScreenplayHistory = true;
    } else if (event.event_type === "script_selected_version_updated") {
      plan.refreshScreenplayHistory = true;
      plan.refreshSelectedScreenplay = true;
      plan.refreshWorkflow = true;
    } else if (event.event_type === "workflow_structure_updated") {
      plan.refreshWorkflow = true;
      plan.refreshWorkflowStructure = true;
    } else if (event.event_type === "linked_context_updated") {
      plan.refreshWorkflow ||= refresh.includes("workflow");
      plan.refreshSlotPrompts ||= refresh.includes("slot_prompts");
      plan.refreshReferences ||= refresh.includes("references");
      plan.refreshAssets ||= refresh.includes("assets");
      if (refresh.includes("script")) {
        plan.refreshScreenplayHistory = true;
        plan.refreshSelectedScreenplay = true;
      }
    }

    addStrings(nodeIds, event.payload?.node_ids);
    addStrings(itemIds, event.payload?.item_ids);
    addStrings(slotIds, event.payload?.slot_ids);
    if (event.node_id) nodeIds.add(event.node_id);
    if (event.item_id) itemIds.add(event.item_id);
    if (event.slot_id) slotIds.add(event.slot_id);
    const transactionId = stringFromUnknown(event.payload?.transaction_id);
    if (transactionId) transactionIds.add(transactionId);
    const scriptVersionId = stringFromUnknown(event.payload?.script_version_id) || stringFromUnknown(event.version_id);
    if (scriptVersionId) scriptVersionIds.add(scriptVersionId);
  }

  plan.nodeIds = Array.from(nodeIds);
  plan.itemIds = Array.from(itemIds);
  plan.slotIds = Array.from(slotIds);
  plan.transactionIds = Array.from(transactionIds);
  plan.scriptVersionIds = Array.from(scriptVersionIds);
  return plan;
}

export function createV2LocalSynchronizationRefreshPlan(
  scriptVersionId: string,
  structuralDiff: V2ScriptStructuralDiff,
  linkedContext: V2LinkedContextSummary,
): V2SynchronizationRefreshPlan {
  const refresh = new Set(linkedContext.refresh ?? []);
  return {
    isSynchronizationBatch: true,
    refreshScreenplayHistory: true,
    refreshSelectedScreenplay: true,
    refreshWorkflow: true,
    refreshWorkflowStructure: v2StructuralDiffChangesWorkflow(structuralDiff),
    refreshSlotPrompts: refresh.has("slot_prompts"),
    refreshReferences: refresh.has("references"),
    refreshAssets: refresh.has("assets"),
    nodeIds: uniqueStrings(linkedContext.updated_node_ids),
    itemIds: uniqueStrings(linkedContext.updated_item_ids),
    slotIds: uniqueStrings(linkedContext.updated_slot_ids),
    transactionIds: [],
    scriptVersionIds: scriptVersionId ? [scriptVersionId] : [],
  };
}

export function v2EventShouldRefreshRuntime(event: WorkflowRuntimeEventV2) {
  if (isV2SynchronizationEvent(event.event_type)) return false;
  return V2_RUNTIME_REFRESH_EVENT_TYPES.has(event.event_type) ||
    v2EventRefreshHints(event).some((hint) => hint === "runtime" || hint === "workflow" || hint === "slot_versions" || hint === "assets");
}

export function v2EventShouldRefreshAssets(event: WorkflowRuntimeEventV2) {
  if (isV2SynchronizationEvent(event.event_type)) return false;
  return V2_ASSET_REFRESH_EVENT_TYPES.has(event.event_type) ||
    v2EventRefreshHints(event).some((hint) => hint === "assets" || hint === "slot_versions" || hint === "workflow");
}

export function v2EventShouldRefreshProviderTasks(event: WorkflowRuntimeEventV2) {
  if (isV2SynchronizationEvent(event.event_type)) return false;
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

function addStrings(target: Set<string>, value: unknown) {
  if (!Array.isArray(value)) return;
  value.forEach((item) => {
    const normalized = stringFromUnknown(item);
    if (normalized) target.add(normalized);
  });
}

function uniqueStrings(value: unknown): string[] {
  const result = new Set<string>();
  addStrings(result, value);
  return Array.from(result);
}

function v2StructuralDiffChangesWorkflow(diff: V2ScriptStructuralDiff): boolean {
  if (diff.order_changed) return true;
  return Object.entries(diff).some(([key, value]) =>
    /^(added|archived|reactivated)_(character|location|scene|shot)_ids$/.test(key) && Array.isArray(value) && value.length > 0,
  );
}
