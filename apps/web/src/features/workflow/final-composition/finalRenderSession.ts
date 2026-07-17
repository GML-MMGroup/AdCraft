import type {
  V2FinalCompositionTimeline,
  V2FinalTimelineRenderStateResponse,
  WorkflowRuntimeEventV2,
} from "../../../types-v2.ts";
import type { TimelineSessionToken } from "./shotTimelineHistory.ts";

const FINAL_RENDER_POLL_DELAYS = [500, 1000, 2000, 3000, 5000] as const;
const FINAL_RENDER_ACTIVE_STATUSES = new Set<V2FinalTimelineRenderStateResponse["status"]>([
  "queued",
  "running",
  "cancellation_requested",
]);
const FINAL_RENDER_TERMINAL_STATUSES = new Set<V2FinalTimelineRenderStateResponse["status"]>([
  "completed",
  "failed",
  "cancelled",
]);
const FINAL_RENDER_TRANSIENT_EVENT_TYPES = new Set([
  "final_composition_render_queued",
  "final_composition_render_started",
  "final_composition_render_progress",
]);
const FINAL_RENDER_TERMINAL_EVENT_TYPES = new Set([
  "final_composition_render_completed",
  "final_composition_render_failed",
  "final_composition_render_cancelled",
]);

export type FinalRenderSessionIdentity = {
  session: TimelineSessionToken;
  renderGeneration: number;
  renderId: string;
};

export type FinalCompositionEventDetail = {
  workflowId?: string;
  eventTypes?: string[];
  events?: WorkflowRuntimeEventV2[];
};

export type FinalRenderEventHint = {
  eventType: string;
  kind: "fast-state" | "authoritative-get";
  renderId: string;
  status?: V2FinalTimelineRenderStateResponse["status"];
  progressSeconds?: number;
  totalSeconds?: number;
  progressPercent?: number;
  resetBackoff: boolean;
};

export function isFinalRenderActive(status: V2FinalTimelineRenderStateResponse["status"] | string) {
  return FINAL_RENDER_ACTIVE_STATUSES.has(status as V2FinalTimelineRenderStateResponse["status"]);
}

export function isFinalRenderTerminal(status: V2FinalTimelineRenderStateResponse["status"] | string) {
  return FINAL_RENDER_TERMINAL_STATUSES.has(status as V2FinalTimelineRenderStateResponse["status"]);
}

export function shouldRetryFinalRenderGet(status: number | null) {
  return status === null || status === 408 || status === 429 || status >= 500;
}

export function finalRenderGetFailureAction(status: number | null) {
  return shouldRetryFinalRenderGet(status) ? "retry" as const : "terminate" as const;
}

export function finalRenderCancelAction(status: V2FinalTimelineRenderStateResponse["status"]) {
  if (status === "cancellation_requested") return "poll" as const;
  if (isFinalRenderTerminal(status)) return "terminal" as const;
  return "request" as const;
}

export function nextFinalRenderPoll(backoffIndex: number, reset = false) {
  const index = reset
    ? 0
    : Math.min(Math.max(0, Math.floor(backoffIndex)), FINAL_RENDER_POLL_DELAYS.length - 1);
  return {
    delayMs: FINAL_RENDER_POLL_DELAYS[index],
    nextBackoffIndex: Math.min(index + 1, FINAL_RENDER_POLL_DELAYS.length - 1),
  };
}

export function finalRenderSessionMatches(
  current: FinalRenderSessionIdentity | null,
  candidate: FinalRenderSessionIdentity,
  active: boolean,
) {
  return Boolean(active
    && current
    && current.session.workflowId === candidate.session.workflowId
    && current.session.generation === candidate.session.generation
    && current.renderGeneration === candidate.renderGeneration
    && current.renderId === candidate.renderId);
}

export function finalRenderEventHints(
  detail: FinalCompositionEventDetail | null | undefined,
  expected: FinalRenderSessionIdentity,
  active: boolean,
): FinalRenderEventHint[] {
  if (!active || !expected.session.workflowId || detail?.workflowId !== expected.session.workflowId) return [];
  const hints: FinalRenderEventHint[] = [];
  for (const event of detail.events ?? []) {
    if (event.workflow_id !== expected.session.workflowId) continue;
    const renderId = stringValue(event.payload?.render_id);
    if (renderId !== expected.renderId) continue;
    if (FINAL_RENDER_TERMINAL_EVENT_TYPES.has(event.event_type)) {
      hints.push({
        eventType: event.event_type,
        kind: "authoritative-get",
        renderId,
        resetBackoff: false,
      });
      continue;
    }
    if (!FINAL_RENDER_TRANSIENT_EVENT_TYPES.has(event.event_type)) continue;
    const fallbackStatus = event.event_type === "final_composition_render_queued" ? "queued" : "running";
    const payloadStatus = stringValue(event.payload?.status);
    const status = payloadStatus && isFinalRenderActive(payloadStatus)
      ? payloadStatus as V2FinalTimelineRenderStateResponse["status"]
      : fallbackStatus;
    const hint: FinalRenderEventHint = {
      eventType: event.event_type,
      kind: "fast-state",
      renderId,
      status,
      resetBackoff: event.event_type === "final_composition_render_progress",
    };
    assignFiniteNumber(hint, "progressSeconds", event.payload?.progress_seconds);
    assignFiniteNumber(hint, "totalSeconds", event.payload?.total_seconds);
    assignFiniteNumber(hint, "progressPercent", event.payload?.progress_percent);
    hints.push(hint);
  }
  return hints;
}

export async function flushTimelineForRender<TTimeline extends V2FinalCompositionTimeline = V2FinalCompositionTimeline>({
  session,
  isSessionCurrent,
  finalizeGesture,
  readDraft,
  readBaseline,
  equals,
  hasConflict,
  save,
}: {
  session: TimelineSessionToken;
  isSessionCurrent: (session: TimelineSessionToken) => boolean;
  finalizeGesture: () => void;
  readDraft: () => TTimeline | null;
  readBaseline: () => TTimeline | null;
  equals: (left: TTimeline | null, right: TTimeline | null) => boolean;
  hasConflict: () => boolean;
  save: () => Promise<unknown | null>;
}): Promise<TTimeline | null> {
  finalizeGesture();
  while (isSessionCurrent(session) && !hasConflict()) {
    const draft = readDraft();
    const baseline = readBaseline();
    if (!draft || !baseline) return null;
    if (equals(draft, baseline)) return baseline;
    const saved = await save();
    if (saved === null || !isSessionCurrent(session) || hasConflict()) return null;
  }
  return null;
}

export function activeRenderIdFromPayload(payload: unknown) {
  const body = recordValue(payload);
  const detail = recordValue(body?.detail);
  if (detail?.code !== "v2_timeline_render_already_active") return null;
  return stringValue(detail.active_render_id);
}

export function claimFinalRenderCompletion(
  claimed: Set<string>,
  identity: FinalRenderSessionIdentity,
) {
  const key = [
    identity.session.workflowId,
    identity.session.generation,
    identity.renderGeneration,
    identity.renderId,
  ].join(":");
  if (claimed.has(key)) return false;
  claimed.add(key);
  return true;
}

function assignFiniteNumber(
  hint: FinalRenderEventHint,
  key: "progressSeconds" | "totalSeconds" | "progressPercent",
  value: unknown,
) {
  if (typeof value === "number" && Number.isFinite(value)) hint[key] = value;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value ? value : null;
}

function recordValue(value: unknown) {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}
