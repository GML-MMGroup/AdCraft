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
  }

  useEffect(() => {
    setRuntime(null);
    setRuntimeError(null);
    setChatEvents([]);
    setChatRevision(0);
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
          setRuntime(next);
          setRuntimeError(null);
        } catch (error) {
          if (activeWorkflowIdRef.current !== workflowId) return;
          if (isV2ApiError(error) && [404, 405, 501].includes(error.status)) {
            setConnectionState("unavailable");
            setRuntimeError("Agent Canvas runtime requires the matching backend update.");
            return;
          }
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
    if (policy.refreshRuntime) void refreshRuntime();
    if (policy.refreshWorkflow) void refreshWorkflow();
    if (policy.refreshAssets) void refreshAssets(event);
    if (policy.refreshChat) {
      setChatEvents((current) => [...current, event].slice(-100));
      setChatRevision((current) => current + 1);
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

    const handleMessage = (message: MessageEvent<string>) => {
      try {
        processEvent(normalizeCanvasRuntimeEventV2(JSON.parse(message.data)));
      } catch {
        void refreshRuntime();
      }
    };

    const connect = async () => {
      if (cancelled) return;
      setConnectionState(reconnectAttempt ? "reconnecting" : "connecting");
      try {
        if (cursorRef.current === 0) {
          const baselineRuntime = await agentCanvasApi.agentCanvasRuntime(workflowId);
          if (cancelled || activeWorkflowIdRef.current !== workflowId) return;
          setRuntime(baselineRuntime);
          cursorRef.current = baselineRuntime.events_cursor;
          setRuntimeError(null);
        }
        for (;;) {
          const before = cursorRef.current;
          const replay = await agentCanvasApi.agentCanvasEvents(workflowId, before, 200);
          if (cancelled) return;
          replay.events.forEach(processEvent);
          cursorRef.current = Math.max(cursorRef.current, replay.next_cursor);
          if (replay.events.length < 200 || cursorRef.current <= before) break;
        }
        await refreshRuntime();
        if (cancelled) return;
        eventSource = agentCanvasApi.openAgentCanvasEventStream(workflowId, cursorRef.current);
        eventSource.onmessage = handleMessage;
        AGENT_CANVAS_SSE_EVENT_TYPES.forEach((type) =>
          eventSource?.addEventListener(type, handleMessage as EventListener),
        );
        eventSource.onopen = () => {
          reconnectAttempt = 0;
          setConnectionState("live");
        };
        eventSource.onerror = () => {
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
      } catch (error) {
        if (cancelled) return;
        if (isV2ApiError(error) && [404, 405, 501].includes(error.status)) {
          setConnectionState("unavailable");
          setRuntimeError("Live Agent Canvas events require the matching backend update.");
          return;
        }
        if (isV2ApiError(error) && error.code === "event_cursor_expired") {
          try {
            const latestRuntime = await agentCanvasApi.agentCanvasRuntime(workflowId);
            if (cancelled || activeWorkflowIdRef.current !== workflowId) return;
            setRuntime(latestRuntime);
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
    },
  };
}
