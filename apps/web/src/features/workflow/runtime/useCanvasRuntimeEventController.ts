import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";
import { api } from "../../../api/client.ts";
import { dispatchAssetLibraryUploadEvent, normalizeMediaStatus } from "../../../api/workflowNormalizers.ts";
import type { WorkflowRuntimeEventV2, WorkflowV2 } from "../../../types-v2.ts";
import type { AgentConversationEvent, FinalCompositionTimelineResponse, MediaStatus, NodeRunResult, UploadedAsset, WorkflowGraph, WorkflowRevisionState } from "../../../types.ts";
import { isVisibleAgent } from "../../../workflow/agentConversations.ts";
import {
  chatCanvasRefreshHints,
  isChatCanvasActionRuntimeEvent,
  isChatCanvasPromptRuntimeEvent,
  isChatCanvasRevisionRuntimeEvent,
} from "../../../workflow/chatCanvasActions.ts";
import {
  applyCanvasRuntimeEvent,
  applyCanvasRuntimeSnapshot,
  canvasRuntimeEdgeSourceNodeIds,
  canvasRuntimeNodeStatusMap,
  initialCanvasRuntimeStore,
  isCanvasRuntimeAssetLibraryEvent,
  isCanvasRuntimeCandidateEvent,
  isCanvasRuntimeTimelineEvent,
  normalizeCanvasRuntimeCandidatePayload,
  normalizeCanvasRuntimeEvent,
  type CanvasRuntimeCandidatePayload,
  type CanvasRuntimeConnectionState,
  type CanvasRuntimeEvent,
  type CanvasRuntimeSnapshot,
  type CanvasRuntimeStore,
} from "../../../workflow/canvasRuntime.ts";
import { localRevisionStateKey, pendingVisibleRevisionCandidates } from "../../../workflow/localRevision.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { isV2WorkflowId } from "../../../workflow-v2/pageAdapter.ts";
import { isV2SynchronizationEvent } from "../../../workflow-v2/runtime.ts";
import { frontDeskConversationId } from "../copilot/agentConversationPanelModel.ts";
import { assetLibraryRefreshDetailFromEvent, patchAssetLibraryState } from "../assets/dynamicItemAssetModel.ts";
import { assetTypeFromSemanticType, latestLocalRevisionPromptMetadata, localRevisionTargetsMatch, revisionMatchesCanvasCandidate } from "../assets/localRevisionViewModel.ts";
import type { CanvasCandidateSummaryState, LocalRevisionCardState } from "../assets/useWorkflowAssetOperations.ts";
import {
  V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES,
  V2_SLOT_VERSION_REFRESH_EVENT_TYPES,
  V2_WORKFLOW_REFRESH_EVENT_TYPES,
  v2EventRefreshHints,
  v2EventShouldRefreshAssets,
  v2EventShouldRefreshProviderTasks,
  v2EventShouldRefreshRuntime,
  v2RuntimeEventSlotId,
} from "./v2RuntimeEventModel.ts";
import { useCanvasRuntimeSubscription } from "./useCanvasRuntimeSubscription.ts";
import { stringFromUnknown } from "./resolvedInputsViewModel.ts";
import {
  canvasRuntimeEventHandlers,
  type PendingScopedWorkflowRefresh,
  type ScopedWorkflowRefreshPlan,
} from "./canvasRuntimeEventHandlers.ts";

export type { ScopedWorkflowRefreshPlan } from "./canvasRuntimeEventHandlers.ts";

type V2RuntimeSnapshotAdapter = {
  syncSnapshot: (workflowId: string) => Promise<unknown>;
  slotNodeId: (slotId: string) => string | null;
};

export type CanvasRuntimeEventControllerArgs = {
  localWorkflowId: string;
  activeWorkflowIdRef: RefObject<string | null>;
  selectedNodeIdRef: RefObject<string>;
  getActiveConversationId: () => string | null;
  getRevisionHistoryTarget: () => UploadedAsset | null;
  getV2SlotVersionsById: () => Record<string, unknown>;
  getActiveV2SlotId: () => string | null;
  getWorkflowV2: () => WorkflowV2 | null | undefined;
  currentWorkflowIsV2: () => boolean;
  v2Runtime: V2RuntimeSnapshotAdapter;
  setActiveExecutionId: Dispatch<SetStateAction<string | null>>;
  setExecutionPollingState: Dispatch<SetStateAction<"idle" | "starting" | "polling" | "completed" | "failed">>;
  setWorkflowRunning: Dispatch<SetStateAction<boolean>>;
  setStatus: Dispatch<SetStateAction<string>>;
  setRunningNodeIds: Dispatch<SetStateAction<string[]>>;
  setMediaStatus: Dispatch<SetStateAction<MediaStatus | null>>;
  setCanvasCandidateSummaryByNodeId: Dispatch<SetStateAction<Record<string, CanvasCandidateSummaryState>>>;
  setLocalRevisionByKey: Dispatch<SetStateAction<Record<string, LocalRevisionCardState>>>;
  setQualityOverrideRevisionId: Dispatch<SetStateAction<string | null>>;
  setV2ProviderTaskRefreshKeyBySlotId: Dispatch<SetStateAction<Record<string, number>>>;
  setSelectedNodeRun: Dispatch<SetStateAction<NodeRunResult | null>>;
  onApplySnapshotGraph: (graph: WorkflowGraph) => void;
  onApplyMediaStatusToCanvas: (status: MediaStatus | null) => void;
  onPatchNodeStatus: (nodeId: string | null | undefined, status: string | null | undefined) => void;
  onApplyNodeRunsToCanvas: (runs: NodeRunResult[]) => void;
  onClearNodeDebugCache: (nodeId: string) => void;
  onRefreshSelectedResolvedInputs: (nodeId: string, options?: { force?: boolean }) => Promise<unknown>;
  onRefreshWorkflowGraph: (workflowId: string) => Promise<unknown>;
  onRefreshMediaStatus: (workflowId: string) => Promise<MediaStatus | null>;
  onRefreshV2WorkflowGraph: (
    workflowId: string,
    options?: { refreshRuntime?: boolean; refreshAssets?: boolean },
  ) => Promise<WorkflowV2 | null>;
  onRefreshV2AssetsAndRetryMissing: (workflowId: string, reason: string, workflow?: WorkflowV2 | null) => Promise<unknown>;
  onLoadV2SlotVersions: (slotId: string) => Promise<unknown> | void;
  onLoadLocalAssetHistory: (workflowId: string, nodeId: string, asset: UploadedAsset) => Promise<unknown>;
  onApplyLocalRevisionState: (key: string, revision: WorkflowRevisionState) => void;
  onUpdateLocalRevisionCardState: (key: string, patch: Partial<LocalRevisionCardState>) => void;
  onNoteAffected: (nodes?: string[]) => void;
  onTimelineLoadStarted: () => void;
  onTimelineLoadFailed: (message: string) => void;
  onApplyFinalCompositionTimelineResponse: (workflowId: string, response: FinalCompositionTimelineResponse, options?: { eventDirty?: boolean }) => void;
  onMarkTimelineEventDirty: () => void;
  onTimelineRenderStarted: () => void;
  onTimelineRenderFailed: (message: string) => void;
  onTimelineRenderFinished: () => void;
  finalCompositionErrorMessage: (error: unknown) => string;
  onAppendConversationEventForConversation: (conversationId: string, event: AgentConversationEvent) => void;
  onHandleAgentConversationEvents: (events: AgentConversationEvent[], workflowId: string) => Promise<void>;
  onHandleNodePromptUpdatedEvent: (event: AgentConversationEvent, workflowId: string) => Promise<void>;
  onHandleItemPromptUpdatedEvent: (event: AgentConversationEvent, workflowId: string) => Promise<void>;
  onHandleRevisionConversationEvent: (event: AgentConversationEvent, workflowId: string) => Promise<void>;
};

export function useCanvasRuntimeEventController(args: CanvasRuntimeEventControllerArgs) {
  const argsRef = useRef(args);
  const [canvasRuntimeConnectionState, setCanvasRuntimeConnectionState] = useState<CanvasRuntimeConnectionState>("disconnected");
  const [canvasRuntimeStatusById, setCanvasRuntimeStatusById] = useState<Record<string, string>>({});
  const [canvasRuntimeActiveEdgeIds, setCanvasRuntimeActiveEdgeIds] = useState<string[]>([]);
  const canvasRuntimeStoreRef = useRef<CanvasRuntimeStore>(initialCanvasRuntimeStore);
  const pendingScopedWorkflowRefreshRef = useRef<PendingScopedWorkflowRefresh | null>(null);
  const scopedWorkflowRefreshFrameRef = useRef<number | null>(null);
  const canvasRuntimeSubscriptionRef = useRef<ReturnType<typeof useCanvasRuntimeSubscription> | null>(null);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  const applyCanvasRuntimeStoreState = useCallback((nextStore: CanvasRuntimeStore) => {
    canvasRuntimeStoreRef.current = nextStore;
    setCanvasRuntimeConnectionState(nextStore.connectionState);
    argsRef.current.setActiveExecutionId(nextStore.activeExecutionId);
    setCanvasRuntimeStatusById(canvasRuntimeNodeStatusMap(nextStore));
    setCanvasRuntimeActiveEdgeIds(nextStore.activeEdgeIds);
    argsRef.current.setRunningNodeIds(canvasRuntimeEdgeSourceNodeIds(nextStore));
  }, []);

  const refreshScopedWorkflowNodeRuns = useCallback(async (workflowId: string, nodeIds: string[]) => {
    const uniqueNodeIds = Array.from(new Set(nodeIds.filter(Boolean)));
    if (!uniqueNodeIds.length) return;
    const runs = (
      await Promise.all(
        uniqueNodeIds.map(async (nodeId) => {
          try {
            const run = await api.workflowNode(workflowId, nodeId);
            return { ...run, node_id: run.node_id || nodeId };
          } catch {
            return null;
          }
        }),
      )
    ).filter((run): run is NodeRunResult => Boolean(run));
    if (!runs.length || !shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
    argsRef.current.onApplyNodeRunsToCanvas(runs);
    const selectedNodeId = argsRef.current.selectedNodeIdRef.current;
    const selectedRun = selectedNodeId ? runs.find((run) => (run.node_id || run.node_type) === selectedNodeId) : null;
    if (selectedRun) argsRef.current.setSelectedNodeRun(selectedRun);
  }, []);

  const flushScopedWorkflowRefreshPlan = useCallback(async (workflowId = pendingScopedWorkflowRefreshRef.current?.workflowId) => {
    const pending = pendingScopedWorkflowRefreshRef.current;
    if (!pending || !workflowId || pending.workflowId !== workflowId) return;
    pendingScopedWorkflowRefreshRef.current = null;
    if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;

    if (pending.runtimeSnapshot) {
      await canvasRuntimeSubscriptionRef.current?.loadSnapshot(workflowId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
    }
    if (pending.graph) {
      await argsRef.current.onRefreshWorkflowGraph(workflowId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
    }
    if (pending.nodeIds.size) {
      await refreshScopedWorkflowNodeRuns(workflowId, Array.from(pending.nodeIds));
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
    }
    if (pending.mediaStatus) {
      await argsRef.current.onRefreshMediaStatus(workflowId);
      if (!shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
    }

    const selectedNodeId = argsRef.current.selectedNodeIdRef.current;
    if (selectedNodeId && pending.resolvedInputNodeIds.has(selectedNodeId)) {
      argsRef.current.onClearNodeDebugCache(selectedNodeId);
      await argsRef.current.onRefreshSelectedResolvedInputs(selectedNodeId, { force: true });
    }
  }, [refreshScopedWorkflowNodeRuns]);

  const queueScopedWorkflowRefresh = useCallback((workflowId: string, plan: ScopedWorkflowRefreshPlan) => {
    if (!workflowId || !shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) return;
    const pending =
      pendingScopedWorkflowRefreshRef.current?.workflowId === workflowId
        ? pendingScopedWorkflowRefreshRef.current
        : canvasRuntimeEventHandlers.createPendingScopedWorkflowRefresh(workflowId);
    canvasRuntimeEventHandlers.mergeScopedWorkflowRefreshPlan(pending, plan);
    pendingScopedWorkflowRefreshRef.current = pending;
    if (scopedWorkflowRefreshFrameRef.current !== null) return;
    scopedWorkflowRefreshFrameRef.current = requestAnimationFrame(() => {
      scopedWorkflowRefreshFrameRef.current = null;
      void flushScopedWorkflowRefreshPlan(workflowId);
    });
  }, [flushScopedWorkflowRefreshPlan]);

  const applyCanvasRuntimeSnapshotToPage = useCallback((snapshot: CanvasRuntimeSnapshot) => {
    const nextStore = applyCanvasRuntimeSnapshot(canvasRuntimeStoreRef.current, snapshot);
    applyCanvasRuntimeStoreState(nextStore);
    if (snapshot.graph) argsRef.current.onApplySnapshotGraph(snapshot.graph);
    if (snapshot.mediaStatus) {
      argsRef.current.setMediaStatus(snapshot.mediaStatus);
      argsRef.current.onApplyMediaStatusToCanvas(snapshot.mediaStatus);
    }
  }, [applyCanvasRuntimeStoreState]);

  const setCanvasRuntimeConnectionStateOnPage = useCallback((connectionState: CanvasRuntimeConnectionState) => {
    canvasRuntimeStoreRef.current = { ...canvasRuntimeStoreRef.current, connectionState };
    setCanvasRuntimeConnectionState(connectionState);
  }, []);

  const canvasRuntimeSubscription = useCanvasRuntimeSubscription({
    localWorkflowId: args.localWorkflowId,
    activeWorkflowIdRef: args.activeWorkflowIdRef,
    onConnectionState: setCanvasRuntimeConnectionStateOnPage,
    onSnapshot: applyCanvasRuntimeSnapshotToPage,
    onEvent: (workflowId, event) => handleCanvasRuntimeEvent(workflowId, event),
  });
  canvasRuntimeSubscriptionRef.current = canvasRuntimeSubscription;

  const stopCanvasRuntimeSubscription = useCallback(() => {
    canvasRuntimeSubscription.stop();
    if (scopedWorkflowRefreshFrameRef.current !== null) {
      cancelAnimationFrame(scopedWorkflowRefreshFrameRef.current);
      scopedWorkflowRefreshFrameRef.current = null;
    }
    pendingScopedWorkflowRefreshRef.current = null;
    canvasRuntimeStoreRef.current = initialCanvasRuntimeStore;
    setCanvasRuntimeStatusById({});
    setCanvasRuntimeActiveEdgeIds([]);
    setCanvasRuntimeConnectionState("disconnected");
  }, [canvasRuntimeSubscription]);

  const startCanvasRuntimeSubscription = useCallback((workflowId: string) => {
    if (!workflowId || workflowId === argsRef.current.localWorkflowId) return;
    stopCanvasRuntimeSubscription();
    canvasRuntimeStoreRef.current = { ...initialCanvasRuntimeStore, connectionState: "connecting" };
    canvasRuntimeSubscription.start(workflowId);
  }, [canvasRuntimeSubscription, stopCanvasRuntimeSubscription]);

  const scopedRefreshPlanFromHints = useCallback((refreshHints: string[], targetNodeId?: string | null): ScopedWorkflowRefreshPlan => {
    const wantsGraph = refreshHints.includes("workflow_graph") || refreshHints.includes("graph");
    const wantsNode = refreshHints.includes("node") || refreshHints.includes("node_assets") || wantsGraph;
    const wantsMedia = refreshHints.includes("media_status") || refreshHints.includes("node_assets");
    const wantsResolved = refreshHints.includes("resolved_inputs") || refreshHints.includes("node");
    return {
      graph: wantsGraph,
      mediaStatus: wantsMedia,
      nodeIds: wantsNode && targetNodeId ? [targetNodeId] : [],
      resolvedInputNodeIds: wantsResolved && targetNodeId ? [targetNodeId] : [],
    };
  }, []);

  const candidateEventTargetAsset = useCallback((candidate: CanvasRuntimeCandidatePayload): UploadedAsset | null => {
    if (!candidate.entityId || !candidate.semanticType) return null;
    const assetType = assetTypeFromSemanticType(candidate.semanticType);
    return {
      asset_id: candidate.targetAssetId || candidate.entityId,
      asset_type: assetType,
      asset_role: assetType === "audio" ? "audio" : "reference",
      filename: candidate.entityId,
      mime_type: "",
      local_path: "",
      entity_id: candidate.entityId,
      semantic_type: candidate.semanticType,
      ...(candidate.libraryEntityId ? { library_entity_id: candidate.libraryEntityId } : {}),
      ...(candidate.libraryAssetId ? { library_asset_id: candidate.libraryAssetId, library_asset_ids: [candidate.libraryAssetId] } : {}),
      ...(candidate.libraryState ? { library_state: candidate.libraryState } : {}),
      ...(candidate.libraryError ? { library_error: candidate.libraryError } : {}),
      ...(candidate.sourceType ? { source_type: candidate.sourceType } : {}),
    };
  }, []);

  const updateCanvasRuntimeCandidateSummary = useCallback((nodeId: string | null | undefined, candidate: CanvasRuntimeCandidatePayload, options?: { dirty?: boolean }) => {
    if (!nodeId) return;
    argsRef.current.setCanvasCandidateSummaryByNodeId((current) => {
      const previous = current[nodeId] ?? {};
      return {
        ...current,
        [nodeId]: {
          candidateCount: candidate.candidateCount ?? candidate.pendingVisibleCandidateCount ?? previous.candidateCount,
          candidateWarningCount: candidate.candidateWarningCount ?? previous.candidateWarningCount,
          pendingVisibleCandidateCount: candidate.pendingVisibleCandidateCount ?? previous.pendingVisibleCandidateCount,
          dirty: options?.dirty ?? previous.dirty,
          updatedAt: new Date().toISOString(),
        },
      };
    });
  }, []);

  const patchLocalRevisionLibraryState = useCallback((workflowId: string, nodeId: string, targetAsset: UploadedAsset, candidate: CanvasRuntimeCandidatePayload) => {
    const revisionKey = localRevisionStateKey(workflowId, nodeId, targetAsset);
    const patchRevision = (revision: WorkflowRevisionState): WorkflowRevisionState => {
      if (!revisionMatchesCanvasCandidate(revision, candidate)) return revision;
      return {
        ...revision,
        library_state: candidate.libraryState ?? revision.library_state,
        library_entity_id: candidate.libraryEntityId ?? revision.library_entity_id,
        library_asset_id: candidate.libraryAssetId ?? revision.library_asset_id,
        library_error: candidate.libraryError ?? revision.library_error,
        source_type: candidate.sourceType ?? revision.source_type,
        candidate_asset: patchAssetLibraryState(revision.candidate_asset, candidate),
        candidate_assets: revision.candidate_assets?.map((asset) => patchAssetLibraryState(asset, candidate) ?? asset),
        assets: revision.assets?.map((asset) => patchAssetLibraryState(asset, candidate) ?? asset),
        history: revision.history?.map((asset) => patchAssetLibraryState(asset, candidate) ?? asset),
      };
    };

    argsRef.current.setLocalRevisionByKey((current) => {
      const state = current[revisionKey];
      if (!state) return current;
      return {
        ...current,
        [revisionKey]: {
          ...state,
          candidates: state.candidates?.map(patchRevision),
          revisions: state.revisions?.map(patchRevision),
          assets: state.assets?.map((asset) => patchAssetLibraryState(asset, candidate) ?? asset),
          history: state.history?.map((asset) => patchAssetLibraryState(asset, candidate) ?? asset),
          updatedAt: new Date().toISOString(),
        },
      };
    });
  }, []);

  const refreshCanvasRuntimeCandidateDetails = useCallback(async (
    workflowId: string,
    nodeId: string,
    candidate: CanvasRuntimeCandidatePayload,
    eventType: string,
    options: { forceRevisionList?: boolean } = {},
  ) => {
    if (isV2WorkflowId(workflowId) || argsRef.current.currentWorkflowIsV2()) return;
    const refresh = new Set(candidate.refresh);
    const targetAsset = candidateEventTargetAsset(candidate);

    if (candidate.revisionId && (refresh.has("revision") || eventType === "candidate_quality_updated")) {
      try {
        const revision = await api.getNodeRevision(workflowId, nodeId, candidate.revisionId);
        if (targetAsset && shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) {
          argsRef.current.onApplyLocalRevisionState(localRevisionStateKey(workflowId, nodeId, targetAsset), revision);
        }
      } catch {
        options.forceRevisionList = true;
      }
    }

    if (options.forceRevisionList || refresh.has("revisions") || eventType === "candidate_created" || eventType === "revision_status_changed") {
      try {
        const response = await api.listNodeRevisions(workflowId, nodeId);
        if (targetAsset && shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) {
          const revisions = response.revisions.filter((revision) => revisionMatchesCanvasCandidate(revision, candidate));
          argsRef.current.onUpdateLocalRevisionCardState(localRevisionStateKey(workflowId, nodeId, targetAsset), {
            revisions,
            candidates: pendingVisibleRevisionCandidates(revisions),
            promptMetadata: latestLocalRevisionPromptMetadata(revisions),
          });
        }
      } catch {
        // A missing archived/superseded revision can be recovered by the history endpoint.
      }
    }

    if (targetAsset && (refresh.has("asset_history") || eventType === "candidate_created" || eventType === "candidate_accepted" || eventType === "candidate_rejected" || eventType === "candidate_superseded" || eventType === "asset_history_updated")) {
      await argsRef.current.onLoadLocalAssetHistory(workflowId, nodeId, targetAsset);
    }

    if (refresh.has("node_assets")) queueScopedWorkflowRefresh(workflowId, { nodeIds: [nodeId] });
    if (refresh.has("workflow_graph")) queueScopedWorkflowRefresh(workflowId, { graph: true });
    const selectedNodeId = argsRef.current.selectedNodeIdRef.current;
    if (refresh.has("resolved_inputs") && selectedNodeId && (selectedNodeId === nodeId || candidate.affectedDownstreamNodeIds.includes(selectedNodeId))) {
      queueScopedWorkflowRefresh(workflowId, { resolvedInputNodeIds: [selectedNodeId] });
    }
  }, [candidateEventTargetAsset, queueScopedWorkflowRefresh]);

  const handleCanvasRuntimeCandidateEvent = useCallback(async (workflowId: string, event: CanvasRuntimeEvent) => {
    const nodeId = event.node_id ?? null;
    if (!nodeId) return;
    const candidate = normalizeCanvasRuntimeCandidatePayload(event);
    const targetAsset = candidateEventTargetAsset(candidate);
    const panelOpen = argsRef.current.selectedNodeIdRef.current === nodeId;
    const revisionHistoryTarget = argsRef.current.getRevisionHistoryTarget();
    const targetHistoryOpen = Boolean(targetAsset && revisionHistoryTarget && panelOpen && localRevisionTargetsMatch(revisionHistoryTarget, targetAsset));
    const shouldRefreshDetails = panelOpen || targetHistoryOpen;

    updateCanvasRuntimeCandidateSummary(nodeId, candidate, { dirty: !candidate.candidateCount && !candidate.pendingVisibleCandidateCount });

    if (event.event_type === "candidate_accepted") {
      const selectedNodeId = argsRef.current.selectedNodeIdRef.current;
      queueScopedWorkflowRefresh(workflowId, {
        nodeIds: [nodeId],
        graph: candidate.refresh.includes("workflow_graph"),
        mediaStatus: candidate.refresh.includes("node_assets"),
        resolvedInputNodeIds: selectedNodeId && (selectedNodeId === nodeId || candidate.affectedDownstreamNodeIds.includes(selectedNodeId)) ? [selectedNodeId] : [],
      });
      if (targetAsset) await argsRef.current.onLoadLocalAssetHistory(workflowId, nodeId, targetAsset);
      await refreshCanvasRuntimeCandidateDetails(workflowId, nodeId, candidate, event.event_type, { forceRevisionList: shouldRefreshDetails });
      argsRef.current.onNoteAffected(candidate.affectedDownstreamNodeIds);
      return;
    }

    if (event.event_type === "node_candidate_summary_updated") {
      if (shouldRefreshDetails) await refreshCanvasRuntimeCandidateDetails(workflowId, nodeId, candidate, event.event_type);
      return;
    }

    if (event.event_type === "candidate_rejected" || event.event_type === "candidate_superseded") {
      argsRef.current.setQualityOverrideRevisionId((current) => (current && current === candidate.revisionId ? null : current));
      if (shouldRefreshDetails) await refreshCanvasRuntimeCandidateDetails(workflowId, nodeId, candidate, event.event_type, { forceRevisionList: true });
      return;
    }

    if (event.event_type === "revision_status_changed" || event.event_type === "candidate_created" || event.event_type === "candidate_quality_updated" || event.event_type === "asset_history_updated") {
      if (shouldRefreshDetails) await refreshCanvasRuntimeCandidateDetails(workflowId, nodeId, candidate, event.event_type);
    }
  }, [candidateEventTargetAsset, queueScopedWorkflowRefresh, refreshCanvasRuntimeCandidateDetails, updateCanvasRuntimeCandidateSummary]);

  const handleCanvasRuntimeAssetLibraryEvent = useCallback(async (workflowId: string, event: CanvasRuntimeEvent) => {
    dispatchAssetLibraryUploadEvent(assetLibraryRefreshDetailFromEvent(workflowId, event));
    if (
      event.event_type !== "asset_library_entity_created" &&
      event.event_type !== "asset_library_entity_linked" &&
      event.event_type !== "asset_library_asset_linked" &&
      event.event_type !== "asset_library_ingest_failed" &&
      event.event_type !== "asset_reference_suggestions_updated"
    ) {
      return;
    }

    const nodeId = event.node_id ?? null;
    if (!nodeId) return;
    const candidate = normalizeCanvasRuntimeCandidatePayload(event);
    const targetAsset = candidateEventTargetAsset(candidate);
    updateCanvasRuntimeCandidateSummary(nodeId, candidate, { dirty: false });
    if (targetAsset && shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) {
      patchLocalRevisionLibraryState(workflowId, nodeId, targetAsset, candidate);
    }
    const panelOpen = argsRef.current.selectedNodeIdRef.current === nodeId;
    const revisionHistoryTarget = argsRef.current.getRevisionHistoryTarget();
    const targetHistoryOpen = Boolean(targetAsset && revisionHistoryTarget && panelOpen && localRevisionTargetsMatch(revisionHistoryTarget, targetAsset));
    if (targetAsset && (panelOpen || targetHistoryOpen || event.event_type === "asset_library_ingest_failed")) {
      await refreshCanvasRuntimeCandidateDetails(workflowId, nodeId, candidate, event.event_type, { forceRevisionList: true });
    }
  }, [candidateEventTargetAsset, patchLocalRevisionLibraryState, refreshCanvasRuntimeCandidateDetails, updateCanvasRuntimeCandidateSummary]);

  const handleFinalCompositionTimelineRuntimeEvent = useCallback(async (workflowId: string, event: CanvasRuntimeEvent) => {
    if (isV2WorkflowId(workflowId) || argsRef.current.currentWorkflowIsV2()) return;
    const panelOpen = argsRef.current.selectedNodeIdRef.current === "final-composition";
    const payload = event.payload ?? {};
    if (panelOpen || event.event_type === "timeline_clip_stale" || event.event_type === "timeline_updated") {
      try {
        argsRef.current.onTimelineLoadStarted();
        const response = await api.getFinalCompositionTimeline(workflowId);
        if (shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current)) {
          argsRef.current.onApplyFinalCompositionTimelineResponse(workflowId, response, { eventDirty: !panelOpen });
        }
      } catch (error) {
        if (shouldApplyWorkflowScopedResult(workflowId, argsRef.current.activeWorkflowIdRef.current) && panelOpen) {
          argsRef.current.onTimelineLoadFailed(argsRef.current.finalCompositionErrorMessage(error));
        }
      }
    } else {
      argsRef.current.onMarkTimelineEventDirty();
    }

    if (event.event_type === "final_render_started") {
      argsRef.current.onTimelineRenderStarted();
      return;
    }

    if (event.event_type === "final_render_failed") {
      argsRef.current.onTimelineRenderFailed(stringFromUnknown(payload.error) || stringFromUnknown(payload.error_code) || "Final render failed. Current active final video remains available.");
      queueScopedWorkflowRefresh(workflowId, { graph: true, nodeIds: [event.node_id ?? "final-composition"] });
      return;
    }

    if (event.event_type === "final_render_completed") {
      argsRef.current.onTimelineRenderFinished();
      const finalCandidate = normalizeCanvasRuntimeCandidatePayload({
        ...event,
        node_id: event.node_id ?? "final-composition",
        payload: {
          ...payload,
          target_entity_id: stringFromUnknown(payload.target_entity_id) || workflowId,
          semantic_type: stringFromUnknown(payload.semantic_type) || "final_video",
          refresh: payload.refresh ?? ["revision", "revisions", "asset_history", "workflow_graph", "node_assets"],
        },
      });
      await refreshCanvasRuntimeCandidateDetails(workflowId, "final-composition", finalCandidate, event.event_type, { forceRevisionList: true });
      queueScopedWorkflowRefresh(workflowId, {
        graph: finalCandidate.refresh.includes("workflow_graph"),
        mediaStatus: true,
        nodeIds: [event.node_id ?? "final-composition"],
        resolvedInputNodeIds: [argsRef.current.selectedNodeIdRef.current],
      });
    }
  }, [queueScopedWorkflowRefresh, refreshCanvasRuntimeCandidateDetails]);

  const canvasRuntimeConversationEvent = useCallback((workflowId: string, event: CanvasRuntimeEvent): AgentConversationEvent => {
    const payload = event.payload ?? {};
    const action = canvasRuntimeEventHandlers.recordFromUnknown(payload.action);
    const actionId = stringFromUnknown(payload.action_id) || stringFromUnknown(action?.action_id);
    const conversationId =
      stringFromUnknown(payload.conversation_id) ||
      stringFromUnknown(action?.conversation_id) ||
      argsRef.current.getActiveConversationId() ||
      frontDeskConversationId(workflowId);
    const speakerAgent = isVisibleAgent(payload.speaker_agent) ? payload.speaker_agent : isVisibleAgent(action?.speaker_agent) ? action.speaker_agent : "creative_director";
    return {
      event_id: stringFromUnknown(payload.event_id) || `runtime_${event.event_seq || Date.now()}_${event.event_type}`,
      conversation_id: conversationId,
      event_type: event.event_type as AgentConversationEvent["event_type"],
      speaker_agent: speakerAgent,
      workflow_id: event.workflow_id ?? workflowId,
      target_node_id: event.node_id || stringFromUnknown(payload.target_node_id) || stringFromUnknown(action?.target_node_id) || null,
      target_node_type: stringFromUnknown(payload.target_node_type) || stringFromUnknown(action?.target_node_type) || null,
      text: event.message || stringFromUnknown(payload.text) || stringFromUnknown(payload.message) || stringFromUnknown(payload.summary) || "",
      created_at: event.created_at ?? new Date().toISOString(),
      metadata: {
        ...payload,
        ...(action ? { action } : {}),
        ...(actionId ? { action_id: actionId } : {}),
        event_seq: event.event_seq,
      },
    };
  }, []);

  const handleCanvasRuntimeChatActionEvent = useCallback(async (workflowId: string, event: CanvasRuntimeEvent) => {
    const conversationEvent = canvasRuntimeConversationEvent(workflowId, event);
    argsRef.current.onAppendConversationEventForConversation(conversationEvent.conversation_id, conversationEvent);
    await argsRef.current.onHandleAgentConversationEvents([conversationEvent], workflowId);
    const refreshHints = chatCanvasRefreshHints(conversationEvent);
    queueScopedWorkflowRefresh(workflowId, scopedRefreshPlanFromHints(refreshHints, conversationEvent.target_node_id ?? argsRef.current.selectedNodeIdRef.current));
  }, [canvasRuntimeConversationEvent, queueScopedWorkflowRefresh, scopedRefreshPlanFromHints]);

  const handleCanvasRuntimePromptEvent = useCallback(async (workflowId: string, event: CanvasRuntimeEvent) => {
    const conversationEvent = canvasRuntimeConversationEvent(workflowId, event);
    argsRef.current.onAppendConversationEventForConversation(conversationEvent.conversation_id, conversationEvent);
    if (event.event_type === "node_prompt_updated") {
      await argsRef.current.onHandleNodePromptUpdatedEvent(conversationEvent, workflowId);
      return;
    }
    await argsRef.current.onHandleItemPromptUpdatedEvent(conversationEvent, workflowId);
  }, [canvasRuntimeConversationEvent]);

  const handleCanvasRuntimeRevisionEvent = useCallback(async (workflowId: string, event: CanvasRuntimeEvent) => {
    const conversationEvent = canvasRuntimeConversationEvent(workflowId, event);
    argsRef.current.onAppendConversationEventForConversation(conversationEvent.conversation_id, conversationEvent);
    await argsRef.current.onHandleRevisionConversationEvent(conversationEvent, workflowId);
  }, [canvasRuntimeConversationEvent]);

  const handleCanvasRuntimeEvent = useCallback(async (workflowId: string, rawEvent: CanvasRuntimeEvent) => {
    const event = normalizeCanvasRuntimeEvent(rawEvent);
    if (event.event_seq > 0 && event.event_seq <= canvasRuntimeStoreRef.current.lastEventSeq) return;
    const nextStore = applyCanvasRuntimeEvent(canvasRuntimeStoreRef.current, event);
    applyCanvasRuntimeStoreState(nextStore);
    const nodeId = event.node_id ?? null;

    if (canvasRuntimeEventHandlers.isNodeStatusRuntimeEvent(event.event_type)) {
      argsRef.current.onPatchNodeStatus(nodeId, event.status ?? nextStore.nodeRuntimeById[nodeId ?? ""]?.status);
      return;
    }

    if (event.event_type === "node_output_updated" || event.event_type === "node_assets_updated") {
      if (!nodeId) return;
      queueScopedWorkflowRefresh(workflowId, { nodeIds: [nodeId], resolvedInputNodeIds: [nodeId] });
      return;
    }

    if (event.event_type === "media_status_changed") {
      const nextMediaStatus = normalizeMediaStatus(event.payload?.media_status ?? event.payload);
      if (nextMediaStatus) {
        argsRef.current.setMediaStatus(nextMediaStatus);
        argsRef.current.onApplyMediaStatusToCanvas(nextMediaStatus);
      } else {
        queueScopedWorkflowRefresh(workflowId, { mediaStatus: true });
      }
      return;
    }

    if (event.event_type === "graph_updated") {
      queueScopedWorkflowRefresh(workflowId, { graph: true });
      return;
    }

    if (event.event_type === "resolved_inputs_updated") {
      queueScopedWorkflowRefresh(workflowId, { resolvedInputNodeIds: [nodeId] });
      return;
    }

    if (isChatCanvasActionRuntimeEvent(event.event_type) || event.event_type === "chat_action_created" || event.event_type === "chat_action_applied" || event.event_type === "chat_action_rejected" || event.event_type === "chat_action_failed") {
      await handleCanvasRuntimeChatActionEvent(workflowId, event);
      return;
    }

    if (isChatCanvasPromptRuntimeEvent(event.event_type) || event.event_type === "node_prompt_updated" || event.event_type === "item_prompt_updated") {
      await handleCanvasRuntimePromptEvent(workflowId, event);
      return;
    }

    if (isChatCanvasRevisionRuntimeEvent(event.event_type) || event.event_type === "revision_started" || event.event_type === "revision_waiting" || event.event_type === "revision_completed" || event.event_type === "revision_failed") {
      await handleCanvasRuntimeRevisionEvent(workflowId, event);
      return;
    }

    if (isCanvasRuntimeAssetLibraryEvent(event.event_type)) {
      await handleCanvasRuntimeAssetLibraryEvent(workflowId, event);
      return;
    }

    if (isCanvasRuntimeCandidateEvent(event.event_type) || event.event_type === "candidate_created") {
      await handleCanvasRuntimeCandidateEvent(workflowId, event);
      return;
    }

    if (isCanvasRuntimeTimelineEvent(event.event_type) || event.event_type === "timeline_updated" || event.event_type === "timeline_clip_stale" || event.event_type === "final_render_started" || event.event_type === "final_render_completed" || event.event_type === "final_render_failed") {
      await handleFinalCompositionTimelineRuntimeEvent(workflowId, event);
      return;
    }

    if (event.event_type === "execution_completed" || event.event_type === "execution_partial_failed" || event.event_type === "execution_failed" || event.event_type === "execution_cancelled") {
      queueScopedWorkflowRefresh(workflowId, {
        graph: true,
        mediaStatus: true,
        resolvedInputNodeIds: [argsRef.current.selectedNodeIdRef.current],
      });
      return;
    }

    if (event.event_type === "snapshot_required") {
      await canvasRuntimeSubscription.loadSnapshot(workflowId);
    }
  }, [
    applyCanvasRuntimeStoreState,
    canvasRuntimeSubscription,
    handleCanvasRuntimeAssetLibraryEvent,
    handleCanvasRuntimeCandidateEvent,
    handleCanvasRuntimeChatActionEvent,
    handleCanvasRuntimePromptEvent,
    handleCanvasRuntimeRevisionEvent,
    handleFinalCompositionTimelineRuntimeEvent,
    queueScopedWorkflowRefresh,
  ]);

  const applyV2RuntimeEventsToPage = useCallback((events: WorkflowRuntimeEventV2[]) => {
    if (!events.length) return;
    const workflowId = events.find((event) => event.workflow_id)?.workflow_id;
    const finalCompositionEvents = events.filter((event) =>
      event.event_type === "final_timeline_created" ||
      event.event_type === "final_timeline_updated" ||
      V2_FINAL_RENDER_LIFECYCLE_EVENT_TYPES.has(event.event_type),
    );
    if (workflowId && finalCompositionEvents.length) {
      window.dispatchEvent(new CustomEvent("v2-final-composition-events", {
        detail: {
          workflowId,
          events: finalCompositionEvents,
          eventTypes: finalCompositionEvents.map((event) => event.event_type),
        },
      }));
    }
    const runtimeEvents = events.filter((event) => !isV2SynchronizationEvent(event.event_type));
    const latestExecutionEvent = [...events].reverse().find((event) =>
      [
        "execution_queued",
        "execution_started",
        "execution_waiting",
        "execution_completed",
        "execution_partial_failed",
        "execution_failed",
        "execution_cancelled",
      ].includes(event.event_type),
    );
    if (latestExecutionEvent) {
      const executionId = stringFromUnknown(latestExecutionEvent.payload?.execution_id ?? latestExecutionEvent.payload?.active_execution_id);
      if (executionId) argsRef.current.setActiveExecutionId(executionId);
      if (latestExecutionEvent.event_type === "execution_completed") {
        argsRef.current.setExecutionPollingState("completed");
        argsRef.current.setWorkflowRunning(false);
        argsRef.current.setStatus("Workflow V2 run complete");
      } else if (latestExecutionEvent.event_type === "execution_partial_failed") {
        argsRef.current.setExecutionPollingState("failed");
        argsRef.current.setWorkflowRunning(false);
        argsRef.current.setStatus("Workflow V2 run partially failed");
      } else if (latestExecutionEvent.event_type === "execution_failed" || latestExecutionEvent.event_type === "execution_cancelled") {
        argsRef.current.setExecutionPollingState("failed");
        argsRef.current.setWorkflowRunning(false);
        argsRef.current.setStatus(latestExecutionEvent.event_type === "execution_cancelled" ? "Workflow V2 run cancelled" : "Workflow V2 run failed");
      } else if (latestExecutionEvent.event_type === "execution_waiting") {
        argsRef.current.setExecutionPollingState("polling");
        argsRef.current.setWorkflowRunning(true);
        argsRef.current.setStatus("Workflow V2 run waiting for media");
      } else {
        argsRef.current.setExecutionPollingState("polling");
        argsRef.current.setWorkflowRunning(true);
      }
    }
    const shouldRefreshRuntime = runtimeEvents.some(v2EventShouldRefreshRuntime);
    const shouldRefreshWorkflow = runtimeEvents.some((event) =>
      V2_WORKFLOW_REFRESH_EVENT_TYPES.has(event.event_type) ||
      v2EventRefreshHints(event).some((hint) => hint === "workflow" || hint === "slot_versions"),
    );
    const shouldRefreshAssets = runtimeEvents.some(v2EventShouldRefreshAssets);
    if (workflowId && (shouldRefreshRuntime || shouldRefreshWorkflow || shouldRefreshAssets)) {
      void (async () => {
        if (shouldRefreshRuntime) await argsRef.current.v2Runtime.syncSnapshot(workflowId);
        const refreshedWorkflow = shouldRefreshWorkflow
          ? await argsRef.current.onRefreshV2WorkflowGraph(workflowId, { refreshRuntime: false })
          : null;
        if (shouldRefreshAssets) {
          await argsRef.current.onRefreshV2AssetsAndRetryMissing(workflowId, "runtime-event", refreshedWorkflow ?? argsRef.current.getWorkflowV2());
        }
      })();
    }
    const versionRefreshSlotIds = new Set(
      events
        .filter((event) =>
          V2_SLOT_VERSION_REFRESH_EVENT_TYPES.has(event.event_type) ||
          v2EventRefreshHints(event).includes("slot_versions"),
        )
        .map(v2RuntimeEventSlotId)
        .filter((slotId): slotId is string => Boolean(slotId)),
    );
    versionRefreshSlotIds.forEach((slotId) => {
      if (argsRef.current.getV2SlotVersionsById()[slotId] || slotId === argsRef.current.getActiveV2SlotId()) {
        void argsRef.current.onLoadV2SlotVersions(slotId);
      }
    });
    const providerTaskRefreshSlotIds = new Set(
      events
        .filter(v2EventShouldRefreshProviderTasks)
        .map(v2RuntimeEventSlotId)
        .filter((slotId): slotId is string => Boolean(slotId)),
    );
    if (providerTaskRefreshSlotIds.size) {
      argsRef.current.setV2ProviderTaskRefreshKeyBySlotId((current) => {
        const next = { ...current };
        providerTaskRefreshSlotIds.forEach((slotId) => {
          next[slotId] = (next[slotId] ?? 0) + 1;
        });
        return next;
      });
    }
    const resolvedInputRefreshNodeIds = new Set(
      events
        .filter((event) => event.event_type === "resolved_inputs_updated" || event.event_type === "slot_selected_version_updated" || v2EventRefreshHints(event).includes("resolved_inputs"))
        .map((event) => event.node_id ?? (event.slot_id ? argsRef.current.v2Runtime.slotNodeId(event.slot_id) : null))
        .filter((nodeId): nodeId is string => Boolean(nodeId)),
    );
    resolvedInputRefreshNodeIds.forEach((nodeId) => {
      if (nodeId === argsRef.current.selectedNodeIdRef.current) void argsRef.current.onRefreshSelectedResolvedInputs(nodeId, { force: true });
    });
  }, []);

  return {
    state: {
      canvasRuntimeConnectionState,
      canvasRuntimeStatusById,
      canvasRuntimeActiveEdgeIds,
      canvasRuntimeStoreRef,
    },
    actions: {
      applyV2RuntimeEventsToPage,
      startCanvasRuntimeSubscription,
      stopCanvasRuntimeSubscription,
      applyCanvasRuntimeSnapshotToPage,
      applyCanvasRuntimeStoreState,
      queueScopedWorkflowRefresh,
      flushScopedWorkflowRefreshPlan,
      scopedRefreshPlanFromHints,
      handleCanvasRuntimeEvent,
      handleCanvasRuntimeCandidateEvent,
      handleCanvasRuntimeAssetLibraryEvent,
      handleFinalCompositionTimelineRuntimeEvent,
      candidateEventTargetAsset,
    },
  };
}
