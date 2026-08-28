import { useEffect, useMemo, useRef, useState } from "react";

import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type { PresentationStreamEventV1 } from "../../../types-v2.ts";
import { normalizePresentationStreamEventV1 } from "../model/normalizers.ts";

export const PRESENTATION_STREAM_EVENT_TYPES: readonly PresentationStreamEventV1["event_type"][] = [
  "started",
  "delta",
  "committed",
  "failed",
  "superseded",
  "reset",
  "heartbeat",
];

export type PresentationStreamViewStatus =
  | "connecting"
  | "open"
  | "reconnecting"
  | "completed"
  | "failed"
  | "superseded";

export interface PresentationStreamView {
  stream_id: string;
  status: PresentationStreamViewStatus;
  text: string;
  last_sequence_no: number;
  stream_kind: PresentationStreamEventV1["stream_kind"] | null;
  turn_id: string | null;
  node_id: string | null;
  authoritative_id: string | null;
  error_code: string | null;
  protocol_error: string | null;
  last_event_type: PresentationStreamEventV1["event_type"] | null;
  last_event: PresentationStreamEventV1 | null;
}

function initialView(streamId: string): PresentationStreamView {
  return {
    stream_id: streamId,
    status: "connecting",
    text: "",
    last_sequence_no: 0,
    stream_kind: null,
    turn_id: null,
    node_id: null,
    authoritative_id: null,
    error_code: null,
    protocol_error: null,
    last_event_type: null,
    last_event: null,
  };
}

function statusForEvent(eventType: PresentationStreamEventV1["event_type"]): PresentationStreamViewStatus {
  if (eventType === "committed") return "completed";
  if (eventType === "failed") return "failed";
  if (eventType === "superseded") return "superseded";
  return "open";
}

function isTerminalEvent(eventType: PresentationStreamEventV1["event_type"]): boolean {
  return eventType === "committed" || eventType === "failed" || eventType === "superseded";
}

export function useAgentCanvasPresentationStreams(
  workflowId: string | null,
  streamIds: readonly string[],
): Record<string, PresentationStreamView> {
  const streamKey = useMemo(
    () => [...new Set(streamIds.filter((streamId) => Boolean(streamId)))].sort().join("\u0000"),
    [streamIds],
  );
  const [views, setViews] = useState<Record<string, PresentationStreamView>>({});
  const viewsRef = useRef(new Map<string, PresentationStreamView>());
  const workflowScopeRef = useRef<string | null>(null);

  useEffect(() => {
    const activeIds = streamKey ? streamKey.split("\u0000") : [];
    const activeIdSet = new Set(activeIds);
    if (workflowScopeRef.current !== workflowId) {
      viewsRef.current.clear();
      workflowScopeRef.current = workflowId;
    }
    for (const streamId of viewsRef.current.keys()) {
      if (!activeIdSet.has(streamId)) viewsRef.current.delete(streamId);
    }
    activeIds.forEach((streamId) => {
      if (!viewsRef.current.has(streamId)) viewsRef.current.set(streamId, initialView(streamId));
    });
    setViews(Object.fromEntries(activeIds.map((streamId) => [streamId, viewsRef.current.get(streamId)!])));

    if (!workflowId || !activeIds.length) return undefined;
    let cancelled = false;
    const subscriptions = new Map<string, {
      source: EventSource | null;
      reconnectTimer: number | null;
      finished: boolean;
    }>();

    const updateView = (
      streamId: string,
      update: (current: PresentationStreamView) => PresentationStreamView,
    ) => {
      const previous = viewsRef.current.get(streamId) ?? initialView(streamId);
      const nextView = update(previous);
      viewsRef.current.set(streamId, nextView);
      setViews((current) => ({ ...current, [streamId]: nextView }));
    };

    const scheduleReconnect = (streamId: string, attempt: number) => {
      const subscription = subscriptions.get(streamId);
      if (!subscription || cancelled || subscription.finished) return;
      updateView(streamId, (current) => ({ ...current, status: "reconnecting" }));
      const delay = Math.min(
        1_000 * (2 ** Math.min(Math.max(attempt - 1, 0), 4)),
        12_000,
      );
      subscription.reconnectTimer = window.setTimeout(() => {
        subscription.reconnectTimer = null;
        connect(streamId, attempt + 1);
      }, delay);
    };

    const connect = (streamId: string, attempt: number) => {
      const subscription = subscriptions.get(streamId);
      if (!subscription || cancelled || subscription.finished) return;
      const current = viewsRef.current.get(streamId) ?? initialView(streamId);
      updateView(streamId, (view) => ({
        ...view,
        status: attempt > 0 ? "reconnecting" : "connecting",
        protocol_error: null,
      }));
      try {
        const source = agentCanvasApi.openAgentCanvasPresentationStream(
          workflowId,
          streamId,
          current.last_sequence_no,
        );
        subscription.source = source;
        const handleMessage = (message: MessageEvent<string>) => {
          if (cancelled || subscription.finished) return;
          let event: PresentationStreamEventV1;
          try {
            event = normalizePresentationStreamEventV1(JSON.parse(message.data));
          } catch (error) {
            updateView(streamId, (view) => ({
              ...view,
              protocol_error: error instanceof Error ? error.message : "Invalid presentation stream event.",
            }));
            subscription.finished = true;
            source.close();
            return;
          }
          if (event.workflow_id !== workflowId || event.stream_id !== streamId) {
            updateView(streamId, (view) => ({
              ...view,
              protocol_error: "Presentation stream identity did not match the requested workflow.",
            }));
            subscription.finished = true;
            source.close();
            return;
          }
          const previous = viewsRef.current.get(streamId) ?? initialView(streamId);
          if (event.sequence_no <= previous.last_sequence_no) return;
          const terminal = isTerminalEvent(event.event_type);
          updateView(streamId, (view) => ({
            ...view,
            status: statusForEvent(event.event_type),
            text: event.event_type === "reset"
              ? ""
              : event.event_type === "delta"
                ? `${view.text}${event.delta ?? ""}`
                : view.text,
            last_sequence_no: event.sequence_no,
            stream_kind: event.stream_kind,
            turn_id: event.turn_id,
            node_id: event.node_id,
            authoritative_id: event.authoritative_id,
            error_code: event.error_code,
            last_event_type: event.event_type,
            last_event: event,
          }));
          if (terminal) {
            subscription.finished = true;
            source.close();
          }
        };
        source.onmessage = handleMessage;
        PRESENTATION_STREAM_EVENT_TYPES.forEach((eventType) => {
          source.addEventListener(eventType, handleMessage as EventListener);
        });
        source.onopen = () => {
          updateView(streamId, (view) => ({ ...view, status: "open" }));
        };
        source.onerror = () => {
          if (cancelled || subscription.finished) return;
          source.close();
          subscription.source = null;
          scheduleReconnect(streamId, attempt + 1);
        };
      } catch {
        scheduleReconnect(streamId, attempt + 1);
      }
    };

    activeIds.forEach((streamId) => {
      subscriptions.set(streamId, { source: null, reconnectTimer: null, finished: false });
      connect(streamId, 0);
    });

    return () => {
      cancelled = true;
      subscriptions.forEach((subscription) => {
        subscription.finished = true;
        if (subscription.reconnectTimer !== null) window.clearTimeout(subscription.reconnectTimer);
        subscription.source?.close();
      });
    };
  }, [streamKey, workflowId]);

  return views;
}
