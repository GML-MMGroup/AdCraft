import { useCallback, useEffect, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasNodeV2,
  CanvasNodePatchRequestV2,
  CanvasRuntimeEventV2,
  CanvasRuntimeModelResolutionV2,
  CanvasRuntimeSnapshotV2,
  ProviderInputManifestAuditV2,
  ProjectAssetSummaryV2,
  UpstreamInputReadinessIssueV2,
} from "../../../types-v2.ts";
import {
  normalizeCanvasRuntimeEventV2,
  normalizeProjectAssetSummaryV2,
} from "../model/normalizers.ts";
import { isSourceOnlyNode } from "../model/nodeExecutionMode.ts";
import { runnableDraftParameterMigrations } from "../model/providerModels.ts";
import { AGENT_CANVAS_SSE_EVENT_TYPES } from "./eventTypes.ts";
import {
  inputManifestAuditFromEvent,
  upstreamInputReadinessIssueFromDetails,
} from "./inputManifestAudit.ts";
import { resolvePublishedAssets } from "./publishedAssets.ts";
import { nodeRunRequest } from "./runRequest.ts";
import { modelResolutionFromEvent } from "./modelResolution.ts";
import { runtimeEventPolicy } from "./runtimeEventPolicy.ts";
import {
  runtimeRefreshIdentity,
  sameRuntimePresentation,
} from "./runtimeRefreshIdentity.ts";

type RuntimeCallbacks = {
  applyWorkflow: (workflow: AgentCanvasWorkflowV2) => void;
  mergePublishedAsset: (asset: ProjectAssetSummaryV2, nodeId?: string | null) => void;
  mergeNode: (node: CanvasNodeV2) => void;
};

type RuntimeNodePatcher = (
  nodeId: string,
  patch: CanvasNodePatchRequestV2,
) => Promise<void>;

export function useAgentCanvasRuntime(
  workflow: AgentCanvasWorkflowV2 | null,
  callbacks: RuntimeCallbacks,
  patchNode?: RuntimeNodePatcher,
) {
  const patchNodeRef = useRef(patchNode);
  patchNodeRef.current = patchNode;
  const [runtime, setRuntime] = useState<CanvasRuntimeSnapshotV2 | null>(null);
  const [connectionState, setConnectionState] = useState<"idle" | "connecting" | "live" | "reconnecting" | "unavailable">("idle");
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [runPending, setRunPending] = useState(false);
  const [chatRevision, setChatRevision] = useState(0);
  const [chatEvents, setChatEvents] = useState<CanvasRuntimeEventV2[]>([]);
  const [settingsRevision, setSettingsRevision] = useState(0);
  const [documentEvents, setDocumentEvents] = useState<CanvasRuntimeEventV2[]>([]);
  const [editingPreparationByNodeId, setEditingPreparationByNodeId] = useState<Record<
    string,
    { omittedNodeIds: string[]; manifestRevision: number | null }
  >>({});
  const [autoRunNotice, setAutoRunNotice] = useState<string | null>(null);
  const [inputManifestsByNodeId, setInputManifestsByNodeId] = useState<Record<string, ProviderInputManifestAuditV2>>({});
  const [modelResolutionsByNodeId, setModelResolutionsByNodeId] = useState<Record<string, CanvasRuntimeModelResolutionV2>>({});
  const [inputReadinessIssue, setInputReadinessIssue] = useState<UpstreamInputReadinessIssueV2 | null>(null);
  const cursorRef = useRef(0);
  const runtimeRefreshRef = useRef<Promise<void> | null>(null);
  const workflowRefreshRef = useRef<Promise<void> | null>(null);
  const assetsRefreshRef = useRef<Promise<void> | null>(null);
  const runtimeRefreshQueuedRef = useRef(false);
  const workflowRefreshQueuedRef = useRef(false);
  const assetsRefreshQueuedRef = useRef(false);
  const pendingAssetPublishesRef = useRef<Map<string, string | null>>(new Map());
  const seenTransitionKeysRef = useRef<Set<string>>(new Set());
  const lastRuntimeRefreshIdentityRef = useRef<string | null>(null);

  const workflowId = workflow?.workflow_id ?? null;
  const activeWorkflowIdRef = useRef<string | null>(workflowId);
  if (activeWorkflowIdRef.current !== workflowId) {
    activeWorkflowIdRef.current = workflowId;
    cursorRef.current = 0;
    runtimeRefreshRef.current = null;
    workflowRefreshRef.current = null;
    assetsRefreshRef.current = null;
    runtimeRefreshQueuedRef.current = false;
    workflowRefreshQueuedRef.current = false;
    assetsRefreshQueuedRef.current = false;
    pendingAssetPublishesRef.current.clear();
    seenTransitionKeysRef.current.clear();
    lastRuntimeRefreshIdentityRef.current = null;
  }

  useEffect(() => {
    setRuntime(null);
    setRuntimeError(null);
    setChatEvents([]);
    setChatRevision(0);
    setSettingsRevision(0);
    setDocumentEvents([]);
    setEditingPreparationByNodeId({});
    setAutoRunNotice(null);
    setInputManifestsByNodeId({});
    setModelResolutionsByNodeId({});
    setInputReadinessIssue(null);
  }, [workflowId]);

  const refreshRuntime = useCallback(async () => {
    if (!workflowId) return;
    if (runtimeRefreshRef.current) {
      runtimeRefreshQueuedRef.current = true;
      return runtimeRefreshRef.current;
    }
    const request = (async () => {
      do {
        runtimeRefreshQueuedRef.current = false;
        try {
          const next = await agentCanvasApi.agentCanvasRuntime(workflowId);
          if (activeWorkflowIdRef.current !== workflowId) return;
          setRuntime((current) => (
            sameRuntimePresentation(current, next) ? current : next
          ));
          setRuntimeError(null);
        } catch (error) {
          if (activeWorkflowIdRef.current !== workflowId) return;
          if (isV2ApiError(error) && [404, 405, 501].includes(error.status)) {
            setConnectionState("unavailable");
            setRuntimeError("Agent Canvas runtime requires the matching backend update.");
            return;
          }
          lastRuntimeRefreshIdentityRef.current = null;
          setRuntimeError(error instanceof Error ? error.message : "Runtime refresh failed.");
        }
      } while (
        runtimeRefreshQueuedRef.current
        && activeWorkflowIdRef.current === workflowId
      );
    })().finally(() => {
        if (runtimeRefreshRef.current === request) runtimeRefreshRef.current = null;
      });
    runtimeRefreshRef.current = request;
    return request;
  }, [workflowId]);

  const refreshWorkflow = useCallback(async () => {
    if (!workflowId) return;
    if (workflowRefreshRef.current) {
      workflowRefreshQueuedRef.current = true;
      return workflowRefreshRef.current;
    }
    const request = (async () => {
      do {
        workflowRefreshQueuedRef.current = false;
        try {
          const { value } = await agentCanvasApi.agentCanvasWorkflowWithEtag(workflowId);
          if (activeWorkflowIdRef.current === workflowId) callbacks.applyWorkflow(value);
        } catch (error) {
          if (activeWorkflowIdRef.current === workflowId) {
            setRuntimeError(error instanceof Error ? error.message : "Workflow refresh failed.");
          }
        }
      } while (
        workflowRefreshQueuedRef.current
        && activeWorkflowIdRef.current === workflowId
      );
    })().finally(() => {
        if (workflowRefreshRef.current === request) workflowRefreshRef.current = null;
      });
    workflowRefreshRef.current = request;
    return request;
  }, [callbacks, workflowId]);

  const refreshAssets = useCallback(async (event?: CanvasRuntimeEventV2) => {
    if (!workflowId) return;
    const published = event?.payload?.asset;
    if (published) {
      try {
        callbacks.mergePublishedAsset(
          normalizeProjectAssetSummaryV2(published),
          event?.node_id,
        );
        return;
      } catch {
        // Fall through to the canonical project asset list.
      }
    }
    const expectedAssetId = event?.asset_id
      ?? (typeof event?.payload?.asset_id === "string" ? event.payload.asset_id : null);
    if (!expectedAssetId) {
      await refreshWorkflow();
      return;
    }
    pendingAssetPublishesRef.current.set(expectedAssetId, event?.node_id ?? null);
    if (assetsRefreshRef.current) {
      assetsRefreshQueuedRef.current = true;
      return assetsRefreshRef.current;
    }
    const request = (async () => {
      do {
        assetsRefreshQueuedRef.current = false;
        try {
          const response = await agentCanvasApi.listAgentCanvasProjectAssets(workflowId);
          if (activeWorkflowIdRef.current !== workflowId) return;
          const pending = new Map(pendingAssetPublishesRef.current);
          pending.forEach((_nodeId, assetId) => pendingAssetPublishesRef.current.delete(assetId));
          const resolved = resolvePublishedAssets(response.assets, pending);
          resolved.matches.forEach(({ asset, nodeId }) => callbacks.mergePublishedAsset(asset, nodeId));
          if (resolved.unresolvedAssetIds.length) void refreshWorkflow();
        } catch (error) {
          if (activeWorkflowIdRef.current === workflowId) {
            setRuntimeError(error instanceof Error ? error.message : "Asset refresh failed.");
          }
        }
      } while (
        assetsRefreshQueuedRef.current
        && activeWorkflowIdRef.current === workflowId
      );
    })().finally(() => {
        if (assetsRefreshRef.current === request) assetsRefreshRef.current = null;
      });
    assetsRefreshRef.current = request;
    return request;
  }, [callbacks, refreshWorkflow, workflowId]);

  const processEvent = useCallback((event: CanvasRuntimeEventV2) => {
    if (event.seq <= cursorRef.current) return;
    cursorRef.current = event.seq;
    const transitionKey = event.transition_key;
    if (transitionKey) {
      if (seenTransitionKeysRef.current.has(transitionKey)) return;
      seenTransitionKeysRef.current.add(transitionKey);
      if (seenTransitionKeysRef.current.size > 500) {
        const oldest = seenTransitionKeysRef.current.values().next().value;
        if (typeof oldest === "string") seenTransitionKeysRef.current.delete(oldest);
      }
    }
    const inputManifest = inputManifestAuditFromEvent(event);
    if (inputManifest) {
      setInputManifestsByNodeId((current) => ({
        ...current,
        [inputManifest.node_id]: inputManifest,
      }));
    }
    const modelResolution = modelResolutionFromEvent(event);
    if (modelResolution) {
      setModelResolutionsByNodeId((current) => ({
        ...current,
        [modelResolution.node_id]: modelResolution,
      }));
    }
    const policy = runtimeEventPolicy(event);
    if (policy.refreshRuntime) {
      const refreshIdentity = runtimeRefreshIdentity(event);
      if (lastRuntimeRefreshIdentityRef.current !== refreshIdentity) {
        lastRuntimeRefreshIdentityRef.current = refreshIdentity;
        void refreshRuntime();
      }
    }
    if (policy.refreshWorkflow) void refreshWorkflow();
    if (policy.refreshAssets) void refreshAssets(event);
    if (policy.refreshChat) {
      setChatEvents((current) => [...current, event].slice(-100));
      setChatRevision((current) => current + 1);
    }
    if (policy.refreshSettings) setSettingsRevision((current) => current + 1);
    if (policy.refreshDocuments) {
      setDocumentEvents((current) => [...current, event].slice(-50));
    }
    if (event.event_type === "editing_prepared" || event.event_type === "guided_editing_ready") {
      const nodeId = event.node_id
        ?? (typeof event.payload?.editing_node_id === "string" ? event.payload.editing_node_id : null);
      if (nodeId) {
        const omittedNodeIds = Array.isArray(event.payload?.omitted_node_ids)
          ? event.payload.omitted_node_ids.filter((item): item is string => typeof item === "string")
          : [];
        const manifestRevision = typeof event.payload?.manifest_revision === "number"
          && Number.isInteger(event.payload.manifest_revision)
          ? event.payload.manifest_revision
          : null;
        setEditingPreparationByNodeId((current) => ({
          ...current,
          [nodeId]: { omittedNodeIds, manifestRevision },
        }));
      }
    }
    if (event.event_type === "agent_auto_run_failed") {
      setAutoRunNotice(
        "Automatic generation could not start. The Draft is still available; use the node Run action to retry.",
      );
    } else if (event.event_type === "agent_auto_run_submitted") {
      setAutoRunNotice(null);
    }
    const nodeId = policy.refreshEditingNodeId ?? policy.refreshNodeId;
    if (nodeId && workflowId) {
      void agentCanvasApi.agentCanvasNode(workflowId, nodeId)
        .then((node) => {
          if (activeWorkflowIdRef.current === workflowId) callbacks.mergeNode(node);
        })
        .catch(() => {});
    }
  }, [callbacks, refreshAssets, refreshRuntime, refreshWorkflow, workflowId]);

  useEffect(() => {
    if (!workflowId) {
      setRuntime(null);
      setConnectionState("idle");
      return undefined;
    }
    let cancelled = false;
    let eventSource: EventSource | null = null;
    let reconnectTimer = 0;
    let reconnectAttempt = 0;
    let currentConnectionId = 0;

    const handleMessage = (message: MessageEvent<string>) => {
      try {
        processEvent(normalizeCanvasRuntimeEventV2(JSON.parse(message.data)));
      } catch {
        void refreshRuntime();
      }
    };

    const replayEvents = async (
      afterSeq: number,
      isActive: () => boolean = () => !cancelled,
    ) => {
      let replayCursor = afterSeq;
      for (;;) {
        const replay = await agentCanvasApi.agentCanvasEvents(workflowId, replayCursor, 200);
        if (!isActive() || activeWorkflowIdRef.current !== workflowId) return;
        replay.events.forEach(processEvent);
        const nextCursor = Math.max(cursorRef.current, replay.next_cursor, replayCursor);
        cursorRef.current = nextCursor;
        if (replay.events.length < 200 || nextCursor <= replayCursor) return;
        replayCursor = nextCursor;
      }
    };

    const connect = async () => {
      if (cancelled) return;
      setConnectionState(reconnectAttempt ? "reconnecting" : "connecting");
      const connectionId = ++currentConnectionId;
      const isCurrentConnection = () => !cancelled && connectionId === currentConnectionId;
      const initialConnection = cursorRef.current === 0;
      try {
        if (initialConnection) {
          const baselineRuntime = await agentCanvasApi.agentCanvasRuntime(workflowId);
          if (cancelled || activeWorkflowIdRef.current !== workflowId) return;
          setRuntime((current) => (
            sameRuntimePresentation(current, baselineRuntime) ? current : baselineRuntime
          ));
          cursorRef.current = baselineRuntime.events_cursor;
          setRuntimeError(null);
        }
        const streamCursor = cursorRef.current;
        eventSource = agentCanvasApi.openAgentCanvasEventStream(workflowId, streamCursor);
        eventSource.onmessage = handleMessage;
        AGENT_CANVAS_SSE_EVENT_TYPES.forEach((type) =>
          eventSource?.addEventListener(type, handleMessage as EventListener),
        );
        let postConnectSyncStarted = false;
        eventSource.onopen = () => {
          reconnectAttempt = 0;
          setConnectionState("live");
          if (postConnectSyncStarted) return;
          postConnectSyncStarted = true;
          void (async () => {
            // A runtime baseline can be newer than the Timeline snapshot that was
            // being assembled at the same time. Once the stream is truly open,
            // replay its boundary again and refresh the authoritative projections.
            try {
              await replayEvents(streamCursor, isCurrentConnection);
              if (!isCurrentConnection() || !initialConnection) return;
              void refreshWorkflow();
              setChatRevision((current) => current + 1);
            } catch (error) {
              if (!isCurrentConnection()) return;
              setRuntimeError(
                error instanceof Error
                  ? error.message
                  : "The live event stream could not be synchronized.",
              );
            }
          })();
        };
        eventSource.onerror = () => {
          if (connectionId === currentConnectionId) currentConnectionId += 1;
          eventSource?.close();
          eventSource = null;
          if (cancelled) return;
          reconnectAttempt += 1;
          setConnectionState("reconnecting");
          reconnectTimer = window.setTimeout(
            () => void connect(),
            Math.min(1000 * (2 ** Math.min(reconnectAttempt, 4)), 12_000),
          );
        };

        // Replay after installing SSE so events created after the baseline are
        // covered even if the stream's first delivery is delayed. The final
        // authority refresh runs from onopen, after the stream is confirmed live.
        await replayEvents(streamCursor, isCurrentConnection);
        if (cancelled) return;
      } catch (error) {
        if (cancelled) return;
        if (connectionId === currentConnectionId) currentConnectionId += 1;
        eventSource?.close();
        eventSource = null;
        if (isV2ApiError(error) && [404, 405, 501].includes(error.status)) {
          setConnectionState("unavailable");
          setRuntimeError("Live Agent Canvas events require the matching backend update.");
          return;
        }
        if (isV2ApiError(error) && error.code === "event_cursor_expired") {
          try {
            const latestRuntime = await agentCanvasApi.agentCanvasRuntime(workflowId);
            if (cancelled || activeWorkflowIdRef.current !== workflowId) return;
            setRuntime((current) => (
              sameRuntimePresentation(current, latestRuntime) ? current : latestRuntime
            ));
            cursorRef.current = latestRuntime.events_cursor;
            setRuntimeError(null);
            await refreshWorkflow();
            if (cancelled) return;
            setChatRevision((current) => current + 1);
            reconnectAttempt = 0;
            reconnectTimer = window.setTimeout(() => void connect(), 0);
            return;
          } catch (recoveryError) {
            if (cancelled) return;
            setRuntimeError(
              recoveryError instanceof Error
                ? recoveryError.message
                : "The live event cursor could not be recovered.",
            );
          }
        }
        reconnectAttempt += 1;
        setConnectionState("reconnecting");
        reconnectTimer = window.setTimeout(
          () => void connect(),
          Math.min(1000 * (2 ** Math.min(reconnectAttempt, 4)), 12_000),
        );
      }
    };

    cursorRef.current = 0;
    void connect();
    return () => {
      cancelled = true;
      window.clearTimeout(reconnectTimer);
      eventSource?.close();
    };
  }, [processEvent, refreshRuntime, refreshWorkflow, workflowId]);

  const runAll = useCallback(async () => {
    if (!workflowId || !workflow) return;
    setRunPending(true);
    try {
      const migrations = runnableDraftParameterMigrations(workflow);
      const patchNode = patchNodeRef.current;
      if (migrations.length && !patchNode) {
        throw new Error("Global Run cannot migrate legacy provider parameters.");
      }
      for (const migration of migrations) {
        await patchNode!(migration.node_id, {
          parameters: migration.parameters,
        });
      }
      await agentCanvasApi.runAgentCanvas(workflowId, {
        scope: "all_drafts",
        node_ids: [],
        retry_failed: false,
        source_action: "global_run",
      }, createOperationKey("run-all"));
      await refreshRuntime();
    } finally {
      setRunPending(false);
    }
  }, [refreshRuntime, workflow, workflowId]);

  const runNode = useCallback(async (
    node: CanvasNodeV2,
    options: { retryFailed?: boolean } = {},
  ) => {
    if (!workflowId) return;
    if (!["text", "script", "image", "video", "audio"].includes(node.node_type)) return;
    if (isSourceOnlyNode(node)) return;
    if (node.status !== "draft" && node.status !== "failed") return;
    setRunPending(true);
    try {
      const request = nodeRunRequest(node, options.retryFailed);
      await agentCanvasApi.runAgentCanvas(
        workflowId,
        request,
        createOperationKey(request.retry_failed ? "retry-node" : "run-node"),
      );
      setInputReadinessIssue((current) => (
        current?.target_node_id === node.node_id ? null : current
      ));
      await refreshRuntime();
    } catch (error) {
      if (isV2ApiError(error) && error.code === "upstream_inputs_not_ready") {
        const issue = upstreamInputReadinessIssueFromDetails(node.node_id, error.details);
        if (issue) setInputReadinessIssue(issue);
      }
      throw error;
    } finally {
      setRunPending(false);
    }
  }, [refreshRuntime, workflowId]);

  const cancelRun = useCallback(async () => {
    if (!workflowId || !runtime?.active_execution_id) return;
    await agentCanvasApi.cancelAgentCanvasRun(
      workflowId,
      runtime.active_execution_id,
      { reason: "user_cancelled" },
    );
    await refreshRuntime();
  }, [refreshRuntime, runtime?.active_execution_id, workflowId]);

  return {
    state: {
      runtime,
      connectionState,
      runtimeError,
      runPending,
      chatRevision,
      chatEvents,
      settingsRevision,
      documentEvents,
      editingPreparationByNodeId,
      autoRunNotice,
      inputManifestsByNodeId,
      modelResolutionsByNodeId,
      inputReadinessIssue,
    },
    actions: {
      refreshRuntime,
      refreshWorkflow,
      runAll,
      runNode,
      cancelRun,
      clearAutoRunNotice: () => setAutoRunNotice(null),
    },
  };
}
