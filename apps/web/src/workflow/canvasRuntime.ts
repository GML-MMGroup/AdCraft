import type { MediaStatus, WorkflowGraph } from "../types";

export type CanvasRuntimeConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "degraded_polling"
  | "disconnected";

export type CanvasRuntimeEventType =
  | "node_status_changed"
  | "node_output_updated"
  | "node_assets_updated"
  | "media_status_changed"
  | "graph_updated"
  | "resolved_inputs_updated"
  | "snapshot_required"
  | "connection_reconnecting"
  | "polling_degraded"
  | string;

export type CanvasRuntimeCandidateRefresh =
  | "revision"
  | "revisions"
  | "asset_history"
  | "candidate_summary"
  | "node_assets"
  | "workflow_graph"
  | "resolved_inputs";

export type CanvasRuntimeCandidatePayload = {
  revisionId: string | null;
  entityId: string | null;
  semanticType: string | null;
  targetAssetId: string | null;
  candidateAssetIds: string[];
  activeAssetIds: string[];
  previousActiveAssetIds: string[];
  supersededByRevisionId: string | null;
  affectedDownstreamNodeIds: string[];
  candidateCount: number | null;
  candidateWarningCount: number | null;
  pendingVisibleCandidateCount: number | null;
  qualityStatus: string | null;
  issueCount: number | null;
  generationStatus: string | null;
  acceptanceStatus: string | null;
  visibilityStatus: string | null;
  libraryState: string | null;
  libraryEntityId: string | null;
  libraryAssetId: string | null;
  libraryError: string | null;
  sourceType: string | null;
  waitingReason: string | null;
  error: string | null;
  errorCode: string | null;
  refresh: CanvasRuntimeCandidateRefresh[];
};

export type CanvasRuntimeNodeState = {
  node_id: string;
  node_type?: string | null;
  status: string;
  status_source?: string | null;
  execution_id?: string | null;
  node_run_id?: string | null;
  waiting_reason?: string | null;
  error?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
};

export type CanvasRuntimeEvent = {
  event_seq: number;
  event_type: CanvasRuntimeEventType;
  workflow_id?: string | null;
  execution_id?: string | null;
  node_id?: string | null;
  status?: string | null;
  message?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string | null;
  [key: string]: unknown;
};

export type CanvasRuntimeSnapshot = {
  workflow_id?: string | null;
  graph?: WorkflowGraph | null;
  mediaStatus?: MediaStatus | null;
  lastEventSeq: number;
  activeExecutionId: string | null;
  nodeRuntimeById: Record<string, CanvasRuntimeNodeState>;
  queuedNodeIds: string[];
  runningNodeIds: string[];
  waitingNodeIds: string[];
  completedNodeIds: string[];
  failedNodeIds: string[];
  skippedNodeIds: string[];
  activeEdgeIds: string[];
};

export type CanvasRuntimeEventsResponse = {
  workflow_id?: string | null;
  events: CanvasRuntimeEvent[];
  next_after_seq: number;
};

export type CanvasRuntimeStore = {
  connectionState: CanvasRuntimeConnectionState;
  lastEventSeq: number;
  activeExecutionId: string | null;
  nodeRuntimeById: Record<string, CanvasRuntimeNodeState>;
  queuedNodeIds: string[];
  runningNodeIds: string[];
  waitingNodeIds: string[];
  completedNodeIds: string[];
  failedNodeIds: string[];
  skippedNodeIds: string[];
  activeEdgeIds: string[];
  mediaStatus?: MediaStatus | null;
  graph?: WorkflowGraph | null;
};

export const initialCanvasRuntimeStore: CanvasRuntimeStore = {
  connectionState: "disconnected",
  lastEventSeq: 0,
  activeExecutionId: null,
  nodeRuntimeById: {},
  queuedNodeIds: [],
  runningNodeIds: [],
  waitingNodeIds: [],
  completedNodeIds: [],
  failedNodeIds: [],
  skippedNodeIds: [],
  activeEdgeIds: [],
  mediaStatus: null,
  graph: null,
};

export function normalizeCanvasRuntimeSnapshot(value: unknown): CanvasRuntimeSnapshot {
  const record = objectRecord(value);
  const explicitQueuedNodeIds = uniqueStrings(record.queuedNodeIds ?? record.queued_node_ids);
  const explicitRunningNodeIds = uniqueStrings(record.runningNodeIds ?? record.running_node_ids);
  const explicitWaitingNodeIds = uniqueStrings(record.waitingNodeIds ?? record.waiting_node_ids);
  const explicitCompletedNodeIds = uniqueStrings(record.completedNodeIds ?? record.completed_node_ids);
  const explicitFailedNodeIds = uniqueStrings(record.failedNodeIds ?? record.failed_node_ids);
  const explicitSkippedNodeIds = uniqueStrings(record.skippedNodeIds ?? record.skipped_node_ids);
  const activeExecution = objectRecord(record.activeExecution ?? record.active_execution);
  const activeExecutionId =
    firstString(
      record.activeExecutionId,
      record.active_execution_id,
      record.execution_id,
      activeExecution.execution_id,
      activeExecution.id,
    ) ?? null;
  const hasActiveExecution = Boolean(activeExecutionId);
  const nodeRuntimeById = mergeRuntimeListStatuses(normalizeNodeRuntimeMap(
    record.nodeRuntimeById ??
      record.node_runtime_by_id ??
      record.node_runtime ??
      record.nodes ??
      record.node_states,
  ), hasActiveExecution
    ? [
        [explicitQueuedNodeIds, "queued"],
        [explicitRunningNodeIds, "running"],
        [explicitWaitingNodeIds, "waiting"],
        [explicitCompletedNodeIds, "completed"],
        [explicitFailedNodeIds, "failed"],
        [explicitSkippedNodeIds, "skipped"],
      ]
    : [
        [explicitCompletedNodeIds, "completed"],
        [explicitFailedNodeIds, "failed"],
        [explicitSkippedNodeIds, "skipped"],
      ],
  "execution");

  return {
    workflow_id: firstString(record.workflow_id, record.workflowId) ?? null,
    graph: workflowGraphFromUnknown(record.graph ?? record.workflow),
    mediaStatus: mediaStatusFromUnknown(record.mediaStatus ?? record.media_status),
    lastEventSeq: numberFromUnknown(record.lastEventSeq, record.last_event_seq, record.event_seq, record.next_after_seq),
    activeExecutionId,
    nodeRuntimeById,
    queuedNodeIds: explicitQueuedNodeIds.length ? explicitQueuedNodeIds : nodeIdsByStatus(nodeRuntimeById, ["queued"]),
    runningNodeIds: hasActiveExecution
      ? explicitRunningNodeIds.length ? explicitRunningNodeIds : nodeIdsByRuntimeStatus(nodeRuntimeById, ["running", "in_progress", "processing"], activeExecutionId)
      : [],
    waitingNodeIds: hasActiveExecution
      ? explicitWaitingNodeIds.length ? explicitWaitingNodeIds : nodeIdsByRuntimeStatus(nodeRuntimeById, ["waiting"], activeExecutionId)
      : [],
    completedNodeIds: explicitCompletedNodeIds.length ? explicitCompletedNodeIds : nodeIdsByStatus(nodeRuntimeById, ["completed"]),
    failedNodeIds: explicitFailedNodeIds.length ? explicitFailedNodeIds : nodeIdsByStatus(nodeRuntimeById, ["failed", "error"]),
    skippedNodeIds: explicitSkippedNodeIds.length ? explicitSkippedNodeIds : nodeIdsByStatus(nodeRuntimeById, ["skipped"]),
    activeEdgeIds: uniqueStrings(record.activeEdgeIds ?? record.active_edge_ids),
  };
}

export function normalizeCanvasRuntimeEventsResponse(value: unknown): CanvasRuntimeEventsResponse {
  const record = objectRecord(value);
  const events = Array.isArray(record.events) ? record.events.map(normalizeCanvasRuntimeEvent) : [];
  const lastSeq = events.reduce((max, event) => Math.max(max, event.event_seq), 0);
  return {
    workflow_id: firstString(record.workflow_id, record.workflowId) ?? null,
    events,
    next_after_seq: numberFromUnknown(record.next_after_seq, record.last_event_seq, record.event_seq) || lastSeq,
  };
}

export function normalizeCanvasRuntimeEvent(value: unknown): CanvasRuntimeEvent {
  const record = objectRecord(value);
  const payload = objectRecord(record.payload);
  return {
    ...(record as CanvasRuntimeEvent),
    event_seq: numberFromUnknown(record.event_seq, record.seq, record.sequence),
    event_type: firstString(record.event_type, record.type) ?? "unknown",
    workflow_id: firstString(record.workflow_id, record.workflowId) ?? null,
    execution_id: firstString(record.execution_id, payload.execution_id) ?? null,
    node_id: firstString(record.node_id, payload.node_id, payload.id) ?? null,
    status: firstString(record.status, payload.status) ?? null,
    message: firstString(record.message, payload.message) ?? null,
    payload,
    created_at: firstString(record.created_at, record.createdAt) ?? null,
  };
}

export function applyCanvasRuntimeSnapshot(current: CanvasRuntimeStore, snapshot: CanvasRuntimeSnapshot): CanvasRuntimeStore {
  return {
    ...current,
    connectionState: "connected",
    lastEventSeq: Math.max(current.lastEventSeq, snapshot.lastEventSeq),
    activeExecutionId: snapshot.activeExecutionId ?? current.activeExecutionId,
    nodeRuntimeById: snapshot.nodeRuntimeById,
    queuedNodeIds: snapshot.queuedNodeIds,
    runningNodeIds: snapshot.runningNodeIds,
    waitingNodeIds: snapshot.waitingNodeIds,
    completedNodeIds: snapshot.completedNodeIds,
    failedNodeIds: snapshot.failedNodeIds,
    skippedNodeIds: snapshot.skippedNodeIds,
    activeEdgeIds: snapshot.activeEdgeIds,
    mediaStatus: snapshot.mediaStatus ?? current.mediaStatus ?? null,
    graph: snapshot.graph ?? current.graph ?? null,
  };
}

export function applyCanvasRuntimeEvent(current: CanvasRuntimeStore, rawEvent: CanvasRuntimeEvent): CanvasRuntimeStore {
  const event = normalizeCanvasRuntimeEvent(rawEvent);
  if (event.event_seq > 0 && event.event_seq <= current.lastEventSeq) return current;
  const next: CanvasRuntimeStore = {
    ...current,
    lastEventSeq: Math.max(current.lastEventSeq, event.event_seq),
    activeExecutionId: event.execution_id ?? current.activeExecutionId,
  };

  if (event.event_type === "connection_reconnecting") return { ...next, connectionState: "reconnecting" };
  if (event.event_type === "polling_degraded") return { ...next, connectionState: "degraded_polling" };
  if (event.event_type === "media_status_changed") {
    return { ...next, mediaStatus: mediaStatusFromUnknown(event.payload?.media_status ?? event.payload) ?? current.mediaStatus ?? null };
  }
  if (event.event_type === "graph_updated") {
    return { ...next, graph: workflowGraphFromUnknown(event.payload?.graph ?? event.payload?.workflow) ?? current.graph ?? null };
  }

  if (isNodeStatusEvent(event.event_type)) {
    const nodeId = event.node_id;
    const status = statusFromEvent(event);
    if (!nodeId || !status) return rebuildRuntimeLists(next);
    const previous = next.nodeRuntimeById[nodeId];
    return rebuildRuntimeLists({
      ...next,
      nodeRuntimeById: {
        ...next.nodeRuntimeById,
        [nodeId]: {
          ...previous,
          node_id: nodeId,
          node_type: firstString(event.payload?.node_type) ?? previous?.node_type ?? null,
          status,
          status_source: firstString(event.payload?.status_source, event.payload?.statusSource, event.status_source) ?? previous?.status_source ?? "execution",
          execution_id: event.execution_id ?? previous?.execution_id ?? null,
          node_run_id: firstString(event.payload?.node_run_id) ?? previous?.node_run_id ?? null,
          waiting_reason: firstString(event.payload?.waiting_reason) ?? previous?.waiting_reason ?? null,
          error: firstString(event.payload?.error) ?? previous?.error ?? null,
          updated_at: event.created_at ?? previous?.updated_at ?? null,
          metadata: objectRecord(event.payload?.metadata) ?? previous?.metadata,
        },
      },
    });
  }

  return next;
}

export function isCanvasRuntimeCandidateEvent(type: string) {
  return [
    "revision_status_changed",
    "candidate_created",
    "candidate_quality_updated",
    "candidate_accepted",
    "candidate_rejected",
    "candidate_superseded",
    "asset_history_updated",
    "node_candidate_summary_updated",
  ].includes(type);
}

export function isCanvasRuntimeAssetLibraryEvent(type: string) {
  return [
    "asset_library_entity_created",
    "asset_library_entity_linked",
    "asset_library_asset_linked",
    "asset_library_ingest_failed",
    "asset_reference_suggestions_updated",
  ].includes(type);
}

export function isCanvasRuntimeTimelineEvent(type: string) {
  return [
    "timeline_updated",
    "timeline_clip_stale",
    "final_render_started",
    "final_render_completed",
    "final_render_failed",
  ].includes(type);
}

export function normalizeCanvasRuntimeCandidatePayload(rawEvent: CanvasRuntimeEvent): CanvasRuntimeCandidatePayload {
  const event = normalizeCanvasRuntimeEvent(rawEvent);
  const payload = objectRecord(event.payload);
  return {
    revisionId: firstString(payload.revision_id, payload.revisionId) ?? null,
    entityId: firstString(payload.entity_id, payload.entityId, payload.target_entity_id, payload.targetEntityId) ?? null,
    semanticType: firstString(payload.semantic_type, payload.semanticType) ?? null,
    targetAssetId: firstString(payload.target_asset_id, payload.targetAssetId) ?? null,
    candidateAssetIds: uniqueStrings(payload.candidate_asset_ids ?? payload.candidateAssetIds),
    activeAssetIds: uniqueStrings(payload.active_asset_ids ?? payload.activeAssetIds),
    previousActiveAssetIds: uniqueStrings(payload.previous_active_asset_ids ?? payload.previousActiveAssetIds),
    supersededByRevisionId: firstString(payload.superseded_by_revision_id, payload.supersededByRevisionId) ?? null,
    affectedDownstreamNodeIds: uniqueStrings(payload.affected_downstream_node_ids ?? payload.affectedDownstreamNodeIds),
    candidateCount: nullableNumberFromUnknown(payload.candidate_count, payload.candidateCount),
    candidateWarningCount: nullableNumberFromUnknown(payload.candidate_warning_count, payload.candidateWarningCount),
    pendingVisibleCandidateCount: nullableNumberFromUnknown(payload.pending_visible_candidate_count, payload.pendingVisibleCandidateCount),
    qualityStatus: firstString(payload.quality_status, payload.qualityStatus) ?? null,
    issueCount: nullableNumberFromUnknown(payload.issue_count, payload.issueCount),
    generationStatus: firstString(payload.generation_status, payload.generationStatus) ?? null,
    acceptanceStatus: firstString(payload.acceptance_status, payload.acceptanceStatus) ?? null,
    visibilityStatus: firstString(payload.visibility_status, payload.visibilityStatus) ?? null,
    libraryState: firstString(payload.library_state, payload.libraryState) ?? null,
    libraryEntityId: firstString(payload.library_entity_id, payload.libraryEntityId) ?? null,
    libraryAssetId: firstString(payload.library_asset_id, payload.libraryAssetId) ?? null,
    libraryError: firstString(payload.library_error, payload.libraryError, payload.library_ingest_error, payload.libraryIngestError) ?? null,
    sourceType: firstString(payload.source_type, payload.sourceType) ?? null,
    waitingReason: firstString(payload.waiting_reason, payload.waitingReason) ?? null,
    error: firstString(payload.error) ?? null,
    errorCode: firstString(payload.error_code, payload.errorCode) ?? null,
    refresh: candidateRefreshValues(payload.refresh),
  };
}

export function canvasRuntimeEdgeSourceNodeIds(store: Pick<CanvasRuntimeStore, "activeExecutionId" | "nodeRuntimeById" | "runningNodeIds" | "waitingNodeIds">) {
  return uniqueStrings([...store.runningNodeIds, ...store.waitingNodeIds]).filter((nodeId) => {
    return isRuntimeExecutingNode(store.nodeRuntimeById[nodeId], store.activeExecutionId);
  });
}

export function canvasRuntimeNodeStatusMap(store: Pick<CanvasRuntimeStore, "activeExecutionId" | "nodeRuntimeById">) {
  return Object.fromEntries(
    Object.entries(store.nodeRuntimeById)
      .filter(([, node]) => Boolean(node.status))
      .map(([nodeId, node]) => [nodeId, displayRuntimeStatus(node, store.activeExecutionId)]),
  );
}

function rebuildRuntimeLists(store: CanvasRuntimeStore): CanvasRuntimeStore {
  return {
    ...store,
    queuedNodeIds: nodeIdsByStatus(store.nodeRuntimeById, ["queued"]),
    runningNodeIds: nodeIdsByRuntimeStatus(store.nodeRuntimeById, ["running", "processing", "in_progress"], store.activeExecutionId),
    waitingNodeIds: nodeIdsByRuntimeStatus(store.nodeRuntimeById, ["waiting"], store.activeExecutionId),
    completedNodeIds: nodeIdsByStatus(store.nodeRuntimeById, ["completed"]),
    failedNodeIds: nodeIdsByStatus(store.nodeRuntimeById, ["failed", "error"]),
    skippedNodeIds: nodeIdsByStatus(store.nodeRuntimeById, ["skipped"]),
  };
}

export function isRuntimeExecutingNode(node: CanvasRuntimeNodeState | undefined, activeExecutionId?: string | null) {
  if (!node) return false;
  const status = normalizeStatus(node.status);
  if (!["running", "waiting", "processing", "in_progress"].includes(status)) return false;
  const statusSource = runtimeStatusSource(node);
  if (statusSource === "graph" || statusSource === "plan" || statusSource === "planned") return false;
  return statusSource === "execution" || Boolean(node.execution_id) || Boolean(activeExecutionId);
}

export function displayRuntimeStatus(node: CanvasRuntimeNodeState, activeExecutionId?: string | null) {
  const status = normalizeStatus(node.status);
  if (["running", "waiting", "processing", "in_progress"].includes(status) && !isRuntimeExecutingNode(node, activeExecutionId)) {
    return "pending";
  }
  return node.status;
}

function mergeRuntimeListStatuses(runtimeById: Record<string, CanvasRuntimeNodeState>, groups: Array<[string[], string]>, statusSource?: string) {
  const result = { ...runtimeById };
  groups.forEach(([nodeIds, status]) => {
    nodeIds.forEach((nodeId) => {
      const previous = result[nodeId];
      if (previous?.status && runtimeStatusSource(previous) === "execution") return;
      result[nodeId] = {
        ...previous,
        node_id: nodeId,
        status,
        status_source: statusSource ?? previous?.status_source ?? null,
      };
    });
  });
  return result;
}

function normalizeNodeRuntimeMap(value: unknown) {
  const result: Record<string, CanvasRuntimeNodeState> = {};
  if (Array.isArray(value)) {
    value.forEach((item) => {
      const node = normalizeNodeRuntimeState(item);
      if (node) result[node.node_id] = node;
    });
    return result;
  }
  const record = objectRecord(value);
  Object.entries(record).forEach(([key, item]) => {
    const node = normalizeNodeRuntimeState(item, key);
    if (node) result[node.node_id] = node;
  });
  return result;
}

function normalizeNodeRuntimeState(value: unknown, fallbackNodeId = ""): CanvasRuntimeNodeState | null {
  const record = objectRecord(value);
  const nodeId = firstString(record.node_id, record.id, fallbackNodeId);
  const status = firstString(record.status);
  if (!nodeId || !status) return null;
  return {
    node_id: nodeId,
    node_type: firstString(record.node_type, record.type) ?? null,
    status,
    status_source: firstString(record.status_source, record.statusSource, objectRecord(record.metadata).status_source, objectRecord(record.metadata).statusSource) ?? null,
    execution_id: firstString(record.execution_id) ?? null,
    node_run_id: firstString(record.node_run_id) ?? null,
    waiting_reason: firstString(record.waiting_reason) ?? null,
    error: firstString(record.error) ?? null,
    updated_at: firstString(record.updated_at, record.created_at) ?? null,
    metadata: objectRecord(record.metadata),
  };
}

function isNodeStatusEvent(type: string) {
  return [
    "node_status_changed",
    "node_started",
    "node_waiting",
    "node_failed",
    "node_completed",
    "node_queued",
    "node_running",
    "node_skipped",
    "node_cancelled",
    "node_blocked",
  ].includes(type);
}

function statusFromEvent(event: CanvasRuntimeEvent) {
  if (event.status) return event.status;
  if (event.event_type === "node_started" || event.event_type === "node_running") return "running";
  if (event.event_type === "node_waiting") return "waiting";
  if (event.event_type === "node_failed") return "failed";
  if (event.event_type === "node_completed") return "completed";
  if (event.event_type === "node_queued") return "queued";
  if (event.event_type === "node_skipped") return "skipped";
  if (event.event_type === "node_cancelled") return "cancelled";
  if (event.event_type === "node_blocked") return "blocked";
  return null;
}

function nodeIdsByStatus(nodes: Record<string, CanvasRuntimeNodeState>, statuses: string[]) {
  const expected = new Set(statuses);
  return Object.entries(nodes)
    .filter(([, node]) => expected.has(normalizeStatus(node.status)))
    .map(([nodeId]) => nodeId);
}

function nodeIdsByRuntimeStatus(nodes: Record<string, CanvasRuntimeNodeState>, statuses: string[], activeExecutionId?: string | null) {
  const expected = new Set(statuses);
  return Object.entries(nodes)
    .filter(([, node]) => expected.has(normalizeStatus(node.status)) && isRuntimeExecutingNode(node, activeExecutionId))
    .map(([nodeId]) => nodeId);
}

function workflowGraphFromUnknown(value: unknown): WorkflowGraph | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Partial<WorkflowGraph>;
  return record.workflow_id && Array.isArray(record.nodes) ? record as WorkflowGraph : null;
}

function mediaStatusFromUnknown(value: unknown): MediaStatus | null {
  return value && typeof value === "object" ? value as MediaStatus : null;
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function numberFromUnknown(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return 0;
}

function nullableNumberFromUnknown(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return null;
}

function uniqueStrings(values: unknown) {
  const raw = Array.isArray(values) ? values : [];
  const seen = new Set<string>();
  const result: string[] = [];
  raw.forEach((value) => {
    const text = firstString(value);
    if (!text || seen.has(text)) return;
    seen.add(text);
    result.push(text);
  });
  return result;
}

function normalizeStatus(value?: string | null) {
  return value?.trim().toLowerCase() ?? "";
}

function runtimeStatusSource(node: CanvasRuntimeNodeState) {
  return normalizeStatus(node.status_source ?? firstString(objectRecord(node.metadata).status_source));
}

function candidateRefreshValues(value: unknown): CanvasRuntimeCandidateRefresh[] {
  const allowed = new Set<CanvasRuntimeCandidateRefresh>([
    "revision",
    "revisions",
    "asset_history",
    "candidate_summary",
    "node_assets",
    "workflow_graph",
    "resolved_inputs",
  ]);
  return uniqueStrings(value).filter((item): item is CanvasRuntimeCandidateRefresh => allowed.has(item as CanvasRuntimeCandidateRefresh));
}
