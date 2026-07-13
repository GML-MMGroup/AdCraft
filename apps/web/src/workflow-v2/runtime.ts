import type {
  WorkflowRuntimeEventV2,
  WorkflowRuntimeV2,
  WorkflowV2ItemRuntime,
  WorkflowV2NodeRuntime,
  WorkflowV2SlotRuntime,
} from "../types-v2.ts";

export type V2RuntimeConnectionState = "connecting" | "connected" | "reconnecting" | "degraded_polling" | "disconnected";
export type V2ConnectionState = V2RuntimeConnectionState;

export const V2_SYNCHRONIZATION_EVENT_TYPES = new Set([
  "script_version_created",
  "script_selected_version_updated",
  "workflow_structure_updated",
  "linked_context_updated",
]);

export function isV2SynchronizationEvent(eventType: string): boolean {
  return V2_SYNCHRONIZATION_EVENT_TYPES.has(eventType);
}

export interface WorkflowRuntimeStoreV2 {
  connectionState: V2RuntimeConnectionState;
  lastEventSeq: number;
  activeExecutionId: string | null;
  executionStatus: string | null;
  runningSlotIds: string[];
  runningItemIds: string[];
  runningNodeIds: string[];
  waitingSlotIds: string[];
  waitingItemIds: string[];
  waitingNodeIds: string[];
  failedSlotIds: string[];
  failedItemIds: string[];
  failedNodeIds: string[];
  completedSlotIds: string[];
  completedItemIds: string[];
  completedNodeIds: string[];
  blockedSlotIds: string[];
  blockedItemIds: string[];
  blockedNodeIds: string[];
  skippedSlotIds: string[];
  skippedItemIds: string[];
  skippedNodeIds: string[];
  slotNodeIds: Record<string, string>;
  slotItemIds: Record<string, string>;
  slotRuntimeById: Record<string, WorkflowV2SlotRuntime>;
  itemRuntimeById: Record<string, WorkflowV2ItemRuntime>;
  nodeRuntimeById: Record<string, WorkflowV2NodeRuntime>;
  refreshWorkflow: boolean;
  refreshRuntime: boolean;
  refreshAssets: boolean;
  refreshSlotVersions: boolean;
  refreshResolvedInputs: boolean;
}
export type V2RuntimeStore = WorkflowRuntimeStoreV2;

export const initialWorkflowRuntimeStoreV2: WorkflowRuntimeStoreV2 = {
  connectionState: "disconnected",
  lastEventSeq: 0,
  activeExecutionId: null,
  executionStatus: null,
  runningSlotIds: [],
  runningItemIds: [],
  runningNodeIds: [],
  waitingSlotIds: [],
  waitingItemIds: [],
  waitingNodeIds: [],
  failedSlotIds: [],
  failedItemIds: [],
  failedNodeIds: [],
  completedSlotIds: [],
  completedItemIds: [],
  completedNodeIds: [],
  blockedSlotIds: [],
  blockedItemIds: [],
  blockedNodeIds: [],
  skippedSlotIds: [],
  skippedItemIds: [],
  skippedNodeIds: [],
  slotNodeIds: {},
  slotItemIds: {},
  slotRuntimeById: {},
  itemRuntimeById: {},
  nodeRuntimeById: {},
  refreshWorkflow: false,
  refreshRuntime: false,
  refreshAssets: false,
  refreshSlotVersions: false,
  refreshResolvedInputs: false,
};

export function createInitialV2RuntimeStore(): V2RuntimeStore {
  return {
    ...initialWorkflowRuntimeStoreV2,
    runningSlotIds: [],
    runningItemIds: [],
    runningNodeIds: [],
    waitingSlotIds: [],
    waitingItemIds: [],
    waitingNodeIds: [],
    failedSlotIds: [],
    failedItemIds: [],
    failedNodeIds: [],
    completedSlotIds: [],
    completedItemIds: [],
    completedNodeIds: [],
    blockedSlotIds: [],
    blockedItemIds: [],
    blockedNodeIds: [],
    skippedSlotIds: [],
    skippedItemIds: [],
    skippedNodeIds: [],
    slotNodeIds: {},
    slotItemIds: {},
    slotRuntimeById: {},
    itemRuntimeById: {},
    nodeRuntimeById: {},
  };
}

function without(values: string[], value?: string | null) {
  if (!value) return values;
  return values.filter((item) => item !== value);
}

function withValue(values: string[], value?: string | null) {
  if (!value || values.includes(value)) return values;
  return [...values, value];
}

function eventText(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function executionIdFromEvent(event: WorkflowRuntimeEventV2) {
  return eventText(event.payload?.execution_id) ?? eventText(event.payload?.active_execution_id);
}

function eventStatus(event: WorkflowRuntimeEventV2, fallback: string) {
  return eventText(event.payload?.status) ?? fallback;
}

function slotRuntimeFromEvent(event: WorkflowRuntimeEventV2, status: string): WorkflowV2SlotRuntime | null {
  if (!event.slot_id) return null;
  return {
    slot_id: event.slot_id,
    node_id: event.node_id ?? "",
    item_id: event.item_id ?? "",
    status,
    provider_task_id: eventText(event.payload?.provider_task_id ?? event.payload?.task_id),
    waiting_reason: eventText(event.payload?.waiting_reason),
    updated_at: event.created_at ?? null,
    metadata: event.payload ?? {},
  };
}

function itemRuntimeFromEvent(event: WorkflowRuntimeEventV2, status: string): WorkflowV2ItemRuntime | null {
  if (!event.item_id) return null;
  return {
    item_id: event.item_id,
    node_id: event.node_id ?? "",
    status,
    active_slot_ids: event.slot_id ? [event.slot_id] : [],
    updated_at: event.created_at ?? null,
    metadata: event.payload ?? {},
  };
}

function nodeRuntimeFromEvent(event: WorkflowRuntimeEventV2, status: string): WorkflowV2NodeRuntime | null {
  if (!event.node_id) return null;
  return {
    node_id: event.node_id,
    status,
    running_slot_ids: status === "running" && event.slot_id ? [event.slot_id] : [],
    waiting_slot_ids: status === "waiting" && event.slot_id ? [event.slot_id] : [],
    failed_slot_ids: status === "failed" && event.slot_id ? [event.slot_id] : [],
    completed_slot_ids: status === "completed" && event.slot_id ? [event.slot_id] : [],
    updated_at: event.created_at ?? null,
    metadata: event.payload ?? {},
  };
}

function withRuntimeRecords(store: WorkflowRuntimeStoreV2, event: WorkflowRuntimeEventV2, status: string): WorkflowRuntimeStoreV2 {
  const slotRuntime = slotRuntimeFromEvent(event, status);
  const itemRuntime = itemRuntimeFromEvent(event, status);
  const nodeRuntime = nodeRuntimeFromEvent(event, status);
  return {
    ...store,
    slotRuntimeById: slotRuntime ? { ...store.slotRuntimeById, [slotRuntime.slot_id]: { ...store.slotRuntimeById[slotRuntime.slot_id], ...slotRuntime } } : store.slotRuntimeById,
    itemRuntimeById: itemRuntime ? { ...store.itemRuntimeById, [itemRuntime.item_id]: { ...store.itemRuntimeById[itemRuntime.item_id], ...itemRuntime } } : store.itemRuntimeById,
    nodeRuntimeById: nodeRuntime ? { ...store.nodeRuntimeById, [nodeRuntime.node_id]: { ...store.nodeRuntimeById[nodeRuntime.node_id], ...nodeRuntime } } : store.nodeRuntimeById,
  };
}

export function applyWorkflowRuntimeSnapshotV2(current: WorkflowRuntimeStoreV2, snapshot: Partial<WorkflowRuntimeV2> | null | undefined): WorkflowRuntimeStoreV2 {
  if (!snapshot) return current;
  const snapshotSlotNodeIds = slotRuntimeIdentityMap(snapshot.slot_runtime, "node_id");
  const snapshotSlotItemIds = slotRuntimeIdentityMap(snapshot.slot_runtime, "item_id");
  const slotRuntimeById = snapshot.slot_runtime ?? {};
  const itemRuntimeById = snapshot.item_runtime ?? {};
  const nodeRuntimeById = snapshot.node_runtime ?? {};
  return {
    ...current,
    connectionState: "connected",
    lastEventSeq: typeof snapshot.events_cursor === "number" ? snapshot.events_cursor : current.lastEventSeq,
    activeExecutionId: snapshot.active_execution_id ?? current.activeExecutionId,
    executionStatus: snapshot.execution_status ?? current.executionStatus,
    runningSlotIds: snapshot.running_slot_ids ?? [],
    runningItemIds: snapshot.running_item_ids ?? [],
    runningNodeIds: snapshot.running_node_ids ?? [],
    waitingSlotIds: snapshot.waiting_slot_ids ?? [],
    waitingItemIds: snapshot.waiting_item_ids ?? [],
    waitingNodeIds: snapshot.waiting_node_ids ?? [],
    failedSlotIds: snapshot.failed_slot_ids ?? [],
    failedItemIds: snapshot.failed_item_ids ?? [],
    failedNodeIds: snapshot.failed_node_ids ?? [],
    completedSlotIds: snapshot.completed_slot_ids ?? [],
    completedItemIds: snapshot.completed_item_ids ?? [],
    completedNodeIds: snapshot.completed_node_ids ?? [],
    blockedSlotIds: snapshot.blocked_slot_ids ?? [],
    blockedItemIds: snapshot.blocked_item_ids ?? [],
    blockedNodeIds: snapshot.blocked_node_ids ?? [],
    skippedSlotIds: snapshot.skipped_slot_ids ?? [],
    skippedItemIds: snapshot.skipped_item_ids ?? [],
    skippedNodeIds: snapshot.skipped_node_ids ?? [],
    slotNodeIds: { ...current.slotNodeIds, ...snapshotSlotNodeIds },
    slotItemIds: { ...current.slotItemIds, ...snapshotSlotItemIds },
    slotRuntimeById: { ...current.slotRuntimeById, ...slotRuntimeById },
    itemRuntimeById: { ...current.itemRuntimeById, ...itemRuntimeById },
    nodeRuntimeById: { ...current.nodeRuntimeById, ...nodeRuntimeById },
    refreshWorkflow: false,
    refreshRuntime: false,
    refreshAssets: false,
    refreshSlotVersions: false,
    refreshResolvedInputs: false,
  };
}
export const applyV2RuntimeSnapshot = applyWorkflowRuntimeSnapshotV2;

export function applyWorkflowRuntimeEventV2(current: WorkflowRuntimeStoreV2, event: WorkflowRuntimeEventV2): WorkflowRuntimeStoreV2 {
  if (event.seq > 0 && event.seq <= current.lastEventSeq) return current;
  let next: WorkflowRuntimeStoreV2 = {
    ...current,
    connectionState: "connected",
    lastEventSeq: Math.max(current.lastEventSeq, event.seq),
    refreshWorkflow: false,
    refreshRuntime: false,
    refreshAssets: false,
    refreshSlotVersions: false,
    refreshResolvedInputs: false,
  };
  if (isV2SynchronizationEvent(event.event_type)) {
    const refresh = refreshHints(event);
    return {
      ...next,
      refreshWorkflow:
        event.event_type === "script_selected_version_updated" ||
        event.event_type === "workflow_structure_updated" ||
        (event.event_type === "linked_context_updated" &&
          refresh.some((hint) => hint === "workflow" || hint === "slot_prompts" || hint === "references")),
    };
  }
  const slotId = event.slot_id;
  const itemId = event.item_id ?? (slotId ? next.slotItemIds[slotId] : undefined);
  const nodeId = event.node_id ?? (slotId ? next.slotNodeIds[slotId] : undefined);
  const scopedEvent: WorkflowRuntimeEventV2 = { ...event, item_id: itemId, node_id: nodeId };
  const providerStatus = providerTaskStatusFromEvent(event);
  if (slotId && nodeId) next = { ...next, slotNodeIds: { ...next.slotNodeIds, [slotId]: nodeId } };
  if (slotId && itemId) next = { ...next, slotItemIds: { ...next.slotItemIds, [slotId]: itemId } };

  if (event.event_type === "execution_started") {
    next = {
      ...next,
      activeExecutionId: executionIdFromEvent(event) ?? next.activeExecutionId,
      executionStatus: eventStatus(event, "running"),
      refreshRuntime: true,
    };
  }
  if (event.event_type === "execution_waiting") {
    next = {
      ...next,
      activeExecutionId: executionIdFromEvent(event) ?? next.activeExecutionId,
      executionStatus: eventStatus(event, "waiting"),
      refreshRuntime: true,
    };
  }
  if (
    event.event_type === "execution_completed" ||
    event.event_type === "execution_partial_failed" ||
    event.event_type === "execution_failed" ||
    event.event_type === "execution_cancelled"
  ) {
    const terminalStatus =
      event.event_type === "execution_completed"
        ? "completed"
        : event.event_type === "execution_partial_failed"
          ? "partial_failed"
          : event.event_type === "execution_cancelled"
            ? "cancelled"
            : "failed";
    next = {
      ...next,
      activeExecutionId: executionIdFromEvent(event) ?? next.activeExecutionId,
      executionStatus: eventStatus(event, terminalStatus),
      runningSlotIds: [],
      runningItemIds: [],
      runningNodeIds: [],
      waitingSlotIds: [],
      waitingItemIds: [],
      waitingNodeIds: [],
      refreshWorkflow: true,
      refreshRuntime: true,
      refreshAssets: true,
      refreshSlotVersions: true,
      refreshResolvedInputs: true,
    };
  }

  if (
    event.event_type === "slot_queued" ||
    event.event_type === "slot_generation_started" ||
    event.event_type === "provider_execution_started"
  ) {
    const status = event.event_type === "slot_queued" ? "queued" : "running";
    next = {
      ...next,
      runningSlotIds: withValue(without(next.runningSlotIds, slotId), slotId),
      waitingSlotIds: without(next.waitingSlotIds, slotId),
      failedSlotIds: without(next.failedSlotIds, slotId),
      blockedSlotIds: without(next.blockedSlotIds, slotId),
      skippedSlotIds: without(next.skippedSlotIds, slotId),
      runningItemIds: withValue(next.runningItemIds, itemId),
      waitingItemIds: without(next.waitingItemIds, itemId),
      failedItemIds: without(next.failedItemIds, itemId),
      blockedItemIds: without(next.blockedItemIds, itemId),
      skippedItemIds: without(next.skippedItemIds, itemId),
      runningNodeIds: withValue(next.runningNodeIds, nodeId),
      waitingNodeIds: without(next.waitingNodeIds, nodeId),
      failedNodeIds: without(next.failedNodeIds, nodeId),
      blockedNodeIds: without(next.blockedNodeIds, nodeId),
      skippedNodeIds: without(next.skippedNodeIds, nodeId),
      refreshRuntime: true,
    };
    next = withRuntimeRecords(next, scopedEvent, status);
  }
  if (
    event.event_type === "slot_generation_waiting" ||
    event.event_type === "provider_execution_waiting" ||
    event.event_type === "provider_task_submitted" ||
    event.event_type === "provider_task_waiting" ||
    (event.event_type === "provider_task_polled" && !providerTaskStatusIsTerminal(providerStatus))
  ) {
    next = {
      ...next,
      runningSlotIds: without(next.runningSlotIds, slotId),
      waitingSlotIds: withValue(next.waitingSlotIds, slotId),
      runningItemIds: without(next.runningItemIds, itemId),
      waitingItemIds: withValue(next.waitingItemIds, itemId),
      runningNodeIds: without(next.runningNodeIds, nodeId),
      waitingNodeIds: withValue(next.waitingNodeIds, nodeId),
      refreshRuntime: true,
    };
    next = withRuntimeRecords(next, scopedEvent, "waiting");
  }
  if (
    event.event_type === "slot_generation_completed" ||
    event.event_type === "slot_selected_version_updated" ||
    event.event_type === "provider_execution_completed" ||
    event.event_type === "provider_task_completed" ||
    (event.event_type === "provider_task_polled" && providerStatus === "completed")
  ) {
    next = {
      ...next,
      runningSlotIds: without(next.runningSlotIds, slotId),
      waitingSlotIds: without(next.waitingSlotIds, slotId),
      failedSlotIds: without(next.failedSlotIds, slotId),
      blockedSlotIds: without(next.blockedSlotIds, slotId),
      skippedSlotIds: without(next.skippedSlotIds, slotId),
      completedSlotIds: withValue(next.completedSlotIds, slotId),
      runningItemIds: without(next.runningItemIds, itemId),
      waitingItemIds: without(next.waitingItemIds, itemId),
      failedItemIds: without(next.failedItemIds, itemId),
      blockedItemIds: without(next.blockedItemIds, itemId),
      skippedItemIds: without(next.skippedItemIds, itemId),
      completedItemIds: withValue(next.completedItemIds, itemId),
      refreshWorkflow: true,
      refreshRuntime: true,
      refreshAssets: true,
      refreshSlotVersions: true,
      refreshResolvedInputs: event.event_type === "slot_selected_version_updated" || refreshHints(event).includes("resolved_inputs"),
    };
    next = withRuntimeRecords(next, scopedEvent, "completed");
  }
  if (
    event.event_type === "asset_version_created" ||
    event.event_type === "slot_working_version_created" ||
    event.event_type === "slot_working_version_updated" ||
    event.event_type === "item_working_version_updated"
  ) {
    const refresh = refreshHints(event);
    next = {
      ...next,
      refreshWorkflow: true,
      refreshRuntime: true,
      refreshAssets: true,
      refreshSlotVersions: true,
      refreshResolvedInputs: refresh.includes("resolved_inputs") || next.refreshResolvedInputs,
    };
  }
  if (
    event.event_type === "slot_generation_failed" ||
    event.event_type === "provider_execution_failed" ||
    event.event_type === "provider_task_failed" ||
    event.event_type === "provider_task_cancelled" ||
    event.event_type === "provider_task_expired" ||
    (event.event_type === "provider_task_polled" && providerTaskStatusIsTerminalFailure(providerStatus))
  ) {
    next = {
      ...next,
      runningSlotIds: without(next.runningSlotIds, slotId),
      waitingSlotIds: without(next.waitingSlotIds, slotId),
      completedSlotIds: without(next.completedSlotIds, slotId),
      blockedSlotIds: without(next.blockedSlotIds, slotId),
      skippedSlotIds: without(next.skippedSlotIds, slotId),
      failedSlotIds: withValue(next.failedSlotIds, slotId),
      runningItemIds: without(next.runningItemIds, itemId),
      waitingItemIds: without(next.waitingItemIds, itemId),
      failedItemIds: withValue(next.failedItemIds, itemId),
      runningNodeIds: without(next.runningNodeIds, nodeId),
      waitingNodeIds: without(next.waitingNodeIds, nodeId),
      failedNodeIds: withValue(next.failedNodeIds, nodeId),
      refreshRuntime: true,
    };
    next = withRuntimeRecords(next, scopedEvent, "failed");
  }
  if (event.event_type === "slot_blocked") {
    next = {
      ...next,
      runningSlotIds: without(next.runningSlotIds, slotId),
      waitingSlotIds: without(next.waitingSlotIds, slotId),
      failedSlotIds: without(next.failedSlotIds, slotId),
      completedSlotIds: without(next.completedSlotIds, slotId),
      blockedSlotIds: withValue(next.blockedSlotIds, slotId),
      runningItemIds: without(next.runningItemIds, itemId),
      waitingItemIds: without(next.waitingItemIds, itemId),
      blockedItemIds: withValue(next.blockedItemIds, itemId),
      runningNodeIds: without(next.runningNodeIds, nodeId),
      waitingNodeIds: without(next.waitingNodeIds, nodeId),
      blockedNodeIds: withValue(next.blockedNodeIds, nodeId),
      refreshRuntime: true,
    };
    next = withRuntimeRecords(next, scopedEvent, "blocked");
  }
  if (event.event_type === "slot_skipped") {
    next = {
      ...next,
      runningSlotIds: without(next.runningSlotIds, slotId),
      waitingSlotIds: without(next.waitingSlotIds, slotId),
      failedSlotIds: without(next.failedSlotIds, slotId),
      completedSlotIds: without(next.completedSlotIds, slotId),
      skippedSlotIds: withValue(next.skippedSlotIds, slotId),
      runningItemIds: without(next.runningItemIds, itemId),
      waitingItemIds: without(next.waitingItemIds, itemId),
      skippedItemIds: withValue(next.skippedItemIds, itemId),
      runningNodeIds: without(next.runningNodeIds, nodeId),
      waitingNodeIds: without(next.waitingNodeIds, nodeId),
      skippedNodeIds: withValue(next.skippedNodeIds, nodeId),
      refreshRuntime: true,
    };
    next = withRuntimeRecords(next, scopedEvent, "skipped");
  }
  if (
    event.event_type === "chat_target_resolved" ||
    event.event_type === "specialist_route_resolved" ||
    event.event_type === "asset_owner_resolved" ||
    event.event_type === "runtime_snapshot_updated"
  ) {
    next = { ...next, refreshRuntime: true };
  }
  if (event.event_type === "node_assets_updated") {
    next = { ...next, refreshWorkflow: true, refreshAssets: true };
  }
  if (event.event_type === "graph_updated") {
    next = { ...next, refreshWorkflow: true };
  }
  if (
    event.event_type === "prompt_updated" ||
    event.event_type === "item_prompt_updated" ||
    event.event_type === "slot_prompt_updated" ||
    event.event_type === "slot_marked_stale" ||
    event.event_type === "reference_attached" ||
    event.event_type === "reference_removed" ||
    event.event_type === "slot_working_version_discarded" ||
    event.event_type === "slot_history_updated" ||
    event.event_type === "asset_history_updated" ||
    event.event_type === "workflow_updated" ||
    event.event_type === "resolved_inputs_updated" ||
    event.event_type === "slot_outdated_hint_added" ||
    event.event_type === "item_outdated_hint_added" ||
    event.event_type === "node_outdated_hint_added" ||
    event.event_type === "slot_outdated_hint_cleared" ||
    event.event_type === "storyboard_summary_refined"
  ) {
    const refresh = refreshHints(event);
    next = {
      ...next,
      refreshWorkflow: event.event_type !== "resolved_inputs_updated" || next.refreshWorkflow,
      refreshAssets: event.event_type === "asset_history_updated" || next.refreshAssets,
      refreshSlotVersions: event.event_type === "slot_history_updated" || event.event_type === "asset_history_updated" || refresh.includes("slot_versions") || next.refreshSlotVersions,
      refreshResolvedInputs: event.event_type === "resolved_inputs_updated" || refresh.includes("resolved_inputs") || next.refreshResolvedInputs,
    };
  }

  return next;
}
export const reduceV2RuntimeEvent = applyWorkflowRuntimeEventV2;

export function slotRuntimeStatusV2(store: WorkflowRuntimeStoreV2, slotId: string) {
  if (store.runningSlotIds.includes(slotId)) return "running";
  if (store.waitingSlotIds.includes(slotId)) return "waiting";
  if (store.failedSlotIds.includes(slotId)) return "failed";
  if (store.completedSlotIds.includes(slotId)) return "completed";
  if (store.blockedSlotIds.includes(slotId)) return "blocked";
  if (store.skippedSlotIds.includes(slotId)) return "skipped";
  return store.slotRuntimeById[slotId]?.status ?? "idle";
}

export function regionHasActiveSlotRuntime(store: WorkflowRuntimeStoreV2, nodeId: string) {
  const activeSlotIds = [...store.runningSlotIds, ...store.waitingSlotIds];
  return activeSlotIds.some((slotId) => store.slotNodeIds[slotId] === nodeId) ||
    Object.values(store.slotRuntimeById).some((runtime) => runtime.node_id === nodeId && (runtime.status === "running" || runtime.status === "waiting"));
}

export function v2RuntimeSlotStatusById(store: WorkflowRuntimeStoreV2): Record<string, string> {
  const statusBySlotId: Record<string, string> = Object.fromEntries(
    Object.entries(store.slotRuntimeById).map(([slotId, runtime]) => [slotId, runtime.status]),
  );
  for (const slotId of store.completedSlotIds) statusBySlotId[slotId] = "completed";
  for (const slotId of store.blockedSlotIds) statusBySlotId[slotId] = "blocked";
  for (const slotId of store.skippedSlotIds) statusBySlotId[slotId] = "skipped";
  for (const slotId of store.failedSlotIds) statusBySlotId[slotId] = "failed";
  for (const slotId of store.waitingSlotIds) statusBySlotId[slotId] = "waiting";
  for (const slotId of store.runningSlotIds) statusBySlotId[slotId] = "running";
  return statusBySlotId;
}

export function v2RuntimeNodeStatusById(store: WorkflowRuntimeStoreV2): Record<string, string> {
  const statusByNodeId: Record<string, string> = Object.fromEntries(
    Object.entries(store.nodeRuntimeById).map(([nodeId, runtime]) => [nodeId, runtime.status]),
  );
  for (const nodeId of store.completedNodeIds) statusByNodeId[nodeId] = "completed";
  for (const nodeId of store.blockedNodeIds) statusByNodeId[nodeId] = "blocked";
  for (const nodeId of store.skippedNodeIds) statusByNodeId[nodeId] = "skipped";
  for (const nodeId of store.failedNodeIds) statusByNodeId[nodeId] = "failed";
  for (const nodeId of store.waitingNodeIds) statusByNodeId[nodeId] = "waiting";
  for (const nodeId of store.runningNodeIds) statusByNodeId[nodeId] = "running";

  for (const slotId of store.completedSlotIds) {
    const nodeId = store.slotNodeIds[slotId];
    if (nodeId && !statusByNodeId[nodeId]) statusByNodeId[nodeId] = "completed";
  }
  for (const slotId of store.failedSlotIds) {
    const nodeId = store.slotNodeIds[slotId];
    if (nodeId) statusByNodeId[nodeId] = "failed";
  }
  for (const slotId of store.waitingSlotIds) {
    const nodeId = store.slotNodeIds[slotId];
    if (nodeId) statusByNodeId[nodeId] = "waiting";
  }
  for (const slotId of store.runningSlotIds) {
    const nodeId = store.slotNodeIds[slotId];
    if (nodeId) statusByNodeId[nodeId] = "running";
  }
  return statusByNodeId;
}

export function v2RuntimeActiveNodeIds(store: WorkflowRuntimeStoreV2): string[] {
  return Array.from(new Set([
    ...store.runningNodeIds,
    ...store.waitingNodeIds,
    ...Object.values(store.nodeRuntimeById).filter((runtime) => runtime.status === "running" || runtime.status === "waiting").map((runtime) => runtime.node_id),
    ...store.runningSlotIds.map((slotId) => store.slotNodeIds[slotId]).filter((nodeId): nodeId is string => Boolean(nodeId)),
    ...store.waitingSlotIds.map((slotId) => store.slotNodeIds[slotId]).filter((nodeId): nodeId is string => Boolean(nodeId)),
    ...Object.values(store.slotRuntimeById)
      .filter((runtime) => runtime.status === "running" || runtime.status === "waiting")
      .map((runtime) => runtime.node_id)
      .filter((nodeId): nodeId is string => Boolean(nodeId)),
  ]));
}

export function v2RuntimeActiveEdgeSourceNodeIds(store: WorkflowRuntimeStoreV2): string[] {
  return v2RuntimeActiveNodeIds(store);
}

function providerTaskStatusFromEvent(event: WorkflowRuntimeEventV2) {
  const status = event.payload?.status;
  return typeof status === "string" ? status.toLowerCase() : "";
}

function providerTaskStatusIsTerminal(status: string) {
  return status === "completed" || providerTaskStatusIsTerminalFailure(status);
}

export function providerTaskStatusIsTerminalFailure(status: string) {
  return status === "failed" || status === "cancelled" || status === "expired";
}

function refreshHints(event: WorkflowRuntimeEventV2) {
  const raw = event.payload?.refresh;
  return Array.isArray(raw) ? raw.filter((item): item is string => typeof item === "string") : [];
}

function slotRuntimeIdentityMap(runtime: Partial<WorkflowRuntimeV2>["slot_runtime"], key: "node_id" | "item_id") {
  const result: Record<string, string> = {};
  if (!runtime) return result;
  for (const [slotId, record] of Object.entries(runtime)) {
    const value = record && typeof record === "object" ? (record as unknown as Record<string, unknown>)[key] : undefined;
    if (typeof value === "string" && value) result[slotId] = value;
  }
  return result;
}
