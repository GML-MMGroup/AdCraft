import { useCallback, useEffect, useMemo, useRef, type RefObject } from "react";
import { api } from "../../../api/client.ts";
import { normalizeCanvasRuntimeEvent, type CanvasRuntimeConnectionState, type CanvasRuntimeEvent, type CanvasRuntimeSnapshot } from "../../../workflow/canvasRuntime.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";

export type UseCanvasRuntimeSubscriptionArgs = {
  localWorkflowId: string;
  activeWorkflowIdRef: RefObject<string | null>;
  onConnectionState: (state: CanvasRuntimeConnectionState) => void;
  onSnapshot: (snapshot: CanvasRuntimeSnapshot) => void | Promise<void>;
  onEvent: (workflowId: string, event: CanvasRuntimeEvent) => void | Promise<void>;
};

export function useCanvasRuntimeSubscription({
  localWorkflowId,
  activeWorkflowIdRef,
  onConnectionState,
  onSnapshot,
  onEvent,
}: UseCanvasRuntimeSubscriptionArgs) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const lastEventSeqRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);
  const callbacksRef = useRef({ onConnectionState, onSnapshot, onEvent });

  useEffect(() => {
    callbacksRef.current = { onConnectionState, onSnapshot, onEvent };
  }, [onConnectionState, onSnapshot, onEvent]);

  const isActive = useCallback(
    (workflowId: string) => shouldApplyWorkflowScopedResult(workflowId, activeWorkflowIdRef.current),
    [activeWorkflowIdRef],
  );

  const stopTransport = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    stopTransport();
    lastEventSeqRef.current = 0;
    reconnectAttemptsRef.current = 0;
    callbacksRef.current.onConnectionState("disconnected");
  }, [stopTransport]);

  const pollEvents = useCallback(async (workflowId: string) => {
    try {
      const response = await api.canvasEvents(workflowId, lastEventSeqRef.current);
      if (!isActive(workflowId)) return;
      if (!response) {
        const snapshot = await api.canvasRuntime(workflowId);
        if (snapshot && isActive(workflowId)) {
          lastEventSeqRef.current = Math.max(lastEventSeqRef.current, snapshot.lastEventSeq);
          await callbacksRef.current.onSnapshot(snapshot);
        }
        return;
      }
      for (const event of response.events) {
        lastEventSeqRef.current = Math.max(lastEventSeqRef.current, event.event_seq);
        await callbacksRef.current.onEvent(workflowId, event);
      }
      lastEventSeqRef.current = Math.max(lastEventSeqRef.current, response.next_after_seq);
    } catch {
      if (!isActive(workflowId)) return;
      callbacksRef.current.onConnectionState("degraded_polling");
    }
  }, [isActive]);

  const startDegradedPolling = useCallback((workflowId: string) => {
    if (!isActive(workflowId)) return;
    callbacksRef.current.onConnectionState("degraded_polling");
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (pollTimerRef.current) window.clearInterval(pollTimerRef.current);
    void pollEvents(workflowId);
    pollTimerRef.current = window.setInterval(() => {
      void pollEvents(workflowId);
    }, 5000);
  }, [isActive, pollEvents]);

  const connectEventStream = useCallback((workflowId: string) => {
    if (typeof EventSource === "undefined") {
      startDegradedPolling(workflowId);
      return;
    }
    if (eventSourceRef.current) eventSourceRef.current.close();
    try {
      const stream = api.openCanvasEventStream(workflowId, lastEventSeqRef.current);
      eventSourceRef.current = stream;
      stream.onopen = () => {
        if (!isActive(workflowId)) return;
        reconnectAttemptsRef.current = 0;
        callbacksRef.current.onConnectionState("connected");
      };
      stream.onmessage = (message) => {
        if (!isActive(workflowId)) return;
        try {
          const event = normalizeCanvasRuntimeEvent(JSON.parse(message.data));
          lastEventSeqRef.current = Math.max(lastEventSeqRef.current, event.event_seq);
          void callbacksRef.current.onEvent(workflowId, event);
        } catch {
          // Ignore malformed runtime events and wait for the next snapshot/event.
        }
      };
      stream.onerror = () => {
        if (!isActive(workflowId)) return;
        callbacksRef.current.onConnectionState("reconnecting");
        stream.close();
        eventSourceRef.current = null;
        reconnectAttemptsRef.current += 1;
        if (reconnectAttemptsRef.current <= 3) {
          if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = window.setTimeout(() => connectEventStream(workflowId), 1400);
          return;
        }
        startDegradedPolling(workflowId);
      };
    } catch {
      startDegradedPolling(workflowId);
    }
  }, [isActive, startDegradedPolling]);

  const loadSnapshot = useCallback(async (workflowId: string) => {
    try {
      const snapshot = await api.canvasRuntime(workflowId);
      if (!isActive(workflowId)) return;
      if (!snapshot) {
        startDegradedPolling(workflowId);
        return;
      }
      lastEventSeqRef.current = Math.max(lastEventSeqRef.current, snapshot.lastEventSeq);
      await callbacksRef.current.onSnapshot(snapshot);
      connectEventStream(workflowId);
    } catch {
      if (!isActive(workflowId)) return;
      startDegradedPolling(workflowId);
    }
  }, [connectEventStream, isActive, startDegradedPolling]);

  const start = useCallback((workflowId: string) => {
    if (!workflowId || workflowId === localWorkflowId) return;
    stopTransport();
    callbacksRef.current.onConnectionState("connecting");
    lastEventSeqRef.current = 0;
    reconnectAttemptsRef.current = 0;
    void loadSnapshot(workflowId);
  }, [loadSnapshot, localWorkflowId, stopTransport]);

  useEffect(() => stop, [stop]);

  return useMemo(
    () => ({
      start,
      stop,
      loadSnapshot,
    }),
    [loadSnapshot, start, stop],
  );
}
