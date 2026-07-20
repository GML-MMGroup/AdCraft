import { useEffect, useRef } from "react";
import { ApiError, api } from "../../../api/client.ts";
import type {
  MediaStatus,
  NodeRunResult,
  FinalCompositionTimelineResponse,
  ResolvedNodeInputs,
  UploadedAsset,
  VideoEditingExportResult,
  WorkflowGraph,
  WorkflowNode,
  WorkflowRevisionState,
} from "../../../types.ts";
import { isV2WorkflowId } from "../../../workflow-v2/pageAdapter.ts";
import {
  applyFinalVideoMediaStatusToWorkflowNodes,
  finalVideoStateFromMediaStatus,
  isFinalCompositionNode,
} from "../../../workflow/finalVideo.ts";
import {
  applyStoryboardMediaStatusToWorkflowNodes,
  isStoryboardVideoNode,
  shouldPollStoryboardVideoMedia,
  storyboardMediaFailureReason,
  storyboardSegmentsReadyForFinalComposition,
  storyboardSegmentAssetsFromMediaStatus,
  storyboardVideoReadinessFromSources,
  storyboardVideoStatusFromMediaStatus,
} from "../../../workflow/mediaSegments.ts";
import {
  localRevisionStateKey,
  pendingVisibleRevisionCandidates,
} from "../../../workflow/localRevision.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import {
  activeWorkflowAssets,
  previewAssetsForCanvasNodeType,
  qualitySummaryForNode,
} from "../assets/workflowAssetPreviewModel.ts";
import { latestLocalRevisionPromptMetadata } from "../assets/localRevisionViewModel.ts";
import { flowNodeToWorkflowNode, isNodeRunForCanvasInstance } from "../canvas/workflowCanvasModel.ts";
import {
  finalCompositionErrorMessage,
  formatStoryboardVideoWaitingStatus,
  resolvedInputsHaveReadyStoryboardSegments,
} from "../runtime/workflowExecutionViewModel.ts";
import { resolvedInputsFromNodeRun } from "../runtime/resolvedInputsViewModel.ts";
import { sleep } from "../page/workflowPageFormatters.ts";
import {
  finalCompositionRenderDisabledReason,
  type FinalCompositionExportSettings,
  type FinalCompositionTimelineViewState,
} from "./useFinalCompositionPageController.ts";
import { getTimelineClipCount } from "./finalCompositionTimelineModel.ts";
import {
  mergeQualityReviewResponseIntoNode,
  mergeQualityReviewResponseIntoRun,
} from "../quality/qualityReviewViewModel.ts";
import type { CanvasNode } from "../types.ts";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

type FinalCompositionTimelineLoadOptions = {
  preserveDraft?: boolean;
  eventDirty?: boolean;
};

type FinalCompositionOperationsArgs = {
  workflow: WorkflowGraph | null | undefined;
  canvasNodes: WorkflowNode[];
  nodeRuns: NodeRunResult[];
  mediaStatus: MediaStatus | null;
  flowNodes: CanvasNode[];
  selectedPlanNode: WorkflowNode | null | undefined;
  selectedRun: NodeRunResult | null | undefined;
  visibleCanvasNodes: WorkflowNode[];
  videoTimeline: Record<string, unknown>;
  finalCompositionTimelineState: FinalCompositionTimelineViewState;
  finalCompositionTimelineBaselineVersion: number | null;
  exportId: string;
  exportSettings: FinalCompositionExportSettings;
  activeWorkflowIdRef: React.MutableRefObject<string | null>;
  currentWorkflowIsV2: () => boolean;
  setStatus: StateSetter<string>;
  setMediaStatus: StateSetter<MediaStatus | null>;
  setCanvasNodes: StateSetter<WorkflowNode[]>;
  setFlowNodes: StateSetter<CanvasNode[]>;
  setSelectedNodeRun: StateSetter<NodeRunResult | null>;
  setSelectedResolvedInputs: StateSetter<ResolvedNodeInputs | null>;
  setQualityReviewingNodeIds: StateSetter<Record<string, boolean>>;
  setExportResult: StateSetter<VideoEditingExportResult | null>;
  setExportId: StateSetter<string>;
  timelineLoadStarted: () => void;
  timelineLoadFailed: (message: string) => void;
  applyFinalCompositionTimelineResponse: (
    workflowId: string,
    response: FinalCompositionTimelineResponse,
    options?: FinalCompositionTimelineLoadOptions,
  ) => void;
  setFinalCompositionTimelineConflict: (message: string | null) => void;
  timelineSaveStarted: () => void;
  timelineSaveFailed: (message: string) => void;
  timelineRenderStarted: () => void;
  timelineRenderFailed: (message: string) => void;
  timelineRenderFinished: () => void;
  syncV2Snapshot: (workflowId: string) => Promise<unknown>;
  refreshV2WorkflowGraph: (workflowId: string) => Promise<unknown>;
  saveCanvas: (options?: { quiet?: boolean; requireBackend?: boolean; nodes?: WorkflowNode[] }) => Promise<boolean>;
  refreshWorkflowNodes: (workflowId: string) => Promise<unknown>;
  refreshWorkflowGraph: (workflowId: string, runtimeRuns?: NodeRunResult[]) => Promise<unknown>;
  refreshSelectedResolvedInputs: (nodeId: string, options?: { force?: boolean }) => Promise<ResolvedNodeInputs | null>;
  patchWorkflowNodeState: (nodeIds: string[] | Set<string>, patch: Partial<WorkflowNode>) => void;
  applyNodeRunsToCanvas: (runs: NodeRunResult[]) => void;
  updateLocalRevisionCardState: (key: string, patch: Record<string, unknown>) => void;
  applyLocalRevisionState: (key: string, revision: WorkflowRevisionState) => void;
  loadLocalAssetHistory: (workflowId: string, nodeId: string, asset: UploadedAsset) => Promise<unknown>;
};

export function useFinalCompositionOperations(args: FinalCompositionOperationsArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  function applyMediaStatusToCanvas(nextMediaStatus: MediaStatus | null) {
    const current = argsRef.current;
    const segmentAssets = storyboardSegmentAssetsFromMediaStatus(nextMediaStatus);
    const storyboardStatus = storyboardVideoStatusFromMediaStatus(nextMediaStatus);
    const storyboardFailureReason = storyboardStatus === "failed" ? storyboardMediaFailureReason(nextMediaStatus) : null;
    const hasStoryboardMedia = Boolean(
      storyboardStatus ||
        segmentAssets.length ||
        nextMediaStatus?.storyboard_video_status ||
        nextMediaStatus?.segments?.length ||
        nextMediaStatus?.all_segments_ready,
    );

    if (hasStoryboardMedia) {
      current.setCanvasNodes((nodes) => applyStoryboardMediaStatusToWorkflowNodes(nodes, nextMediaStatus));
      current.setFlowNodes((nodes) =>
        nodes.map((node) => {
          if (!isStoryboardVideoNode({ id: node.id, node_type: node.data.kind })) return node;
          const previewAssets = previewAssetsForCanvasNodeType(node.data.kind, [...segmentAssets, ...node.data.previewAssets]);
          const mergedOutputCount = segmentAssets.length ? [...segmentAssets, ...node.data.previewAssets].length : node.data.outputCount;
          return {
            ...node,
            data: {
              ...node.data,
              ...(storyboardStatus ? { status: storyboardStatus } : {}),
              outputCount: mergedOutputCount,
              previewAssets,
              stale: storyboardStatus === "completed" ? false : node.data.stale,
              staleReason: storyboardStatus === "failed" ? storyboardFailureReason : storyboardStatus === "completed" ? null : node.data.staleReason,
            },
          };
        }),
      );
    }

    const finalVideoState = finalVideoStateFromMediaStatus(nextMediaStatus);
    if (!finalVideoState.hasFinalVideo) return;
    const asset = finalVideoState.asset;
    current.setCanvasNodes((nodes) => applyFinalVideoMediaStatusToWorkflowNodes(nodes, nextMediaStatus));
    current.setFlowNodes((nodes) =>
      nodes.map((node) => {
        const shouldReceiveFinalMedia = isFinalCompositionNode({ id: node.id, node_type: node.data.kind }) || node.data.kind === "preview" || node.id.includes("preview");
        if (!shouldReceiveFinalMedia) return node;
        const previewAssets = asset ? [asset] : finalVideoState.status === "failed" ? node.data.previewAssets : [];
        return {
          ...node,
          data: {
            ...node.data,
            ...(finalVideoState.status ? { status: finalVideoState.status } : {}),
            outputCount: previewAssets.length,
            previewAssets,
            stale: finalVideoState.status === "completed" ? false : node.data.stale,
            staleReason: finalVideoState.status === "completed" ? null : finalVideoState.reason ?? node.data.staleReason,
          },
        };
      }),
    );
  }

  async function prepareFinalCompositionRun(finalNode: WorkflowNode) {
    const current = argsRef.current;
    const workflowId = current.workflow?.workflow_id;
    if (!workflowId) return null;
    current.setStatus("Checking storyboard video segments...");
    let latestMediaStatus = await refreshMediaStatus(workflowId);
    let readiness = storyboardVideoReadinessFromSources({
      mediaStatus: latestMediaStatus,
      nodes: current.canvasNodes,
      nodeRuns: current.nodeRuns,
    });

    if (!readiness.ready && readiness.pending) {
      current.setStatus(formatStoryboardVideoWaitingStatus(readiness));
      try {
        latestMediaStatus = await api.pollMedia(workflowId, {
          download_media: true,
          compose_when_ready: false,
          wait_until_ready: false,
          interval_seconds: 0,
          max_attempts: 1,
        });
        if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return null;
        current.setMediaStatus(latestMediaStatus);
        applyMediaStatusToCanvas(latestMediaStatus);
      } catch {
        // Keep the preflight on the latest readable media-status result.
      }
    }

    const nodesWithStoryboardMedia = latestMediaStatus ? applyStoryboardMediaStatusToWorkflowNodes(current.canvasNodes, latestMediaStatus) : current.canvasNodes;
    if (latestMediaStatus) current.setCanvasNodes(nodesWithStoryboardMedia);
    readiness = storyboardVideoReadinessFromSources({
      mediaStatus: latestMediaStatus,
      nodes: nodesWithStoryboardMedia,
      nodeRuns: current.nodeRuns,
    });
    const allowBackendSegmentFallback = storyboardSegmentsReadyForFinalComposition(latestMediaStatus);
    if (!readiness.ready && allowBackendSegmentFallback) {
      readiness = {
        ...readiness,
        ready: true,
        pending: false,
        reason: null,
      };
    }

    if (!readiness.ready) {
      current.patchWorkflowNodeState([finalNode.id], { status: "running", stale_reason: readiness.reason ?? "Storyboard video segments are still generating." });
      current.setStatus(formatStoryboardVideoWaitingStatus(readiness));
      return readiness;
    }

    const saved = await current.saveCanvas({ quiet: true, requireBackend: true, nodes: nodesWithStoryboardMedia });
    if (!saved) return null;
    await current.refreshWorkflowNodes(workflowId);
    await current.refreshWorkflowGraph(workflowId, current.nodeRuns);
    const resolvedInputs = await current.refreshSelectedResolvedInputs(finalNode.id, { force: true });
    if (resolvedInputs && !allowBackendSegmentFallback && !resolvedInputsHaveReadyStoryboardSegments(resolvedInputs, readiness)) {
      const nextReadiness = {
        ...readiness,
        ready: false,
        pending: true,
        reason: "Resolved inputs do not include ready storyboard video segments yet.",
      };
      current.patchWorkflowNodeState([finalNode.id], { status: "running", stale_reason: nextReadiness.reason });
      current.setStatus(nextReadiness.reason);
      return nextReadiness;
    }
    current.setStatus("Storyboard video segments ready. Running final composition...");
    return readiness;
  }

  async function pollStoryboardVideoMedia(workflowId: string) {
    const current = argsRef.current;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) {
      await current.syncV2Snapshot(workflowId);
      return null;
    }
    let latestStatus: MediaStatus | null = null;
    const maxAttempts = 40;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (attempt > 0) await sleep(1600);
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return latestStatus;
      try {
        const response = await api.pollMedia(workflowId, {
          download_media: true,
          compose_when_ready: false,
          wait_until_ready: false,
          interval_seconds: 0,
          max_attempts: 1,
        });
        if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return latestStatus;
        latestStatus = response;
        current.setMediaStatus(response);
        applyMediaStatusToCanvas(response);
        if (!shouldPollStoryboardVideoMedia(response)) return response;
      } catch {
        return latestStatus;
      }
    }
    return latestStatus;
  }

  async function refreshMediaStatus(workflowId = argsRef.current.workflow?.workflow_id) {
    const current = argsRef.current;
    if (!workflowId) return null;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) {
      await current.syncV2Snapshot(workflowId);
      return null;
    }
    try {
      const response = await api.mediaStatus(workflowId);
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return null;
      current.setMediaStatus(response);
      applyMediaStatusToCanvas(response);
      return response;
    } catch {
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return null;
      current.setMediaStatus(null);
      return null;
    }
  }

  async function refreshSelectedNodeRun() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before refreshing a node run.");
      return;
    }
    if (!current.selectedPlanNode) {
      current.setStatus("Select a node first.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 quality status is provided by slot and provider task metadata.");
      return;
    }
    const requestWorkflowId = current.workflow.workflow_id;
    current.setStatus(`Refreshing ${current.selectedPlanNode.title}...`);
    try {
      const run = await api.workflowNode(requestWorkflowId, current.selectedPlanNode.id);
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return;
      current.setSelectedNodeRun(run);
      current.applyNodeRunsToCanvas([{ ...run, node_id: run.node_id || current.selectedPlanNode.id }]);
      current.setSelectedResolvedInputs(resolvedInputsFromNodeRun(run));
      await current.refreshSelectedResolvedInputs(current.selectedPlanNode.id, { force: true });
      await current.refreshWorkflowNodes(requestWorkflowId);
      current.setStatus(`${current.selectedPlanNode.title} refreshed`);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Node refresh failed");
    }
  }

  async function reviewSelectedNodeQuality() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate or restore a workflow before reviewing quality.");
      return;
    }
    if (!current.selectedPlanNode) {
      current.setStatus("Select a node first.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 quality status is shown from generated asset metadata.");
      return;
    }
    const selectedPlanNode = current.selectedPlanNode;
    const requestWorkflowId = current.workflow.workflow_id;
    const requestNodeId = selectedPlanNode.id;
    const requestNodeTitle = selectedPlanNode.title;
    current.setQualityReviewingNodeIds((value) => ({ ...value, [requestNodeId]: true }));
    current.setStatus(`Reviewing quality for ${requestNodeTitle}...`);
    try {
      const response = await api.reviewNodeQuality(current.workflow.workflow_id, selectedPlanNode.id);
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return;
      current.setCanvasNodes((nodes) =>
        nodes.map((node) => (node.id === requestNodeId ? mergeQualityReviewResponseIntoNode(node, response) : node)),
      );
      current.setFlowNodes((nodes) =>
        nodes.map((node) => {
          if (node.id !== requestNodeId) return node;
          const mergedNode = mergeQualityReviewResponseIntoNode(
            { ...flowNodeToWorkflowNode(node), output: node.data.output ?? undefined, output_assets: node.data.previewAssets },
            response,
          );
          const previewAssets = mergedNode.output_assets?.length
            ? previewAssetsForCanvasNodeType(node.data.kind, activeWorkflowAssets(mergedNode.output_assets))
            : node.data.previewAssets;
          return {
            ...node,
            data: {
              ...node.data,
              output: mergedNode.output ?? node.data.output ?? null,
              qualitySummary: qualitySummaryForNode(mergedNode),
              previewAssets,
            },
          };
        }),
      );
      current.setSelectedNodeRun((value) =>
        value && isNodeRunForCanvasInstance(value, selectedPlanNode, current.visibleCanvasNodes)
          ? mergeQualityReviewResponseIntoRun(value, response)
          : current.selectedRun && isNodeRunForCanvasInstance(current.selectedRun, selectedPlanNode, current.visibleCanvasNodes)
            ? mergeQualityReviewResponseIntoRun(current.selectedRun, response)
            : value,
      );
      current.setStatus(response.message || `${requestNodeTitle} quality review updated`);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Quality review failed");
    } finally {
      current.setQualityReviewingNodeIds((value) => ({ ...value, [requestNodeId]: false }));
    }
  }

  async function exportEditedVideo() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate or select a workflow before exporting video.");
      return;
    }
    const clips = getTimelineClipCount(current.videoTimeline);
    if (!clips) {
      current.setStatus("No video clips found. Run video nodes or poll media before export.");
      return;
    }
    current.setStatus("Exporting video...");
    try {
      const result = await api.exportVideo({
        workflow_id: current.workflow.workflow_id,
        timeline: current.videoTimeline,
        export_settings: current.exportSettings,
      });
      current.setExportResult(result);
      current.setExportId(result.export_id);
      current.setStatus(`Video export ${result.status}`);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Video export failed");
    }
  }

  async function refreshVideoExport() {
    const current = argsRef.current;
    const id = current.exportId.trim();
    if (!id) {
      current.setStatus("Enter an export id first.");
      return;
    }
    current.setStatus(`Refreshing export ${id}...`);
    try {
      const result = await api.videoExport(id);
      current.setExportResult(result);
      current.setStatus(`Export ${result.status}`);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Export refresh failed");
    }
  }

  async function loadFinalCompositionTimeline(workflowId: string, options: FinalCompositionTimelineLoadOptions = {}) {
    const current = argsRef.current;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) {
      current.setStatus("V2 final composition uses the V2 timeline item and slot APIs.");
      return;
    }
    current.timelineLoadStarted();
    try {
      const response = await api.getFinalCompositionTimeline(workflowId);
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      current.applyFinalCompositionTimelineResponse(workflowId, response, options);
      await loadFinalCompositionCandidateHistory(workflowId);
    } catch (error) {
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      current.timelineLoadFailed(finalCompositionErrorMessage(error));
    }
  }

  async function loadFinalCompositionCandidateHistory(workflowId: string) {
    const current = argsRef.current;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) return;
    const targetAsset = finalCompositionTimelineTargetAsset(workflowId);
    const revisionKey = localRevisionStateKey(workflowId, "final-composition", targetAsset);
    try {
      const revisions = await api.listNodeRevisions(workflowId, "final-composition");
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      const finalRevisions = revisions.revisions.filter((revision) => {
        const semanticType = revision.semantic_type ?? revision.revision?.semantic_type ?? "";
        return semanticType === "final_video";
      });
      current.updateLocalRevisionCardState(revisionKey, {
        revisions: finalRevisions,
        candidates: pendingVisibleRevisionCandidates(finalRevisions),
        promptMetadata: latestLocalRevisionPromptMetadata(finalRevisions),
      });
    } catch {
      // The asset history endpoint below remains the canonical source for active/history assets.
    }
    await current.loadLocalAssetHistory(workflowId, "final-composition", targetAsset);
  }

  async function saveFinalCompositionTimeline() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate or restore a workflow before saving the timeline.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 final composition uses V2 timeline item APIs.");
      return;
    }
    const workflowId = current.workflow.workflow_id;
    const finalCompositionTimelineDraft = current.finalCompositionTimelineState.draft;
    if (!finalCompositionTimelineDraft) {
      current.setStatus("Final composition timeline is not loaded yet.");
      return;
    }
    current.timelineSaveStarted();
    try {
      const response = await api.saveFinalCompositionTimeline(workflowId, {
        timeline: finalCompositionTimelineDraft,
        expected_version: current.finalCompositionTimelineBaselineVersion ?? finalCompositionTimelineDraft.version,
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      current.applyFinalCompositionTimelineResponse(workflowId, response);
      current.setStatus("Final composition timeline saved.");
    } catch (error) {
      const code = error instanceof ApiError ? apiErrorCode(error.payload) : "";
      if (code === "timeline_version_conflict") {
        current.setFinalCompositionTimelineConflict("Timeline was updated on the backend. Review the refreshed timeline, then retry save.");
        current.timelineSaveFailed(finalCompositionErrorMessage(error));
        await loadFinalCompositionTimeline(workflowId, { preserveDraft: true, eventDirty: true });
        current.setStatus("Timeline conflict detected. Review the refreshed timeline before saving again.");
        return;
      }
      current.timelineSaveFailed(finalCompositionErrorMessage(error));
      current.setStatus(finalCompositionErrorMessage(error));
    }
  }

  async function renderFinalCompositionTimeline() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate or restore a workflow before rendering final composition.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 final composition uses V2 candidate generation APIs.");
      return;
    }
    const finalCompositionTimelineDraft = current.finalCompositionTimelineState.draft;
    if (!finalCompositionTimelineDraft) {
      current.setStatus("Final composition timeline is not loaded yet.");
      return;
    }
    const disabledReason = finalCompositionRenderDisabledReason(finalCompositionTimelineDraft, current.finalCompositionTimelineState);
    if (disabledReason) {
      current.setStatus(disabledReason);
      return;
    }
    const workflowId = current.workflow.workflow_id;
    current.timelineRenderStarted();
    let renderFailed = false;
    try {
      const revision = await api.renderFinalCompositionTimeline(workflowId, {
        timeline_id: finalCompositionTimelineDraft.timeline_id,
        timeline_version: finalCompositionTimelineDraft.version,
        acceptance_policy: "manual_candidate",
      });
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      const targetAsset = finalCompositionTimelineTargetAsset(workflowId);
      const revisionKey = localRevisionStateKey(workflowId, "final-composition", targetAsset);
      if (revision.revision_id) current.applyLocalRevisionState(revisionKey, revision);
      await loadFinalCompositionCandidateHistory(workflowId);
      await current.refreshWorkflowGraph(workflowId);
      current.setStatus("Final render queued as a candidate.");
    } catch (error) {
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return;
      renderFailed = true;
      current.timelineRenderFailed(finalCompositionErrorMessage(error));
      current.setStatus(finalCompositionErrorMessage(error));
    } finally {
      if (!renderFailed && shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) {
        current.timelineRenderFinished();
      }
    }
  }

  return {
    actions: {
      prepareFinalCompositionRun,
      pollStoryboardVideoMedia,
      refreshMediaStatus,
      refreshSelectedNodeRun,
      reviewSelectedNodeQuality,
      exportEditedVideo,
      refreshVideoExport,
      loadFinalCompositionTimeline,
      loadFinalCompositionCandidateHistory,
      saveFinalCompositionTimeline,
      renderFinalCompositionTimeline,
      finalCompositionTimelineTargetAsset,
      applyMediaStatusToCanvas,
    },
  };
}

export function finalCompositionTimelineTargetAsset(workflowId: string): UploadedAsset {
  return {
    asset_id: "final-video",
    asset_type: "video",
    asset_role: "reference",
    filename: "Final video",
    mime_type: "video/mp4",
    local_path: "",
    entity_id: workflowId,
    semantic_type: "final_video",
  };
}

function apiErrorCode(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  if (typeof record.code === "string") return record.code;
  if (typeof record.error === "string") return record.error;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const detailRecord = detail as Record<string, unknown>;
    return String(detailRecord.code ?? detailRecord.error ?? detailRecord.type ?? "");
  }
  return "";
}
