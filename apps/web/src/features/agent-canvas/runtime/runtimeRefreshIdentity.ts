import type {
  CanvasRuntimeEventV2,
  CanvasRuntimeSnapshotV2,
} from "../../../types-v2.ts";

const TERMINAL_RUNTIME_EVENTS = new Set([
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "execution_cancelled",
  "node_ready",
  "node_failed",
  "node_blocked",
  "node_skipped",
  "node_cancelled",
  "provider_task_completed",
  "provider_task_failed",
  "provider_result_download_completed",
  "provider_result_download_failed",
  "node_output_published",
  "execution_member_skipped_dependency",
  "runtime_snapshot_updated",
]);

export function isTerminalRuntimeEvent(eventType: string): boolean {
  return TERMINAL_RUNTIME_EVENTS.has(eventType);
}

const PRESENTATION_PAYLOAD_KEYS = new Set([
  "progress",
  "progress_percent",
  "status",
  "state",
  "phase",
  "waiting_reason",
  "queue_status",
  "download_status",
]);

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stableValue(item)]),
    );
  }
  return value;
}

function stableJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

function presentationPayload(payload: CanvasRuntimeEventV2["payload"]): unknown {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const entries = Object.entries(payload)
    .filter(([key]) => PRESENTATION_PAYLOAD_KEYS.has(key));
  return entries.length ? Object.fromEntries(entries) : null;
}

export function runtimeRefreshIdentity(event: CanvasRuntimeEventV2): string {
  return stableJson({
    workflow_id: event.workflow_id,
    execution_id: event.execution_id,
    node_id: event.node_id,
    event_type: event.event_type,
    attempt: event.attempt ?? null,
    payload: presentationPayload(event.payload),
    seq: TERMINAL_RUNTIME_EVENTS.has(event.event_type) ? event.seq : null,
  });
}

export function runtimeReflectsTerminalEvent(
  snapshot: CanvasRuntimeSnapshotV2,
  event: CanvasRuntimeEventV2,
): boolean {
  if (snapshot.events_cursor < event.seq) return false;
  if (!event.node_id) return true;
  const nodeRuntime = snapshot.node_runtime[event.node_id];
  if (event.event_type === "node_ready") {
    return snapshot.ready_node_ids.includes(event.node_id)
      || nodeRuntime?.visible_status === "ready";
  }
  if (event.event_type === "node_failed") {
    return snapshot.failed_node_ids.includes(event.node_id)
      || nodeRuntime?.visible_status === "failed";
  }
  return true;
}

export function sameRuntimePresentation(
  left: CanvasRuntimeSnapshotV2 | null,
  right: CanvasRuntimeSnapshotV2,
): boolean {
  if (!left) return false;
  const { events_cursor: _leftCursor, updated_at: _leftUpdatedAt, ...leftPresentation } = left;
  const { events_cursor: _rightCursor, updated_at: _rightUpdatedAt, ...rightPresentation } = right;
  return stableJson(leftPresentation) === stableJson(rightPresentation);
}
