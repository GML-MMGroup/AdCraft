import { useEffect, useRef } from "react";
import { api } from "../../../api/client.ts";
import type {
  AssetLibraryReference,
  AssetLibraryEntitySummary,
  NodeRunResult,
  UploadedAsset,
  WorkflowAssetHistoryResponse,
  WorkflowGraph,
  WorkflowNode,
  WorkflowRevisionState,
} from "../../../types.ts";
import { isV2WorkflowId } from "../../../workflow-v2/pageAdapter.ts";
import {
  localRevisionEntityId,
  localRevisionRequestForAsset,
  localRevisionSemanticType,
  localRevisionStateKey,
} from "../../../workflow/localRevision.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import { libraryEntitiesToReferences } from "./assetLibraryReferenceModel.ts";
import {
  isLocalRevisionCompletedStatus,
  isLocalRevisionTerminalStatus,
  latestLocalRevisionPromptMetadata,
  localRevisionPromptMetadataFromState,
  localRevisionStatusText,
} from "./localRevisionViewModel.ts";
import type { LocalRevisionCardState, RevisionCandidateBusyState } from "./useWorkflowAssetOperations.ts";
import {
  isPendingVisibleRevisionCandidate,
  pendingVisibleRevisionCandidates,
} from "../../../workflow/localRevision.ts";
import { isRevisionCandidateQualityFailed } from "../quality/qualityReviewViewModel.ts";
import { sleep } from "../page/workflowPageFormatters.ts";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

type StartLocalAssetRevisionOptions = {
  mode?: "regenerate_asset" | "select_existing_asset";
  instruction?: string | null;
  selectedAssetId?: string | null;
  assetReferences?: AssetLibraryReference[];
  libraryEntityIds?: string[];
};

type LocalRevisionOperationsArgs = {
  workflow: WorkflowGraph | null | undefined;
  selectedPlanNode: WorkflowNode | null | undefined;
  revisionTarget: UploadedAsset | null;
  revisionInstruction: string;
  revisionLibraryEntities: AssetLibraryEntitySummary[];
  revisionPrimaryReferenceIds: string[];
  activeWorkflowIdRef: React.MutableRefObject<string | null>;
  currentWorkflowIsV2: () => boolean;
  canShowLocalRevisionActions: (node?: WorkflowNode | null) => boolean;
  getWorkflowNodeType: (node: WorkflowNode) => string;
  setStatus: StateSetter<string>;
  setRevisionInstruction: StateSetter<string>;
  setRevisionTarget: StateSetter<UploadedAsset | null>;
  setRevisionLibraryEntities: StateSetter<AssetLibraryEntitySummary[]>;
  setRevisionPrimaryReferenceIds: StateSetter<string[]>;
  setRevisionHistoryTarget: StateSetter<UploadedAsset | null>;
  setLocalRevisionByKey: StateSetter<Record<string, LocalRevisionCardState>>;
  setRevisionCandidateBusyById: StateSetter<RevisionCandidateBusyState>;
  setQualityOverrideRevisionId: StateSetter<string | null>;
  setSelectedNodeRun: StateSetter<NodeRunResult | null>;
  saveCanvas: (options?: { quiet?: boolean; requireBackend?: boolean }) => Promise<boolean>;
  refreshWorkflowNodes: (workflowId: string) => Promise<unknown>;
  refreshWorkflowGraph: (workflowId: string) => Promise<unknown>;
  refreshMediaStatus: (workflowId: string) => Promise<unknown>;
  refreshSelectedResolvedInputs: (nodeId: string, options?: { force?: boolean }) => Promise<unknown>;
  applyNodeRunsToCanvas: (runs: NodeRunResult[]) => void;
  noteAffected: (nodes?: string[]) => void;
};

export function useLocalRevisionOperations(args: LocalRevisionOperationsArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  function updateLocalRevisionCardState(key: string, patch: Partial<LocalRevisionCardState>) {
    argsRef.current.setLocalRevisionByKey((current) => ({
      ...current,
      [key]: {
        ...current[key],
        key,
        ...patch,
        updatedAt: new Date().toISOString(),
      },
    }));
  }

  function applyLocalRevisionState(key: string, revision: WorkflowRevisionState) {
    const candidates = isPendingVisibleRevisionCandidate(revision) ? [revision] : [];
    updateLocalRevisionCardState(key, {
      revisionId: revision.revision_id,
      status: revision.status,
      message: revision.message,
      error: revision.error,
      activeAsset: revision.active_asset ?? null,
      candidates,
      assets: revision.assets,
      history: revision.history ?? revision.assets,
      affectedDownstreamNodes: revision.affected_downstream_nodes,
      promptMetadata: localRevisionPromptMetadataFromState(revision),
    });
  }

  async function submitAssetRevision() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      current.setStatus("Generate a workflow before revising an asset.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 assets use slot working versions instead of V1 local revisions.");
      return;
    }
    if (!current.selectedPlanNode || !current.revisionTarget) {
      current.setStatus("Select an output asset first.");
      return;
    }
    const instruction = current.revisionInstruction.trim();
    if (!instruction) {
      current.setStatus("Enter a local revision instruction first.");
      return;
    }
    const references = libraryEntitiesToReferences(
      current.revisionLibraryEntities,
      {
        target_node_id: current.selectedPlanNode.id,
        target_node_type: current.getWorkflowNodeType(current.selectedPlanNode),
        target_entity_id: localRevisionEntityId(current.revisionTarget),
      },
      { primaryReferenceIds: new Set(current.revisionPrimaryReferenceIds) },
    );
    try {
      await startLocalAssetRevision(current.revisionTarget, {
        mode: "regenerate_asset",
        instruction,
        assetReferences: references,
        libraryEntityIds: current.revisionLibraryEntities.map((entity) => entity.entity_id),
      });
      current.setRevisionInstruction("");
      current.setRevisionTarget(null);
      current.setRevisionLibraryEntities([]);
      current.setRevisionPrimaryReferenceIds([]);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Asset revision failed");
    }
  }

  async function startLocalAssetRevision(asset: UploadedAsset, options: StartLocalAssetRevisionOptions = {}) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a workflow and select a node before revising an asset.");
      return null;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 assets use slot working versions instead of V1 local revisions.");
      return null;
    }
    if (!current.canShowLocalRevisionActions(current.selectedPlanNode)) {
      current.setStatus("This node does not support asset-level revision.");
      return null;
    }

    const revisionKey = localRevisionStateKey(current.workflow.workflow_id, current.selectedPlanNode.id, asset);
    try {
      const saved = await current.saveCanvas({ quiet: true, requireBackend: true });
      if (!saved) return null;

      const mode = options.mode ?? "regenerate_asset";
      updateLocalRevisionCardState(revisionKey, {
        revisionId: undefined,
        status: "queued",
        message: mode === "select_existing_asset" ? "Switching to selected asset version..." : "Asset revision queued...",
        error: null,
        historyError: null,
      });

      const payload = localRevisionRequestForAsset(current.selectedPlanNode, asset, {
        mode,
        instruction: options.instruction,
        selected_asset_id: options.selectedAssetId,
        asset_references: options.assetReferences ?? [],
      });
      if (options.libraryEntityIds?.length) payload.library_entity_ids = options.libraryEntityIds;

      const created = await api.createNodeRevision(current.workflow.workflow_id, current.selectedPlanNode.id, payload);
      applyLocalRevisionState(revisionKey, created);
      current.setStatus(localRevisionStatusText(created, asset));
      if (!created.revision_id) return created;
      return pollLocalAssetRevision(current.workflow.workflow_id, current.selectedPlanNode.id, created.revision_id, revisionKey, asset);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Asset revision failed";
      updateLocalRevisionCardState(revisionKey, { status: "failed", error: message, message });
      current.setStatus(message);
      return null;
    }
  }

  async function pollLocalAssetRevision(workflowId: string, nodeId: string, revisionId: string, revisionKey: string, targetAsset: UploadedAsset) {
    const current = argsRef.current;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) {
      current.setStatus("V2 revision polling uses slot runtime and version history.");
      return null;
    }
    let latest: WorkflowRevisionState | null = null;
    for (let attempt = 0; attempt < 45; attempt += 1) {
      if (attempt > 0) await sleep(latest?.status === "waiting" ? 2500 : 1500);
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return latest;
      latest = await api.getNodeRevision(workflowId, nodeId, revisionId);
      if (!shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) return latest;
      applyLocalRevisionState(revisionKey, latest);
      current.setStatus(localRevisionStatusText(latest, targetAsset));

      if (!isLocalRevisionTerminalStatus(latest.status)) continue;
      if (isLocalRevisionCompletedStatus(latest.status)) {
        if (isPendingVisibleRevisionCandidate(latest)) {
          await loadLocalAssetHistory(workflowId, nodeId, targetAsset);
          return latest;
        }
        try {
          const run = await api.workflowNode(workflowId, nodeId);
          if (shouldApplyWorkflowScopedResult(workflowId, current.activeWorkflowIdRef.current)) {
            current.setSelectedNodeRun(run);
            current.applyNodeRunsToCanvas([{ ...run, node_id: run.node_id || nodeId }]);
          }
        } catch {
          // The graph refresh below is the canonical fallback.
        }
        await current.refreshWorkflowNodes(workflowId);
        await current.refreshWorkflowGraph(workflowId);
        await current.refreshMediaStatus(workflowId);
        await current.refreshSelectedResolvedInputs(nodeId, { force: true });
        await loadLocalAssetHistory(workflowId, nodeId, targetAsset);
        current.noteAffected(latest.affected_downstream_nodes);
      }
      return latest;
    }
    updateLocalRevisionCardState(revisionKey, {
      status: "waiting",
      message: "Still waiting for media revision results...",
    });
    return latest;
  }

  async function loadLocalAssetHistory(workflowId: string, nodeId: string, asset: UploadedAsset) {
    const current = argsRef.current;
    if (isV2WorkflowId(workflowId) || current.currentWorkflowIsV2()) {
      current.setStatus("V2 asset history is available from slot version history.");
      return null;
    }
    const revisionKey = localRevisionStateKey(workflowId, nodeId, asset);
    updateLocalRevisionCardState(revisionKey, { historyLoading: true, historyError: null });
    try {
      const result: WorkflowAssetHistoryResponse = await api.getNodeAssetHistory(workflowId, nodeId, {
        entity_id: localRevisionEntityId(asset),
        semantic_type: localRevisionSemanticType(asset),
      });
      updateLocalRevisionCardState(revisionKey, {
        historyLoading: false,
        historyError: null,
        activeAsset: result.active_asset ?? null,
        candidates: pendingVisibleRevisionCandidates(result.revisions ?? []),
        assets: result.assets,
        history: result.history ?? result.assets,
        revisions: result.revisions,
        promptMetadata: latestLocalRevisionPromptMetadata(result.revisions),
      });
      return result;
    } catch (error) {
      updateLocalRevisionCardState(revisionKey, {
        historyLoading: false,
        historyError: error instanceof Error ? error.message : "Asset history failed to load",
      });
      return null;
    }
  }

  function openLocalAssetHistory(asset: UploadedAsset) {
    const current = argsRef.current;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 asset history is available from slot version history.");
      return;
    }
    current.setRevisionHistoryTarget(asset);
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) return;
    void loadLocalAssetHistory(current.workflow.workflow_id, current.selectedPlanNode.id, asset);
  }

  async function selectLocalAssetHistoryVersion(targetAsset: UploadedAsset, selectedAsset: UploadedAsset) {
    await startLocalAssetRevision(targetAsset, {
      mode: "select_existing_asset",
      selectedAssetId: selectedAsset.asset_id,
    });
  }

  async function acceptLocalRevisionCandidate(targetAsset: UploadedAsset, revision: WorkflowRevisionState, overrideQualityFailure = false) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode || !revision.revision_id) return;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 candidate acceptance uses slot version selection.");
      return;
    }
    if (!overrideQualityFailure && isRevisionCandidateQualityFailed(revision)) {
      current.setQualityOverrideRevisionId(revision.revision_id);
      return;
    }

    current.setRevisionCandidateBusyById((busy) => ({ ...busy, [revision.revision_id]: "accept" }));
    try {
      const accepted = await api.acceptNodeRevision(current.workflow.workflow_id, current.selectedPlanNode.id, revision.revision_id, {
        note: "",
        override_quality_failure: overrideQualityFailure,
      });
      const revisionKey = localRevisionStateKey(current.workflow.workflow_id, current.selectedPlanNode.id, targetAsset);
      applyLocalRevisionState(revisionKey, accepted);
      current.setQualityOverrideRevisionId(null);
      await current.refreshWorkflowNodes(current.workflow.workflow_id);
      await current.refreshWorkflowGraph(current.workflow.workflow_id);
      await current.refreshMediaStatus(current.workflow.workflow_id);
      await current.refreshSelectedResolvedInputs(current.selectedPlanNode.id, { force: true });
      await loadLocalAssetHistory(current.workflow.workflow_id, current.selectedPlanNode.id, targetAsset);
      current.noteAffected(accepted.affected_downstream_nodes);
      current.setStatus("Local revision candidate accepted.");
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Accepting revision candidate failed");
    } finally {
      current.setRevisionCandidateBusyById((busy) => ({ ...busy, [revision.revision_id]: undefined }));
    }
  }

  async function rejectLocalRevisionCandidate(targetAsset: UploadedAsset, revision: WorkflowRevisionState) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode || !revision.revision_id) return;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 candidate rejection uses slot working-version discard.");
      return;
    }
    current.setRevisionCandidateBusyById((busy) => ({ ...busy, [revision.revision_id]: "reject" }));
    try {
      const rejected = await api.rejectNodeRevision(current.workflow.workflow_id, current.selectedPlanNode.id, revision.revision_id, {
        reason: "",
      });
      const revisionKey = localRevisionStateKey(current.workflow.workflow_id, current.selectedPlanNode.id, targetAsset);
      applyLocalRevisionState(revisionKey, rejected);
      current.setQualityOverrideRevisionId((value) => (value === revision.revision_id ? null : value));
      await loadLocalAssetHistory(current.workflow.workflow_id, current.selectedPlanNode.id, targetAsset);
      if (rejected.affected_downstream_nodes?.length) current.noteAffected(rejected.affected_downstream_nodes);
      current.setStatus("Local revision candidate rejected.");
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Rejecting revision candidate failed");
    } finally {
      current.setRevisionCandidateBusyById((busy) => ({ ...busy, [revision.revision_id]: undefined }));
    }
  }

  return {
    actions: {
      updateLocalRevisionCardState,
      applyLocalRevisionState,
      submitAssetRevision,
      startLocalAssetRevision,
      pollLocalAssetRevision,
      loadLocalAssetHistory,
      openLocalAssetHistory,
      selectLocalAssetHistoryVersion,
      acceptLocalRevisionCandidate,
      rejectLocalRevisionCandidate,
    },
  };
}
