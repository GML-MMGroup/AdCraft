import { useEffect, useRef, type Dispatch, type RefObject, type SetStateAction } from "react";
import { api } from "../../../api/client";
import { v2Api } from "../../../api/v2Client";
import type {
  AdRequest,
  GraphValidationResult,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeVersionsResponse,
  WorkflowVariable,
} from "../../../types";
import type { AssetVersionV2, SlotVersionsResponseV2, WorkflowV2 } from "../../../types-v2";
import { validateCanvas as validateStoredCanvas } from "../../../workflow/connectionValidation";
import { workflowAdRequest } from "../../../workflow/adRequest";
import { dedupeAssets } from "../../../workflow/assets";
import { isStoryboardVideoNode, shouldPollStoryboardVideoMedia } from "../../../workflow/mediaSegments";
import {
  createNodeRunMap,
  findNodeRunForWorkflowNode,
  mergeWorkflowNodesWithRuns,
} from "../../../workflow/runtimeResults";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards";
import { clearSnapshot, LOCAL_WORKFLOW_ID } from "../page/workflowSnapshotModel";
import { textFromUnknown } from "../page/workflowPageFormatters";
import { workflowV2ToWorkflowGraph } from "../../../workflow-v2/pageAdapter";
import { findMissingV2SlotAssetRefs } from "../../../workflow-v2/assets";
import type { WorkflowV2PageModel } from "../../../workflow-v2/pageAdapter";
import {
  activeWorkflowAssets,
  previewAssetsForCanvasNodeType,
  qualitySummaryFromOutput,
} from "../assets/workflowAssetPreviewModel";
import {
  assertV1ApiAllowedForWorkflow,
  buildV2NodeVersions,
  buildV2ResolvedInputs,
  isCurrentWorkflowV2,
  v2AssetVersionsForDebug,
  v2ItemsForDebug,
  v2SlotsForDebug,
} from "../v2/v2DebugViewModel";
import {
  flowNodeToWorkflowNode,
  layoutNodes,
  mapWorkflowEdges,
  mapWorkflowNodes,
  syncWorkflowNodePositions,
} from "../canvas/workflowCanvasModel";
import type { CanvasEdge, CanvasNode } from "../types";
import {
  firstVisibleWorkflowNodeId,
  isUserVisibleWorkflowNode,
} from "../../../workflow/visibility";
import {
  firstIssueMessage,
  normalizeGraphValidationResult,
} from "./workflowGraphValidationModel";
import {
  hasActiveOutputFailure,
  isStrictReferenceFailure,
  normalizeRunAssets,
} from "../runtime/workflowRunOutputViewModel";
import { mergeResolvedInputContext } from "../runtime/resolvedInputsViewModel";
import {
  isSuccessfulNodeStatus,
  mergeOutputPreservingQuality,
} from "../quality/qualityReviewViewModel";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

type V2WorkflowAssetsAdapter = {
  refreshWorkflowAssets: (reason: string, workflowId: string, baseAssetVersions?: AssetVersionV2[]) => Promise<AssetVersionV2[]>;
};

export type WorkflowGraphSyncControllerArgs = {
  workflow: WorkflowGraph | null | undefined;
  workflowV2Model: WorkflowV2PageModel;
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  nodeRunByType: Map<string, NodeRunResult>;
  selectedAssets: UploadedAsset[];
  v2SlotVersionsById: Record<string, SlotVersionsResponseV2 | undefined>;
  activeWorkflowIdRef: RefObject<string | null>;
  reactFlow: { fitView: (options?: { padding?: number }) => void } | null;
  v2WorkflowAssets: V2WorkflowAssetsAdapter;
  syncV2RuntimeSnapshot: (workflowId: string) => Promise<unknown>;
  refreshWorkflowNodes: (workflowId: string) => Promise<unknown>;
  refreshMediaStatus: (workflowId: string) => Promise<unknown>;
  setWorkflow: StateSetter<WorkflowGraph | null>;
  setAdRequest: StateSetter<AdRequest>;
  setWorkflowVariables: StateSetter<WorkflowVariable[]>;
  setCanvasNodes: StateSetter<WorkflowNode[]>;
  setFlowNodes: StateSetter<CanvasNode[]>;
  setFlowEdges: StateSetter<CanvasEdge[]>;
  setSelectedNodeId: StateSetter<string>;
  setDetailsOpen: (value: boolean) => void;
  setSavedAt: StateSetter<string | null>;
  setV2SlotVersionsById: StateSetter<Record<string, SlotVersionsResponseV2 | undefined>>;
  setValidationResult: StateSetter<GraphValidationResult | null>;
  setStatus: StateSetter<string>;
  setAffectedNodes: StateSetter<string[]>;
};

export function useWorkflowGraphSyncController(args: WorkflowGraphSyncControllerArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  async function applyWorkflowGraph(nextWorkflow: WorkflowGraph) {
    const current = argsRef.current;
    current.activeWorkflowIdRef.current = nextWorkflow.workflow_id;
    clearSnapshot(nextWorkflow.workflow_id);
    current.setWorkflow(nextWorkflow);
    syncWorkflowAdRequest(nextWorkflow);
    current.setWorkflowVariables(nextWorkflow.variables ?? []);
    const nextFlowNodes = mapWorkflowNodes(nextWorkflow.nodes, current.nodeRunByType, []);
    const nextFlowEdges = mapWorkflowEdges(nextWorkflow.edges, nextFlowNodes);
    const nextLayoutNodes = layoutNodes(nextFlowNodes, nextFlowEdges);
    current.setCanvasNodes(syncWorkflowNodePositions(nextWorkflow.nodes, nextLayoutNodes));
    current.setFlowNodes(nextLayoutNodes);
    current.setFlowEdges(nextFlowEdges);
    current.setSelectedNodeId(firstVisibleWorkflowNodeId(nextWorkflow.nodes));
    current.setDetailsOpen(true);
    await current.refreshWorkflowNodes(nextWorkflow.workflow_id);
    await current.refreshMediaStatus(nextWorkflow.workflow_id);
    window.setTimeout(() => current.reactFlow?.fitView({ padding: 0.28 }), 0);
  }

  async function applyWorkflowV2(
    nextWorkflow: WorkflowV2,
    options: { refreshAssetsReason?: string | false; preserveViewport?: boolean; refreshRuntime?: boolean } = {},
  ) {
    const current = argsRef.current;
    const graph = workflowV2ToWorkflowGraph(nextWorkflow);
    current.activeWorkflowIdRef.current = nextWorkflow.workflow_id;
    clearSnapshot(nextWorkflow.workflow_id);
    current.setWorkflow(graph);
    syncWorkflowAdRequest(graph);
    current.setWorkflowVariables(graph.variables ?? []);
    const nextFlowNodes = mapWorkflowNodes(graph.nodes, current.nodeRunByType, options.preserveViewport ? current.flowNodes : []);
    const nextFlowEdges = mapWorkflowEdges(graph.edges, nextFlowNodes);
    const nextLayoutNodes = options.preserveViewport ? nextFlowNodes : layoutNodes(nextFlowNodes, nextFlowEdges);
    current.setCanvasNodes(syncWorkflowNodePositions(graph.nodes, nextLayoutNodes));
    current.setFlowNodes(nextLayoutNodes);
    current.setFlowEdges(nextFlowEdges);
    current.setSelectedNodeId((selectedNodeId) =>
      options.preserveViewport && selectedNodeId && graph.nodes.some((node) => node.id === selectedNodeId && isUserVisibleWorkflowNode(node))
        ? selectedNodeId
        : firstVisibleWorkflowNodeId(graph.nodes),
    );
    if (!options.preserveViewport) {
      current.setDetailsOpen(true);
    }
    const refreshAssetsReason = options.refreshAssetsReason ?? "apply-workflow";
    if (refreshAssetsReason) {
      await refreshV2AssetsAndRetryMissing(nextWorkflow.workflow_id, refreshAssetsReason, nextWorkflow);
    }
    if (options.refreshRuntime !== false) await current.syncV2RuntimeSnapshot(nextWorkflow.workflow_id);
    if (!options.preserveViewport) {
      window.setTimeout(() => current.reactFlow?.fitView({ padding: 0.28 }), 0);
    }
  }

  async function refreshV2WorkflowGraph(
    id: string,
    options: { refreshRuntime?: boolean; refreshAssets?: boolean } = {},
  ) {
    try {
      const nextWorkflow = await v2Api.workflow(id);
      const current = argsRef.current;
      if (!shouldApplyWorkflowScopedResult(id, current.activeWorkflowIdRef.current)) return null;
      const graph = workflowV2ToWorkflowGraph(nextWorkflow);
      await applyWorkflowV2(nextWorkflow, {
        refreshAssetsReason: false,
        preserveViewport: true,
        refreshRuntime: options.refreshRuntime,
      });
      argsRef.current.setSavedAt(graph.updated_at ?? new Date().toISOString());
      if (options.refreshAssets !== false) {
        await refreshV2AssetsAndRetryMissing(id, "workflow-refresh", nextWorkflow);
      }
      return nextWorkflow;
    } catch {
      return null;
    }
  }

  function refreshV2WorkflowStructure(id: string) {
    return refreshV2WorkflowGraph(id, { refreshRuntime: false, refreshAssets: false });
  }

  async function refreshV2AssetsAndRetryMissing(
    workflowId: string,
    reason: string,
    workflowForSlots?: WorkflowV2 | null,
  ) {
    const current = argsRef.current;
    const hydratedAssets = await current.v2WorkflowAssets.refreshWorkflowAssets(
      reason,
      workflowId,
      workflowForSlots?.asset_versions ?? [],
    );
    const missing = workflowForSlots ? findMissingV2SlotAssetRefs(workflowForSlots.slots ?? [], hydratedAssets) : [];
    if (missing.length > 0) {
      console.warn("[V2 assets] Missing slot asset refs after refresh", {
        workflowId,
        reason,
        missing,
      });
      return current.v2WorkflowAssets.refreshWorkflowAssets(
        `${reason}:missing-retry`,
        workflowId,
        workflowForSlots?.asset_versions ?? [],
      );
    }
    return hydratedAssets;
  }

  function currentWorkflowIsV2() {
    const current = argsRef.current;
    return isCurrentWorkflowV2(current.workflow, current.workflowV2Model.isV2);
  }

  function assertNotV2WorkflowForV1Api(workflowId: string, operation: string) {
    assertV1ApiAllowedForWorkflow(workflowId, operation, currentWorkflowIsV2());
  }

  async function loadV2ResolvedInputs(requestWorkflowId: string, nodeId: string): Promise<ResolvedNodeInputs | null> {
    const current = argsRef.current;
    if (!currentWorkflowIsV2()) return null;
    const workflowV2 = current.workflowV2Model.workflowV2;
    const items = v2ItemsForDebug(current.workflow, workflowV2, nodeId);
    const slots = v2SlotsForDebug(current.workflow, workflowV2, nodeId);
    const assetVersions = v2AssetVersionsForDebug(current.workflow, workflowV2, nodeId);
    return buildV2ResolvedInputs({
      workflowId: requestWorkflowId,
      nodeId,
      items,
      slots,
      assetVersions,
      runtime: workflowV2?.runtime ?? current.workflow?.metadata?.v2_runtime ?? null,
    });
  }

  async function loadV2NodeVersions(requestWorkflowId: string, nodeId: string): Promise<WorkflowNodeVersionsResponse> {
    const current = argsRef.current;
    if (!currentWorkflowIsV2()) return { workflow_id: requestWorkflowId, node_id: nodeId, versions: [] };
    const workflowV2 = current.workflowV2Model.workflowV2;
    const slots = v2SlotsForDebug(current.workflow, workflowV2, nodeId);
    const fetched = await Promise.all(
      slots.map(async (slot) => current.v2SlotVersionsById[slot.slot_id] ?? v2Api.slotVersions(requestWorkflowId, slot.slot_id).catch(() => null)),
    );
    const fetchedBySlotId: Record<string, SlotVersionsResponseV2> = {};
    fetched.forEach((response, index) => {
      if (response) fetchedBySlotId[slots[index].slot_id] = response;
    });
    if (Object.keys(fetchedBySlotId).length) {
      current.setV2SlotVersionsById((existing) => ({ ...existing, ...fetchedBySlotId }));
    }
    return {
      workflow_id: requestWorkflowId,
      ...buildV2NodeVersions({
        nodeId,
        slots,
        assetVersions: v2AssetVersionsForDebug(current.workflow, workflowV2, nodeId),
        fetched,
      }),
    };
  }

  async function refreshWorkflowGraph(id = argsRef.current.workflow?.workflow_id, runtimeRuns?: NodeRunResult[]) {
    const current = argsRef.current;
    if (!id || id === LOCAL_WORKFLOW_ID) return null;
    if (currentWorkflowIsV2()) return refreshV2WorkflowGraph(id);
    try {
      const graph = await api.getWorkflow(id);
      if (!shouldApplyWorkflowScopedResult(id, current.activeWorkflowIdRef.current)) return null;
      const runtimeRunMap = runtimeRuns ? createNodeRunMap(runtimeRuns) : current.nodeRunByType;
      const graphNodes = mergeWorkflowNodesWithRuns(graph.nodes, runtimeRunMap);
      const hydratedGraph = { ...graph, nodes: graphNodes };
      current.setWorkflow(hydratedGraph);
      syncWorkflowAdRequest(hydratedGraph);
      current.setCanvasNodes(graphNodes);
      current.setWorkflowVariables(graph.variables ?? []);
      current.setFlowNodes((existing) => {
        const nextFlowNodes = mapWorkflowNodes(graphNodes, runtimeRunMap, existing);
        current.setFlowEdges(mapWorkflowEdges(graph.edges, nextFlowNodes));
        return nextFlowNodes;
      });
      current.setSelectedNodeId((selectedNodeId) =>
        selectedNodeId && graphNodes.some((node) => node.id === selectedNodeId && isUserVisibleWorkflowNode(node))
          ? selectedNodeId
          : firstVisibleWorkflowNodeId(graphNodes),
      );
      current.setSavedAt(graph.updated_at ?? new Date().toISOString());
      return hydratedGraph;
    } catch {
      return null;
    }
  }

  async function validateBackendGraph(options?: { quiet?: boolean }) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) {
      const local = validateStoredCanvas(current.flowNodes, current.flowEdges);
      const result: GraphValidationResult = {
        valid: local.ok,
        errors: local.ok ? [] : [{ level: "error", code: "local_validation", message: local.message }],
        warnings: [],
      };
      current.setValidationResult(result);
      if (!options?.quiet) current.setStatus(local.ok ? "Local graph is valid" : local.message);
      return result;
    }
    if (currentWorkflowIsV2()) {
      const result: GraphValidationResult = {
        valid: true,
        errors: [],
        warnings: [{ level: "info", code: "workflow_v2_validation", message: "V2 workflow validation is enforced by backend item and slot contracts." }],
      };
      current.setValidationResult(result);
      if (!options?.quiet) current.setStatus("V2 workflow uses backend item and slot validation.");
      return result;
    }
    try {
      const result = normalizeGraphValidationResult(await api.validateWorkflow(current.workflow.workflow_id));
      current.setValidationResult(result);
      if (!options?.quiet) current.setStatus(result.valid ? "Backend graph validation passed" : firstIssueMessage(result.errors) ?? "Graph validation failed");
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Backend validation failed";
      const result: GraphValidationResult = {
        valid: false,
        errors: [{ level: "error", code: "backend_validation_failed", message }],
        warnings: [],
      };
      current.setValidationResult(result);
      if (!options?.quiet) current.setStatus(message);
      return result;
    }
  }

  function patchWorkflowNodeState(nodeIds: string[] | Set<string>, patch: Partial<WorkflowNode>) {
    const current = argsRef.current;
    const ids = nodeIds instanceof Set ? nodeIds : new Set(nodeIds);
    const nextPatch = patch.output_assets ? { ...patch, output_assets: dedupeAssets(patch.output_assets) } : patch;
    current.setCanvasNodes((existing) => existing.map((node) => (ids.has(node.id) ? { ...node, ...nextPatch } : node)));
    current.setFlowNodes((existing) =>
      existing.map((node) => {
        if (!ids.has(node.id)) return node;
        const outputAssets = nextPatch.output_assets ?? [];
        const hasOutputAssetPatch = nextPatch.output_assets !== undefined;
        return {
          ...node,
          data: {
            ...node.data,
            status: nextPatch.status ?? node.data.status,
            version: nextPatch.version ?? node.data.version,
            locked: nextPatch.locked ?? node.data.locked,
            stale: nextPatch.stale ?? node.data.stale,
            staleReason: nextPatch.stale_reason !== undefined ? nextPatch.stale_reason : node.data.staleReason,
            contentPreview: textFromUnknown(nextPatch.output) || textFromUnknown(nextPatch.content) || node.data.contentPreview,
            outputCount: hasOutputAssetPatch ? outputAssets.length : nextPatch.output ? 1 : node.data.outputCount,
            previewAssets: hasOutputAssetPatch ? previewAssetsForCanvasNodeType(node.data.kind, outputAssets) : node.data.previewAssets,
          },
        };
      }),
    );
  }

  function markNodesStale(nodeIds: string[], reason = "Upstream change") {
    if (!nodeIds.length) return;
    patchWorkflowNodeState(nodeIds, { stale: true, stale_reason: reason });
  }

  function noteAffected(nodes?: string[]) {
    const current = argsRef.current;
    current.setAffectedNodes(nodes ?? []);
    if (nodes?.length) {
      markNodesStale(nodes, "Upstream change");
      current.setStatus(`Updated. ${nodes.length} downstream node(s) may need rerun.`);
    }
  }

  function syncFrontDeskAdRequest(nextAdRequest?: AdRequest | null) {
    const current = argsRef.current;
    if (!nextAdRequest) return;
    current.setAdRequest((existing) => ({
      ...existing,
      ...nextAdRequest,
      selected_assets: current.selectedAssets,
    }));
  }

  function syncWorkflowAdRequest(nextWorkflow?: WorkflowGraph | null) {
    const nextAdRequest = workflowAdRequest(nextWorkflow);
    const current = argsRef.current;
    if (!nextAdRequest) return;
    current.setAdRequest((existing) => ({
      ...existing,
      ...nextAdRequest,
      selected_assets: current.selectedAssets,
    }));
  }

  function applyNodeRunsToCanvas(runs: NodeRunResult[]) {
    const current = argsRef.current;
    if (!runs.length) return;
    const runByKey = createNodeRunMap(runs);

    current.setCanvasNodes((existing) =>
      existing.map((node) => {
        const run = findNodeRunForWorkflowNode(node, runByKey, existing);
        if (!run) return node;
        const outputAssets = normalizeRunAssets(run.output_assets);
        const mergedOutputAssets = outputAssets.length ? dedupeAssets([...outputAssets, ...(node.output_assets ?? [])]) : dedupeAssets(node.output_assets ?? []);
        const keepActiveOutput = hasActiveOutputFailure(run);
        const keepReferenceFailureOutput = keepActiveOutput || isStrictReferenceFailure(run);
        const status = isStrictReferenceFailure(run) ? "failed" : isStoryboardVideoNode(node) && shouldPollStoryboardVideoMedia(run) ? "running" : run.status ?? node.status;
        const nextOutput = keepReferenceFailureOutput ? node.output : mergeOutputPreservingQuality(node.output, run.output) ?? node.output;
        return {
          ...node,
          workflow_id: run.workflow_id ?? node.workflow_id,
          status,
          output: nextOutput,
          input_context: mergeResolvedInputContext(node.input_context, run),
          input_assets: run.input_assets?.length ? run.input_assets : run.materialized_assets?.length ? run.materialized_assets : node.input_assets,
          output_assets: keepReferenceFailureOutput ? node.output_assets : mergedOutputAssets.length ? mergedOutputAssets : node.output_assets,
          stale: isSuccessfulNodeStatus(run.status) ? false : node.stale,
          stale_reason: run.error ?? (isSuccessfulNodeStatus(run.status) ? null : node.stale_reason),
          metadata: {
            ...(node.metadata ?? {}),
            node_run_id: run.node_run_id,
            trace_path: run.trace_path,
            metadata_path: run.metadata_path,
            error: run.error,
            resolved_prompt_preview: run.resolved_prompt_preview,
            resolved_prompt_with_assets: run.resolved_prompt_with_assets,
            effective_prompt: run.effective_prompt,
            resolved_input_assets: run.resolved_input_assets,
            materialized_prompt: run.materialized_prompt,
            materialized_assets: run.materialized_assets,
            source_mappings: run.source_mappings,
            missing_inputs: run.missing_inputs,
            stale_upstream_nodes: run.stale_upstream_nodes,
            locked_upstream_nodes: run.locked_upstream_nodes,
            reference_policy: run.reference_policy,
            selected_provider: run.selected_provider,
            provider_strategy: run.provider_strategy,
            provider_attempts: run.provider_attempts,
            fallback_warnings: run.fallback_warnings,
            identity_certification: run.identity_certification,
            has_active_output: run.has_active_output,
            last_failed_run_id: run.last_failed_run_id,
            last_run_id: run.last_run_id,
            active_run_id: run.active_run_id,
            last_error: run.last_error,
          },
        };
      }),
    );

    current.setFlowNodes((existing) => {
      const currentWorkflowNodes = existing.map((item) => flowNodeToWorkflowNode(item));
      return existing.map((node) => {
        const run = findNodeRunForWorkflowNode(flowNodeToWorkflowNode(node), runByKey, currentWorkflowNodes);
        if (!run) return node;
        const outputAssets = normalizeRunAssets(run.output_assets);
        const mergedOutputAssets = outputAssets.length ? dedupeAssets([...outputAssets, ...node.data.previewAssets]) : [];
        const activePreviewAssets = activeWorkflowAssets(mergedOutputAssets);
        const keepActiveOutput = hasActiveOutputFailure(run);
        const keepReferenceFailureOutput = keepActiveOutput || isStrictReferenceFailure(run);
        const status = isStrictReferenceFailure(run) ? "failed" : isStoryboardVideoNode({ id: node.id, node_type: node.data.kind }) && shouldPollStoryboardVideoMedia(run) ? "running" : run.status ?? node.data.status;
        const nextOutput = keepReferenceFailureOutput ? node.data.output : mergeOutputPreservingQuality(node.data.output ?? undefined, run.output) ?? node.data.output;
        return {
          ...node,
          data: {
            ...node.data,
            status,
            output: nextOutput ?? null,
            qualitySummary: qualitySummaryFromOutput(nextOutput) ?? node.data.qualitySummary ?? null,
            contentPreview: keepReferenceFailureOutput ? node.data.contentPreview : textFromUnknown(run.output) || node.data.contentPreview,
            outputCount: keepReferenceFailureOutput ? node.data.outputCount : outputAssets.length ? mergedOutputAssets.length : textFromUnknown(run.output) ? 1 : node.data.outputCount,
            previewAssets: keepReferenceFailureOutput ? node.data.previewAssets : outputAssets.length ? previewAssetsForCanvasNodeType(node.data.kind, activePreviewAssets) : node.data.previewAssets,
            stale: isSuccessfulNodeStatus(run.status) ? false : node.data.stale,
            staleReason: run.error ?? (isSuccessfulNodeStatus(run.status) ? null : node.data.staleReason),
          },
        };
      });
    });
  }

  const actionsRef = useRef<{
    applyWorkflowGraph: typeof applyWorkflowGraph;
    applyWorkflowV2: typeof applyWorkflowV2;
    refreshV2WorkflowGraph: typeof refreshV2WorkflowGraph;
    refreshV2WorkflowStructure: typeof refreshV2WorkflowStructure;
    refreshV2AssetsAndRetryMissing: typeof refreshV2AssetsAndRetryMissing;
    currentWorkflowIsV2: typeof currentWorkflowIsV2;
    assertNotV2WorkflowForV1Api: typeof assertNotV2WorkflowForV1Api;
    loadV2ResolvedInputs: typeof loadV2ResolvedInputs;
    loadV2NodeVersions: typeof loadV2NodeVersions;
    refreshWorkflowGraph: typeof refreshWorkflowGraph;
    validateBackendGraph: typeof validateBackendGraph;
    patchWorkflowNodeState: typeof patchWorkflowNodeState;
    markNodesStale: typeof markNodesStale;
    noteAffected: typeof noteAffected;
    syncFrontDeskAdRequest: typeof syncFrontDeskAdRequest;
    syncWorkflowAdRequest: typeof syncWorkflowAdRequest;
    applyNodeRunsToCanvas: typeof applyNodeRunsToCanvas;
  } | null>(null);

  if (!actionsRef.current) {
    actionsRef.current = {
      applyWorkflowGraph,
      applyWorkflowV2,
      refreshV2WorkflowGraph,
      refreshV2WorkflowStructure,
      refreshV2AssetsAndRetryMissing,
      currentWorkflowIsV2,
      assertNotV2WorkflowForV1Api,
      loadV2ResolvedInputs,
      loadV2NodeVersions,
      refreshWorkflowGraph,
      validateBackendGraph,
      patchWorkflowNodeState,
      markNodesStale,
      noteAffected,
      syncFrontDeskAdRequest,
      syncWorkflowAdRequest,
      applyNodeRunsToCanvas,
    };
  }

  return {
    actions: actionsRef.current,
  };
}
