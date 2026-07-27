import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v2Api } from "../../../api/v2Client.ts";
import { normalizeWorkflowRuntimeEventV2 } from "../../../api/v2Normalizers.ts";
import type { WorkflowRuntimeEventV2, WorkflowRuntimeV2 } from "../../../types-v2.ts";
import { createRuntimeEventBatcher } from "../../../workflow-v2/runtimeBatch.ts";
import { createV2RuntimeSnapshotCoordinator } from "./v2RuntimeSnapshotCoordinator.ts";
import { V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES } from "./v2RuntimeEventModel.ts";
import { createRuntimeReconnectPolicy } from "./runtimeReconnectPolicy.ts";
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
  "workflow_revision_created",
  "execution_result_revision_deferred",
  "final_timeline_created",
  "final_timeline_updated",
  ...V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES,
] as const;

type RuntimeTransportActivation = {
  workflowId: string;
  lifecycleGeneration: number;
  promise: Promise<boolean>;
  settle: (active: boolean) => void;
};

function createRuntimeTransportActivation(
  workflowId: string,
  lifecycleGeneration: number,
): RuntimeTransportActivation {
  let settlePromise!: (active: boolean) => void;
  let settled = false;
  const promise = new Promise<boolean>((resolve) => {
    settlePromise = resolve;
  });
  return {
    workflowId,
    lifecycleGeneration,
    promise,
    settle(active) {
      if (settled) return;
      settled = true;
      settlePromise(active);
    },
  };
}

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
  const workflowIdRef = useRef<string | null>(options.workflowId ?? null);
  const lifecycleGenerationRef = useRef(0);
  const storeRef = useRef<V2RuntimeStore>(createInitialV2RuntimeStore());
  const eventCursorRef = useRef(0);
  const emptyPollCountRef = useRef(0);
  const snapshotCoordinatorRef = useRef<ReturnType<typeof createV2RuntimeSnapshotCoordinator<WorkflowRuntimeV2>> | null>(null);
  const eventBatcherRef = useRef<ReturnType<typeof createRuntimeEventBatcher<WorkflowRuntimeEventV2>> | null>(null);
  const transportRef = useRef<ReturnType<typeof createRuntimeReconnectPolicy> | null>(null);
  const transportActivationRef = useRef<RuntimeTransportActivation | null>(null);
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

  const applySnapshot = useCallback(async (workflowId: string, snapshot: WorkflowRuntimeV2, lifecycleGeneration = lifecycleGenerationRef.current) => {
    if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return snapshot;
    const latestEventCursor = Math.max(eventCursorRef.current, storeRef.current.lastEventSeq);
    if ((snapshot.events_cursor ?? 0) < latestEventCursor) return snapshot;
    eventCursorRef.current = Math.max(eventCursorRef.current, snapshot.events_cursor ?? 0);
    setRuntime((current) => lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId ? snapshot : current);
    setStore((current) => lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId ? applyV2RuntimeSnapshot(current, snapshot) : current);
    await callbacksRef.current.onSnapshot?.(workflowId, snapshot);
    return snapshot;
  }, []);

  const syncSnapshot = useCallback(async (workflowId: string, options: { queueRefresh?: boolean } = {}, lifecycleGeneration = lifecycleGenerationRef.current) => {
    try {
      return await snapshotCoordinatorRef.current!.request(workflowId, async () => {
        const snapshot = await v2Api.runtime(workflowId);
        return applySnapshot(workflowId, snapshot, lifecycleGeneration);
      }, options);
    } catch {
      if (lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId) {
        setStore((current) => lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId
          ? { ...current, connectionState: "degraded_polling" }
          : current);
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

  const pollEvents = useCallback(async (
    workflowId: string,
    lifecycleGeneration = lifecycleGenerationRef.current,
    signal?: AbortSignal,
  ) => {
    try {
      const afterSeq = Math.max(storeRef.current.lastEventSeq, eventCursorRef.current);
      const response = await v2Api.events(workflowId, afterSeq, signal);
      if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
      const responseCursor = Math.max(response.next_after_seq, ...response.events.map((event) => event.seq));
      eventCursorRef.current = Math.max(eventCursorRef.current, responseCursor);
      if (response.events.length) {
        emptyPollCountRef.current = 0;
        setStore((current) => lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId
          ? response.events.reduce(reduceV2RuntimeEvent, current)
          : current);
        await callbacksRef.current.onEvents?.(workflowId, response.events);
        if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
        if (response.events.some((event) => event.event_type === "runtime_snapshot_updated")) {
          await syncSnapshot(workflowId, {}, lifecycleGeneration);
        }
      } else {
        emptyPollCountRef.current += 1;
        if (emptyPollCountRef.current >= 3) {
          emptyPollCountRef.current = 0;
          await syncSnapshot(workflowId, {}, lifecycleGeneration);
        }
      }
      if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
      setStore((current) => lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId
        ? { ...current, lastEventSeq: Math.max(current.lastEventSeq, responseCursor), connectionState: "degraded_polling" }
        : current);
    } catch {
      if (signal?.aborted) return;
      if (lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId) {
        setStore((current) => lifecycleGenerationRef.current === lifecycleGeneration && workflowIdRef.current === workflowId
          ? { ...current, connectionState: "degraded_polling" }
          : current);
      }
    }
  }, [syncSnapshot]);

  const openEventStream = useCallback((workflowId: string, transportGeneration: number, lifecycleGeneration = lifecycleGenerationRef.current) => {
    if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
    eventSourceRef.current?.close();
    const stream = v2Api.openEventStream(workflowId, eventCursorRef.current);
    eventSourceRef.current = stream;
    stream.onopen = () => {
      if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId || eventSourceRef.current !== stream) return;
      transportRef.current?.sseOpened(transportGeneration);
    };
    const handleStreamEvent = (event: Event) => {
      if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId || eventSourceRef.current !== stream) return;
      try {
        const parsed = normalizeWorkflowRuntimeEventV2(JSON.parse((event as MessageEvent).data));
        eventCursorRef.current = Math.max(eventCursorRef.current, parsed.seq);
        eventBatcherRef.current?.push(parsed);
        transportRef.current?.sseHealthyEvent(transportGeneration);
      } catch {
        stream.close();
        if (eventSourceRef.current !== stream) return;
        eventSourceRef.current = null;
        transportRef.current?.sseFailed(transportGeneration);
      }
    };
    stream.onmessage = handleStreamEvent;
    V2_RUNTIME_EVENT_STREAM_TYPES.forEach((eventType) => {
      stream.addEventListener(eventType, handleStreamEvent);
    });
    stream.onerror = () => {
      stream.close();
      if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId || eventSourceRef.current !== stream) return;
      eventSourceRef.current = null;
      transportRef.current?.sseFailed(transportGeneration);
    };
  }, []);

  if (!transportRef.current) {
    transportRef.current = createRuntimeReconnectPolicy({
      isEligible: () => document.visibilityState !== "hidden" && navigator.onLine !== false,
      onConnect: (transportGeneration) => {
        const workflowId = workflowIdRef.current;
        const lifecycleGeneration = lifecycleGenerationRef.current;
        if (workflowId) openEventStream(workflowId, transportGeneration, lifecycleGeneration);
      },
      onDisconnect: () => {
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
      },
      onPoll: async (_transportGeneration, signal) => {
        const workflowId = workflowIdRef.current;
        const lifecycleGeneration = lifecycleGenerationRef.current;
        if (workflowId) await pollEvents(workflowId, lifecycleGeneration, signal);
      },
      onStateChange: (state) => {
        const connectionState: V2ConnectionState = state === "idle" ? "disconnected" : state;
        setStore((current) => ({ ...current, connectionState }));
      },
    });
  }

  const syncEvents = useCallback(async (workflowId: string) => {
    const lifecycleGeneration = lifecycleGenerationRef.current;
    if (workflowIdRef.current !== workflowId) return;
    const activation = transportActivationRef.current;
    if (
      activation
      && activation.workflowId === workflowId
      && activation.lifecycleGeneration === lifecycleGeneration
    ) {
      const active = await activation.promise;
      if (!active) return;
    }
    if (lifecycleGenerationRef.current !== lifecycleGeneration || workflowIdRef.current !== workflowId) return;
    await transportRef.current?.synchronize();
  }, []);

  const stop = useCallback(() => {
    lifecycleGenerationRef.current += 1;
    const activation = transportActivationRef.current;
    transportActivationRef.current = null;
    activation?.settle(false);
    transportRef.current?.stop();
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    eventBatcherRef.current?.clear();
    snapshotCoordinatorRef.current?.clear();
  }, []);

  const resetWorkflowScopedState = useCallback((connectionState: V2ConnectionState = "disconnected") => {
    const initial = createInitialV2RuntimeStore();
    const next = { ...initial, connectionState };
    setRuntime(undefined);
    storeRef.current = next;
    setStore(next);
    eventCursorRef.current = 0;
    emptyPollCountRef.current = 0;
    eventBatcherRef.current?.clear();
    snapshotCoordinatorRef.current?.clear();
  }, []);

  const start = useCallback((workflowId: string) => {
    if (!workflowId) return;
    stop();
    workflowIdRef.current = workflowId;
    const lifecycleGeneration = lifecycleGenerationRef.current;
    const activation = createRuntimeTransportActivation(workflowId, lifecycleGeneration);
    transportActivationRef.current = activation;
    resetWorkflowScopedState("connecting");
    const activateTransport = () => {
      if (
        lifecycleGenerationRef.current !== lifecycleGeneration
        || workflowIdRef.current !== workflowId
        || transportActivationRef.current !== activation
      ) {
        activation.settle(false);
        return;
      }
      transportRef.current?.start();
      activation.settle(true);
    };
    void syncSnapshot(workflowId, { queueRefresh: false }, lifecycleGeneration)
      .then(activateTransport)
      .catch(activateTransport);
  }, [resetWorkflowScopedState, stop, syncSnapshot]);

  const reset = useCallback(() => {
    stop();
    resetWorkflowScopedState();
  }, [resetWorkflowScopedState, stop]);

  useEffect(() => {
    const reconcileTransport = () => {
      if (document.visibilityState === "hidden" || navigator.onLine === false) {
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
      }
      transportRef.current?.reconcile();
    };
    document.addEventListener("visibilitychange", reconcileTransport);
    window.addEventListener("online", reconcileTransport);
    window.addEventListener("offline", reconcileTransport);
    return () => {
      document.removeEventListener("visibilitychange", reconcileTransport);
      window.removeEventListener("online", reconcileTransport);
      window.removeEventListener("offline", reconcileTransport);
    };
  }, []);

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
