import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import { normalizeWorkflowRuntimeEventV2 } from "../../../api/v2Normalizers.ts";
import type { WorkflowRuntimeEventV2, WorkflowRuntimeV2 } from "../../../types-v2.ts";
import { createRuntimeEventBatcher } from "../../../workflow-v2/runtimeBatch.ts";
import { createV2RuntimeSnapshotCoordinator } from "./v2RuntimeSnapshotCoordinator.ts";
import { V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES } from "./v2RuntimeEventModel.ts";
import {
  applyV2RuntimeSnapshot,
  createInitialV2RuntimeStore,
  reduceV2RuntimeEvent,
  type V2ConnectionState,
  type V2RuntimeStore,
} from "../../../workflow-v2/runtime.ts";

export const V2_RUNTIME_EVENT_STREAM_TYPES = [
  "execution_queued",
  "execution_started",
  "execution_waiting",
  "execution_completed",
  "execution_partial_failed",
  "execution_failed",
  "execution_cancelled",
  "slot_queued",
  "slot_generation_started",
  "slot_generation_waiting",
  "slot_generation_completed",
  "slot_generation_failed",
  "slot_blocked",
  "slot_skipped",
  "provider_execution_started",
  "provider_execution_waiting",
  "provider_execution_completed",
  "provider_execution_failed",
  "provider_task_submitted",
  "provider_task_waiting",
  "provider_task_completed",
  "provider_task_failed",
  "provider_task_cancelled",
  "provider_task_expired",
  "provider_task_polled",
  "asset_version_created",
  "slot_working_version_created",
  "slot_working_version_updated",
  "slot_working_version_discarded",
  "item_working_version_updated",
  "slot_selected_version_updated",
  "runtime_snapshot_updated",
  "node_assets_updated",
  "graph_updated",
  "prompt_updated",
  "item_prompt_updated",
  "slot_prompt_updated",
  "reference_attached",
  "reference_removed",
  "slot_history_updated",
  "asset_history_updated",
  "workflow_updated",
  "resolved_inputs_updated",
  "storyboard_summary_refined",
  "script_version_created",
  "script_selected_version_updated",
  "workflow_structure_updated",
  "linked_context_updated",
  "final_timeline_created",
  "final_timeline_updated",
  ...V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES,
] as const;

export function useV2RuntimeController(options: {
  workflowId?: string | null;
  runtime?: WorkflowRuntimeV2;
  enabled?: boolean;
  onEvents?: (workflowId: string, events: WorkflowRuntimeEventV2[]) => Promise<void> | void;
  onSnapshot?: (workflowId: string, runtime: WorkflowRuntimeV2) => Promise<void> | void;
} = {}) {
  const enabled = options.enabled ?? true;
  const [runtime, setRuntime] = useState<WorkflowRuntimeV2 | undefined>(undefined);
  const [store, setStore] = useState<V2RuntimeStore>(() => createInitialV2RuntimeStore());
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollingTimerRef = useRef<number | null>(null);
  const workflowIdRef = useRef<string | null>(options.workflowId ?? null);
  const lifecycleGenerationRef = useRef(0);
  const storeRef = useRef<V2RuntimeStore>(createInitialV2RuntimeStore());
  const emptyPollCountRef = useRef(0);
  const snapshotCoordinatorRef = useRef<ReturnType<typeof createV2RuntimeSnapshotCoordinator<WorkflowRuntimeV2>> | null>(null);
  const eventBatcherRef = useRef<ReturnType<typeof createRuntimeEventBatcher<WorkflowRuntimeEventV2>> | null>(null);
  if (!snapshotCoordinatorRef.current) {
    snapshotCoordinatorRef.current = createV2RuntimeSnapshotCoordinator<WorkflowRuntimeV2>();
  }
  const callbacksRef = useRef({
    onEvents: options.onEvents,
    onSnapshot: options.onSnapshot,
  });
  callbacksRef.current = {
    onEvents: options.onEvents,
    onSnapshot: options.onSnapshot,
  };

  useEffect(() => {
    storeRef.current = store;
  }, [store]);

  const runningSlotIds = useMemo(() => new Set(store.runningSlotIds), [store.runningSlotIds]);
  const waitingSlotIds = useMemo(() => new Set(store.waitingSlotIds), [store.waitingSlotIds]);
  const runningNodeIds = useMemo(() => new Set(store.runningNodeIds), [store.runningNodeIds]);
  const waitingNodeIds = useMemo(() => new Set(store.waitingNodeIds), [store.waitingNodeIds]);
  const connectionState: V2ConnectionState = store.connectionState;

  const stop = useCallback(() => {
    lifecycleGenerationRef.current += 1;
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    eventBatcherRef.current?.clear();
    if (pollingTimerRef.current) {
      window.clearTimeout(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  }, []);

  const applySnapshot = useCallback(async (workflowId: string, snapshot: WorkflowRuntimeV2) => {
    if (workflowIdRef.current !== workflowId) return snapshot;
    setRuntime(snapshot);
    setStore((current) => applyV2RuntimeSnapshot(current, snapshot));
    await callbacksRef.current.onSnapshot?.(workflowId, snapshot);
    return snapshot;
  }, []);

  const syncSnapshot = useCallback(async (workflowId: string, options: { queueRefresh?: boolean } = {}) => {
    try {
      return await snapshotCoordinatorRef.current!.request(workflowId, async () => {
        const snapshot = await v2Api.runtime(workflowId);
        return applySnapshot(workflowId, snapshot);
      }, options);
    } catch {
      if (workflowIdRef.current === workflowId) {
        setStore((current) => ({ ...current, connectionState: "degraded_polling" }));
      }
      return undefined;
    }
  }, [applySnapshot]);

  if (!eventBatcherRef.current) {
    eventBatcherRef.current = createRuntimeEventBatcher<WorkflowRuntimeEventV2>((events) => {
      const workflowId = workflowIdRef.current;
      if (!workflowId) return;
      setStore((current) => events.reduce(reduceV2RuntimeEvent, current));
      void callbacksRef.current.onEvents?.(workflowId, events);
      if (events.some((event) => event.event_type === "runtime_snapshot_updated")) void syncSnapshot(workflowId);
    });
  }

  const syncEvents = useCallback(async (workflowId: string) => {
    try {
      const afterSeq = storeRef.current.lastEventSeq;
      const response = await v2Api.events(workflowId, afterSeq);
      if (workflowIdRef.current !== workflowId) return;
      if (response.events.length) {
        emptyPollCountRef.current = 0;
        setStore((current) => response.events.reduce(reduceV2RuntimeEvent, current));
        await callbacksRef.current.onEvents?.(workflowId, response.events);
        if (response.events.some((event) => event.event_type === "runtime_snapshot_updated")) {
          await syncSnapshot(workflowId);
        }
      } else {
        emptyPollCountRef.current += 1;
        if (emptyPollCountRef.current >= 3) {
          emptyPollCountRef.current = 0;
          await syncSnapshot(workflowId);
        }
      }
      setStore((current) => ({ ...current, lastEventSeq: Math.max(current.lastEventSeq, response.next_after_seq), connectionState: "degraded_polling" }));
    } catch {
      if (workflowIdRef.current === workflowId) {
        setStore((current) => ({ ...current, connectionState: "degraded_polling" }));
      }
    }
  }, [syncSnapshot]);

  const startPolling = useCallback((workflowId: string, lifecycleGeneration = lifecycleGenerationRef.current) => {
    if (lifecycleGenerationRef.current !== lifecycleGeneration) return;
    if (pollingTimerRef.current) window.clearTimeout(pollingTimerRef.current);
    setStore((current) => ({ ...current, connectionState: "degraded_polling" }));
    const scheduleNextPoll = () => {
      pollingTimerRef.current = window.setTimeout(() => {
        void syncEvents(workflowId).catch(() => {
          setStore((current) => ({ ...current, connectionState: "degraded_polling" }));
        }).finally(() => {
          if (
            lifecycleGenerationRef.current === lifecycleGeneration
            && workflowIdRef.current === workflowId
            && !eventSourceRef.current
          ) scheduleNextPoll();
        });
      }, 5000);
    };
    scheduleNextPoll();
  }, [syncEvents]);

  const start = useCallback((workflowId: string) => {
    if (!workflowId) return;
    stop();
    workflowIdRef.current = workflowId;
    const lifecycleGeneration = lifecycleGenerationRef.current;
    setStore((current) => ({ ...current, connectionState: "connecting" }));
    void syncSnapshot(workflowId, { queueRefresh: false })
      .then((snapshot) => {
        if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
        if (!snapshot) return;
        try {
          const stream = v2Api.openEventStream(workflowId, snapshot.events_cursor ?? 0);
          eventSourceRef.current = stream;
          stream.onopen = () => {
            if (lifecycleGenerationRef.current !== lifecycleGeneration || eventSourceRef.current !== stream) return;
            setStore((current) => ({ ...current, connectionState: "connected" }));
          };
          const handleStreamEvent = (event: Event) => {
            try {
              const parsed = normalizeWorkflowRuntimeEventV2(JSON.parse((event as MessageEvent).data));
              eventBatcherRef.current?.push(parsed);
            } catch {
              setStore((current) => ({ ...current, connectionState: "degraded_polling" }));
            }
          };
          stream.onmessage = handleStreamEvent;
          V2_RUNTIME_EVENT_STREAM_TYPES.forEach((eventType) => {
            stream.addEventListener(eventType, handleStreamEvent);
          });
          stream.onerror = () => {
            stream.close();
            if (lifecycleGenerationRef.current !== lifecycleGeneration || eventSourceRef.current !== stream) return;
            eventSourceRef.current = null;
            setStore((current) => ({ ...current, connectionState: "reconnecting" }));
            startPolling(workflowId, lifecycleGeneration);
          };
        } catch {
          if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
          startPolling(workflowId, lifecycleGeneration);
        }
      })
      .catch(() => {
        if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
        startPolling(workflowId, lifecycleGeneration);
      });
  }, [startPolling, stop, syncSnapshot]);

  const reset = useCallback(() => {
    stop();
    setRuntime(undefined);
    setStore(createInitialV2RuntimeStore());
    emptyPollCountRef.current = 0;
  }, [stop]);

  useEffect(() => {
    workflowIdRef.current = options.workflowId ?? null;
    if (!enabled || !options.workflowId) {
      reset();
      return;
    }
    start(options.workflowId);
    return stop;
  }, [enabled, options.workflowId, reset, start, stop]);

  return {
    runtime,
    store,
    connectionState,
    runningNodeIds,
    waitingNodeIds,
    runningSlotIds,
    waitingSlotIds,
    start,
    stop,
    reset,
    syncSnapshot,
    applySnapshot,
    syncEvents,
  };
}
