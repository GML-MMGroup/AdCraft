import type { WorkflowRuntimeEventV2 } from "../../../types-v2.ts";
import {
  isCanvasRuntimeAssetLibraryEvent,
  isCanvasRuntimeCandidateEvent,
  isCanvasRuntimeTimelineEvent,
  type CanvasRuntimeEvent,
} from "../../../workflow/canvasRuntime.ts";
import { isChatCanvasActionRuntimeEvent, isChatCanvasPromptRuntimeEvent, isChatCanvasRevisionRuntimeEvent } from "../../../workflow/chatCanvasActions.ts";
import { shouldReloadFinalCompositionTimeline } from "../final-composition/finalCompositionEvents.ts";
import { createV2AuthoringRuntimeEventPolicy } from "./v2AuthoringRuntimeEventPolicy.ts";
import {
  createV2SynchronizationRefreshPlan,
  V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES,
  V2_SLOT_VERSION_REFRESH_EVENT_TYPES,
  v2EventRefreshHints,
  v2EventShouldRefreshAssets,
  v2EventShouldRefreshProviderTasks,
  v2EventShouldRefreshRuntime,
  v2RuntimeEventSlotId,
  type V2SynchronizationRefreshPlan,
} from "./v2RuntimeEventModel.ts";

export type CanvasRuntimeEventEffect =
  | { kind: "node_status" }
  | { kind: "node_refresh" }
  | { kind: "media_status" }
  | { kind: "graph_refresh" }
  | { kind: "resolved_inputs_refresh" }
  | { kind: "conversation_action" }
  | { kind: "conversation_prompt" }
  | { kind: "conversation_revision" }
  | { kind: "asset_library" }
  | { kind: "candidate" }
  | { kind: "final_composition" }
  | { kind: "execution_terminal" }
  | { kind: "snapshot" }
  | { kind: "none" };

export type V2ExecutionEffect = {
  executionId: string | null;
  pollingState: "polling" | "completed" | "failed";
  workflowRunning: boolean;
  status: string | null;
};

export type V2DeferredRevisionEffect = {
  candidateStatus: string;
  slotIds: string[];
};

export type V2RuntimeEventEffects = {
  workflowId: string | null;
  execution: V2ExecutionEffect | null;
  refreshRuntime: boolean;
  refreshAssets: boolean;
  slotVersionSlotIds: string[];
  providerTaskSlotIds: string[];
  resolvedInputNodeIds: string[];
  resolvedInputSlotIds: string[];
  finalCompositionEvents: WorkflowRuntimeEventV2[];
  authoringWorkflowRevisionCreated: boolean;
  deferredRevision: V2DeferredRevisionEffect | null;
  synchronization: V2SynchronizationRefreshPlan;
};

const NODE_STATUS_EVENT_TYPES = new Set([
  "node_status_changed",
  "node_started",
  "node_running",
  "node_queued",
  "node_waiting",
  "node_failed",
  "node_completed",
  "node_skipped",
  "node_cancelled",
  "node_blocked",
]);

const EXECUTION_EVENT_TYPES = new Set([
  "execution_queued",
  "execution_started",
  "execution_waiting",
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "execution_cancelled",
]);

const TERMINAL_EXECUTION_EVENT_TYPES = new Set([
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "execution_cancelled",
]);

export function routeCanvasRuntimeEvent(event: CanvasRuntimeEvent): CanvasRuntimeEventEffect {
  if (NODE_STATUS_EVENT_TYPES.has(event.event_type)) return { kind: "node_status" };
  if (event.event_type === "node_output_updated" || event.event_type === "node_assets_updated") return { kind: "node_refresh" };
  if (event.event_type === "media_status_changed") return { kind: "media_status" };
  if (event.event_type === "graph_updated") return { kind: "graph_refresh" };
  if (event.event_type === "resolved_inputs_updated") return { kind: "resolved_inputs_refresh" };
  if (isChatCanvasActionRuntimeEvent(event.event_type) || ["chat_action_created", "chat_action_applied", "chat_action_rejected", "chat_action_failed"].includes(event.event_type)) return { kind: "conversation_action" };
  if (isChatCanvasPromptRuntimeEvent(event.event_type) || ["node_prompt_updated", "item_prompt_updated"].includes(event.event_type)) return { kind: "conversation_prompt" };
  if (isChatCanvasRevisionRuntimeEvent(event.event_type) || ["revision_started", "revision_waiting", "revision_completed", "revision_failed"].includes(event.event_type)) return { kind: "conversation_revision" };
  if (isCanvasRuntimeAssetLibraryEvent(event.event_type)) return { kind: "asset_library" };
  if (isCanvasRuntimeCandidateEvent(event.event_type) || event.event_type === "candidate_created") return { kind: "candidate" };
  if (isCanvasRuntimeTimelineEvent(event.event_type) || ["timeline_updated", "timeline_clip_stale", "final_render_started", "final_render_completed", "final_render_failed"].includes(event.event_type)) return { kind: "final_composition" };
  if (TERMINAL_EXECUTION_EVENT_TYPES.has(event.event_type)) return { kind: "execution_terminal" };
  if (event.event_type === "snapshot_required") return { kind: "snapshot" };
  return { kind: "none" };
}

export function routeV2RuntimeEvents(events: WorkflowRuntimeEventV2[]): V2RuntimeEventEffects {
  const authoring = createV2AuthoringRuntimeEventPolicy(events);
  const ordinaryEvents = authoring.ordinaryRuntimeEvents;
  const latestExecution = [...ordinaryEvents].reverse().find((event) => EXECUTION_EVENT_TYPES.has(event.event_type));
  const deferredSlotIds = new Set(authoring.deferredCandidateSlotIds);
  const slotVersionSlotIds = new Set<string>();
  const providerTaskSlotIds = new Set<string>();
  const resolvedInputNodeIds = new Set<string>();
  const resolvedInputSlotIds = new Set<string>();

  ordinaryEvents.forEach((event) => {
    const slotId = v2RuntimeEventSlotId(event);
    if (slotId && (V2_SLOT_VERSION_REFRESH_EVENT_TYPES.has(event.event_type) || v2EventRefreshHints(event).includes("slot_versions"))) {
      slotVersionSlotIds.add(slotId);
    }
    if (slotId && v2EventShouldRefreshProviderTasks(event)) providerTaskSlotIds.add(slotId);
    if (event.event_type === "resolved_inputs_updated" || event.event_type === "slot_selected_version_updated" || v2EventRefreshHints(event).includes("resolved_inputs")) {
      if (event.node_id) resolvedInputNodeIds.add(event.node_id);
      else if (slotId) resolvedInputSlotIds.add(slotId);
    }
  });
  deferredSlotIds.forEach((slotId) => slotVersionSlotIds.add(slotId));

  return {
    workflowId: events.find((event) => event.workflow_id)?.workflow_id ?? null,
    execution: latestExecution ? executionEffect(latestExecution) : null,
    refreshRuntime: ordinaryEvents.some(v2EventShouldRefreshRuntime),
    refreshAssets: ordinaryEvents.some(v2EventShouldRefreshAssets),
    slotVersionSlotIds: Array.from(slotVersionSlotIds),
    providerTaskSlotIds: Array.from(providerTaskSlotIds),
    resolvedInputNodeIds: Array.from(resolvedInputNodeIds),
    resolvedInputSlotIds: Array.from(resolvedInputSlotIds),
    finalCompositionEvents: ordinaryEvents.filter((event) =>
      V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES.has(event.event_type) || shouldReloadFinalCompositionTimeline([event.event_type])),
    authoringWorkflowRevisionCreated: authoring.shouldRefreshAuthoringWorkflow,
    deferredRevision: authoring.shouldRefreshDeferredCandidates && authoring.candidateStatus
      ? { candidateStatus: authoring.candidateStatus, slotIds: Array.from(deferredSlotIds) }
      : null,
    synchronization: createV2SynchronizationRefreshPlan(events),
  };
}

function executionEffect(event: WorkflowRuntimeEventV2): V2ExecutionEffect {
  const executionId = stringFromUnknown(event.payload?.execution_id ?? event.payload?.active_execution_id);
  if (event.event_type === "execution_completed") return { executionId, pollingState: "completed", workflowRunning: false, status: "Workflow V2 run complete" };
  if (event.event_type === "execution_partial_failed") return { executionId, pollingState: "failed", workflowRunning: false, status: "Workflow V2 run partially failed" };
  if (event.event_type === "execution_failed" || event.event_type === "execution_cancelled") {
    return { executionId, pollingState: "failed", workflowRunning: false, status: event.event_type === "execution_cancelled" ? "Workflow V2 run cancelled" : "Workflow V2 run failed" };
  }
  if (event.event_type === "execution_waiting") return { executionId, pollingState: "polling", workflowRunning: true, status: "Workflow V2 run waiting for media" };
  return { executionId, pollingState: "polling", workflowRunning: true, status: null };
}

function stringFromUnknown(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
