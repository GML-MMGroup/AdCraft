import {
  applyNodeChanges,
  Controls,
  ReactFlow,
  type Connection,
  type Edge,
  type NodeChange,
  type ReactFlowInstance,
  type Viewport,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { agentCanvasApi } from "../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../api/operationKey.ts";
import {
  AssetsIcon,
  CloseIcon,
  LayoutIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
} from "../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingInputRoleV2,
  CanvasConnectionPolicyV2,
  CanvasLayoutPositionV2,
  CanvasNodeV2,
  CanvasPositionV2,
  NodeRuntimeV2,
  ProjectAssetSummaryV2,
  SaveAgentCanvasImageToLibraryRequestV2,
} from "../../types-v2.ts";
import type {
  AgentAssetReferenceSelection,
  AgentAssetSourceNodeSelection,
} from "./assets/AgentAssetBrowser.tsx";
import { toImageBindingSource } from "./assets/assetSelection.ts";
import {
  AgentCanvasNodeRenderer,
  type AgentCanvasFlowNode,
  type AgentCanvasNodeCallbacks,
} from "./canvas/AgentCanvasNode.tsx";
import { AgentCanvasConnectedNodeMenu } from "./canvas/AgentCanvasConnectedNodeMenu.tsx";
import { AgentCanvasContextMenu } from "./canvas/AgentCanvasContextMenu.tsx";
import { AgentCanvasLayoutConfirmation } from "./canvas/AgentCanvasLayoutConfirmation.tsx";
import { AgentCanvasNodePicker } from "./canvas/AgentCanvasNodePicker.tsx";
import { AgentCanvasPointerBackgrounds } from "./canvas/AgentCanvasPointerBackgrounds.tsx";
import {
  agentCanvasLayoutNodeFromFlowNode,
  computeAgentCanvasAutoLayout,
  enabledNodeLayoutEdges,
} from "./canvas/canvasAutoLayout.ts";
import { canvasAuthoringErrorMessage } from "./canvas/canvasErrorMessage.ts";
import { useCanvasPointerSpotlight } from "./canvas/canvasPointerSpotlight.ts";
import { shouldPersistAgentCanvasViewport } from "./canvas/canvasViewportPersistence.ts";
import {
  installAgentCanvasWorkflowViewport,
  readAgentCanvasViewport,
  writeAgentCanvasViewport,
} from "./canvas/agentCanvasViewport.ts";
import {
  beginNodeDrag,
  cancelNodeDrag,
  deferNodeSnapshotDuringDrag,
  finishNodeDrag,
} from "./canvas/draggingNodeState.ts";
import {
  findAvailableCanvasPosition,
  highlightNodeRelatedCanvasEdges,
  needsInitialCanvasLayout,
  reconcileSelectableCanvasEdges,
  toAgentCanvasFlowEdges,
  toAgentCanvasFlowNodes,
} from "./canvas/canvasGraphModel.ts";
import {
  AGENT_CANVAS_NODE_HORIZONTAL_GAP,
  agentCanvasNodePlacementSize,
} from "./canvas/nodeGeometry.ts";
import {
  MANUAL_BINDING_REQUIRED,
  connectionRuleForPair,
} from "./canvas/connectionPolicy.ts";
import { deleteCanvasEntities } from "./canvas/deleteCanvasEntities.ts";
import {
  AGENT_CANVAS_FOCUS_MAX_ZOOM,
  useAgentCanvasNodeFocus,
} from "./canvas/useAgentCanvasNodeFocus.ts";
import { useAgentCanvasNodeRevealQueue } from "./canvas/useAgentCanvasNodeRevealQueue.ts";
import { useAgentCanvasLayoutPreview } from "./canvas/useAgentCanvasLayoutPreview.ts";
import {
  AGENT_CANVAS_ROLE_CONTRACT_VERSION,
  createDefaultCanvasNodeRequest,
  sourceAssetStructuredContent,
  type AgentCanvasVisibleNodeTypeV2,
} from "./model/nodeDefaults.ts";
import { hasPromptReadyDraft } from "./model/promptPreparation.ts";
import { useAgentCanvasProviderModels } from "./model/useAgentCanvasProviderModels.ts";
import { useAgentCanvasRuntime } from "./runtime/useAgentCanvasRuntime.ts";
import { useAgentCanvasSession } from "./session/useAgentCanvasSession.ts";

const nodeTypes = { agentCanvas: AgentCanvasNodeRenderer };

const AgentAssetBrowser = lazy(() => import("./assets/AgentAssetBrowser.tsx").then((module) => ({
  default: module.AgentAssetBrowser,
})));
const AgentCanvasChatPanel = lazy(() => import("./chat/AgentCanvasChatPanel.tsx").then((module) => ({
  default: module.AgentCanvasChatPanel,
})));
const AgentCanvasEditingPanel = lazy(() => import("./editing/AgentCanvasEditingPanel.tsx").then((module) => ({
  default: module.AgentCanvasEditingPanel,
})));
const AgentCanvasInlineWorkbench = lazy(() => import("./workbench/AgentCanvasInlineWorkbench.tsx").then((module) => ({
  default: module.AgentCanvasInlineWorkbench,
})));
const AgentCanvasVideoPreviewDialog = lazy(() => import("./canvas/AgentCanvasVideoPreviewDialog.tsx").then((module) => ({
  default: module.AgentCanvasVideoPreviewDialog,
})));

function reducedMotionPreference(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type CanvasInteractionReason = "viewport" | "node-drag";

export function AgentCanvasPage() {
  const session = useAgentCanvasSession();
  const pointerSpotlight = useCanvasPointerSpotlight<HTMLDivElement>();
  const workflow = session.state.workflow;
  const hasRunnableDraft = workflow ? hasPromptReadyDraft(workflow.nodes) : false;
  const {
    applyWorkflow,
    clearAuthoringError,
    createBinding,
    createConnectedNode,
    createNode: createCanvasNode,
    discardVariationDraft,
    deleteBinding,
    deleteNode,
    importEditingExport,
    materializeVariationDraft,
    mergeNode,
    mergePublishedAsset,
    patchNode,
    patchBinding,
    persistLayoutPreviewPositions,
    placeActionReceiptNodes,
    saveVariationDraft,
    setSelectedNodeId,
    rollbackNodePositions,
    updateNodePositions,
  } = session.actions;
  const runtimeCallbacks = useMemo(() => ({
    applyWorkflow,
    mergePublishedAsset,
    mergeNode,
  }), [
    applyWorkflow,
    mergeNode,
    mergePublishedAsset,
  ]);
  const live = useAgentCanvasRuntime(workflow, runtimeCallbacks, patchNode);
  const providerModels = useAgentCanvasProviderModels(workflow, session.state.selectedNode);
  const {
    cancelRun,
    clearAutoRunNotice,
    refreshRuntime,
    refreshWorkflow,
    runAll,
    runNode,
  } = live.actions;
  const [nodes, setNodes] = useNodesState<AgentCanvasFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [canvasInteracting, setCanvasInteracting] = useState(false);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [videoPreview, setVideoPreview] = useState<{
    asset: ProjectAssetSummaryV2;
    title: string;
  } | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    menuPosition: CanvasPositionV2;
    canvasPosition: CanvasPositionV2;
  } | null>(null);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const [connectionPolicy, setConnectionPolicy] = useState<CanvasConnectionPolicyV2 | null>(null);
  const [connectedNodeMenu, setConnectedNodeMenu] = useState<{
    anchorNodeId: string;
    direction: "upstream" | "downstream";
    point: { x: number; y: number };
  } | null>(null);
  const flowRef = useRef<ReactFlowInstance<AgentCanvasFlowNode, Edge> | null>(null);
  const activeWorkflowIdRef = useRef(workflow?.workflow_id ?? "no-workflow");
  const workflowNodesRef = useRef(workflow?.nodes ?? []);
  const canonicalNodesRef = useRef<readonly AgentCanvasFlowNode[]>([]);
  const initialLayoutRepairWorkflowIdsRef = useRef(new Set<string>());
  const installedViewportWorkflowIdRef = useRef<string | null>(null);
  const viewportInstallFrameRef = useRef<number | null>(null);
  const layoutButtonRef = useRef<HTMLButtonElement>(null);
  const activeDraggedNodeIdsRef = useRef(new Set<string>());
  const canvasInteractionReasonsRef = useRef(new Set<CanvasInteractionReason>());
  const dragCancellationPendingRef = useRef(false);
  const latestPresentedNodesRef = useRef<readonly AgentCanvasFlowNode[]>([]);
  const pendingPresentedNodesRef = useRef<readonly AgentCanvasFlowNode[] | null>(null);
  const flowNodesRef = useRef<readonly AgentCanvasFlowNode[]>(nodes);
  const referenceUploadInputRef = useRef<HTMLInputElement>(null);
  activeWorkflowIdRef.current = workflow?.workflow_id ?? "no-workflow";
  workflowNodesRef.current = workflow?.nodes ?? [];
  useEffect(() => {
    flowNodesRef.current = nodes;
  }, [nodes]);
  const setCanvasInteractionReason = useCallback((
    reason: CanvasInteractionReason,
    active: boolean,
  ) => {
    const reasons = canvasInteractionReasonsRef.current;
    if (active) reasons.add(reason);
    else reasons.delete(reason);
    const nextInteracting = reasons.size > 0;
    setCanvasInteracting((current) => current === nextInteracting ? current : nextInteracting);
  }, []);
  const beginCanvasInteraction = useCallback((reason: CanvasInteractionReason) => {
    setCanvasInteractionReason(reason, true);
  }, [setCanvasInteractionReason]);
  const endCanvasInteraction = useCallback((reason: CanvasInteractionReason) => {
    setCanvasInteractionReason(reason, false);
  }, [setCanvasInteractionReason]);
  const clearCanvasInteractions = useCallback(() => {
    canvasInteractionReasonsRef.current.clear();
    setCanvasInteracting(false);
  }, []);
  const scheduleLayoutButtonFocus = useCallback(() => {
    window.requestAnimationFrame(() => layoutButtonRef.current?.focus());
  }, []);
  const restoreLayoutViewport = useCallback((viewport: Viewport, previewWorkflowId: string) => {
    if (activeWorkflowIdRef.current !== previewWorkflowId) return;
    return flowRef.current?.setViewport(viewport);
  }, []);
  const layoutPreview = useAgentCanvasLayoutPreview({
    workflowId: workflow?.workflow_id ?? "no-workflow",
    persistPositions: persistLayoutPreviewPositions,
    restoreViewport: restoreLayoutViewport,
    rollbackPositions: rollbackNodePositions,
    // The hook invokes this only for explicit Undo/Keep, so project navigation keeps its focus target.
    onUserResolution: scheduleLayoutButtonFocus,
  });
  const {
    active: layoutPreviewActive,
    begin: beginLayoutPreview,
    cancel: cancelLayoutPreview,
    keep: persistLayoutPreview,
    overlay: overlayLayoutPreview,
  } = layoutPreview;
  const undoLayoutPreview = useCallback(() => cancelLayoutPreview("explicit"), [cancelLayoutPreview]);
  const dismissLayoutPreview = useCallback(() => cancelLayoutPreview("implicit"), [cancelLayoutPreview]);
  const keepLayoutPreview = useCallback(() => {
    void persistLayoutPreview();
  }, [persistLayoutPreview]);
  const {
    focusedNodeId,
    highlightedNodeIds,
    focusNode: focusCanvasNode,
    revealNodes: revealCanvasNodes,
    exitFocus: exitCanvasNodeFocus,
    scheduleExitForNodeSelection,
  } = useAgentCanvasNodeFocus({
    flowRef,
    scopeKey: workflow?.workflow_id ?? "no-workflow",
  });
  const focusNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    void flowRef.current?.fitView({
      nodes: [{ id: nodeId }],
      padding: 0.55,
      duration: reducedMotionPreference() ? 0 : 420,
      maxZoom: 1.15,
    });
  }, [setSelectedNodeId]);
  const revealQueue = useAgentCanvasNodeRevealQueue({
    workflowId: workflow?.workflow_id ?? null,
    flowRef,
    onFocusNode: focusNode,
    reducedMotion: reducedMotionPreference(),
  });
  const {
    activeNodeId: progressiveActiveNodeId,
    enqueue: enqueueReveal,
    interrupt: interruptReveal,
    releaseNodeIds: releaseRevealNodeIds,
    reserveNodeIds: reserveRevealNodeIds,
    syncCanonicalNodeIds: syncRevealCanonicalNodeIds,
    visibleNodeIds: visibleRevealNodeIds,
  } = revealQueue;
  const revealAvailableCanvasNodes = useCallback((nodeIds: string[]) => {
    const visibleNodeIds = new Set(flowNodesRef.current.map((node) => node.id));
    revealCanvasNodes(nodeIds.filter((nodeId) => visibleNodeIds.has(nodeId)));
  }, [revealCanvasNodes]);
  useEffect(() => {
    let active = true;
    void agentCanvasApi.agentCanvasConnectionPolicy()
      .then((policy) => {
        if (active) setConnectionPolicy(policy);
      })
      .catch((error) => {
        if (active) setSurfaceError(canvasAuthoringErrorMessage(error));
      });
    return () => {
      active = false;
    };
  }, []);

  const runNodeById = useCallback((nodeId: string, retryFailed = false) => {
    const node = workflow?.nodes.find((candidate) => candidate.node_id === nodeId);
    if (node) void runNode(node, { retryFailed }).catch((error) => {
      setSurfaceError(error instanceof Error ? error.message : "Node run failed.");
    });
  }, [runNode, workflow?.nodes]);

  const openEditing = useCallback((nodeId: string) => {
    setEditingNodeId(nodeId);
    setSelectedNodeId(nodeId);
  }, [setSelectedNodeId]);

  const addEditingExportToCanvas = useCallback(async (exportId: string) => {
    if (!workflow || !editingNodeId) {
      throw new Error("Select an Editing node before importing an export.");
    }
    const editingNode = workflow.nodes.find((candidate) => (
      candidate.node_id === editingNodeId && candidate.node_type === "editing"
    ));
    if (!editingNode) throw new Error("The Editing node is no longer available.");
    const editingAsset = editingNode.output_asset_id
      ? workflow.assets.find((asset) => asset.asset_id === editingNode.output_asset_id) ?? null
      : null;
    const sourceSize = agentCanvasNodePlacementSize(
      editingNode.node_type,
      editingAsset ? { width: editingAsset.width, height: editingAsset.height } : null,
    );
    const videoSize = agentCanvasNodePlacementSize("video");
    const position = findAvailableCanvasPosition(
      workflow.nodes,
      {
        x: editingNode.position.x + sourceSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP,
        y: editingNode.position.y,
      },
      {
        assets: workflow.assets,
        candidateNodeType: "video",
        candidateDimensions: videoSize,
      },
    );
    setSurfaceError(null);
    try {
      await importEditingExport(editingNode.node_id, {
        export_id: exportId,
        title: "Exported video",
        position,
      });
      setEditingNodeId(null);
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "The exported video could not be added to canvas.");
      throw error;
    }
  }, [editingNodeId, importEditingExport, workflow]);

  const closeVideoPreview = useCallback(() => {
    setVideoPreview(null);
  }, []);

  const uploadSelectedNodeReferences = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    const targetNode = session.state.selectedNode;
    if (!workflow || !targetNode || !files.length) return;
    if (targetNode.node_type === "editing") {
      setSurfaceError("Use connected Video and Audio nodes as Editing inputs.");
      return;
    }
    const imageFiles = files.filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length !== files.length) {
      setSurfaceError("Only image files can be attached as prompt references.");
      return;
    }
    setSurfaceError(null);
    try {
      const startOrder = workflow.bindings.filter((binding) => (
        binding.target_node_id === targetNode.node_id
      )).length;
      for (const [index, file] of imageFiles.entries()) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("metadata", JSON.stringify({
          media_type: "image",
          title: file.name.replace(/\.[^.]+$/, "") || file.name,
          semantic_role: null,
          metadata: {},
        }));
        const uploaded = await agentCanvasApi.uploadAgentCanvasAsset(
          workflow.workflow_id,
          formData,
          createOperationKey("node-reference-upload"),
        );
        if (!uploaded.asset.version_id) {
          throw new Error(`Uploaded image ${uploaded.asset.display_name} has no immutable AssetVersion.`);
        }
        await createBinding({
          source: {
            kind: "image_asset",
            source_asset_id: uploaded.asset.asset_id,
            source_asset_version_id: uploaded.asset.version_id,
          },
          target_node_id: targetNode.node_id,
          input_role: "image_reference",
          required: true,
          enabled: true,
          order: startOrder + index,
        });
      }
      await refreshWorkflow();
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "Reference upload failed.");
    }
  }, [createBinding, refreshWorkflow, session.state.selectedNode, workflow]);

  const saveImageToLibrary = useCallback(async (
    assetId: string,
    request: SaveAgentCanvasImageToLibraryRequestV2,
  ) => {
    await agentCanvasApi.saveAgentCanvasImageToLibrary(
      assetId,
      request,
      createOperationKey("save-image-to-library"),
    );
  }, []);

  const renderWorkbench = useCallback((node: CanvasNodeV2, runtime: NodeRuntimeV2 | null) => {
    if (!workflow || session.state.selectedNodeId !== node.node_id) return null;
    return (
      <Suspense fallback={null}>
        <AgentCanvasInlineWorkbench
          workflow={workflow}
          node={node}
          visibleStatus={runtime?.visible_status ?? node.status}
          patchNode={patchNode}
          patchBinding={patchBinding}
          deleteBinding={deleteBinding}
          connectionPolicy={connectionPolicy}
          providerModels={providerModels.models}
          providerModelsLoading={providerModels.loading}
          providerModelsError={providerModels.error}
          inputManifest={live.state.inputManifestsByNodeId[node.node_id]}
          modelResolution={live.state.modelResolutionsByNodeId[node.node_id]}
          inputReadinessIssue={live.state.inputReadinessIssue}
          onRun={runNode}
          onSaveVariation={saveVariationDraft}
          onDiscardVariation={discardVariationDraft}
          onMaterializeVariation={materializeVariationDraft}
          onSaveImageToLibrary={saveImageToLibrary}
          onDelete={deleteNode}
          onOpenEditing={() => openEditing(node.node_id)}
          onWorkflowRefresh={refreshWorkflow}
          onOpenAssets={() => setAssetsOpen(true)}
          onUploadReferences={() => referenceUploadInputRef.current?.click()}
          onClose={() => setSelectedNodeId(null)}
        />
      </Suspense>
    );
  }, [connectionPolicy, deleteBinding, deleteNode, discardVariationDraft, live.state.inputManifestsByNodeId, live.state.inputReadinessIssue, live.state.modelResolutionsByNodeId, materializeVariationDraft, openEditing, patchBinding, patchNode, providerModels.error, providerModels.loading, providerModels.models, refreshWorkflow, runNode, saveImageToLibrary, saveVariationDraft, session.state.selectedNodeId, setSelectedNodeId, workflow]);

  const openNodeVideoPreview = useCallback((nodeId: string, asset: ProjectAssetSummaryV2) => {
    const node = workflowNodesRef.current.find((candidate) => candidate.node_id === nodeId);
    setVideoPreview({
      asset,
      title: asset.display_name || node?.title || "Video preview",
    });
  }, []);

  const nodeCallbacks = useMemo<AgentCanvasNodeCallbacks>(() => ({
    onRun: (nodeId) => runNodeById(nodeId, false),
    onRetry: (nodeId) => runNodeById(nodeId, true),
    onExport: openEditing,
    onOpenEditing: openEditing,
    onOpenVideoPreview: openNodeVideoPreview,
    renderWorkbench,
    onOpenConnectedNodeMenu: (nodeId, direction, point) => {
      setSelectedNodeId(nodeId);
      setConnectedNodeMenu({ anchorNodeId: nodeId, direction, point });
    },
  }), [openEditing, openNodeVideoPreview, renderWorkbench, runNodeById, setSelectedNodeId]);

  const canonicalNodes = useMemo(() => {
    const nextNodes = workflow
      ? toAgentCanvasFlowNodes(workflow, live.state.runtime, nodeCallbacks, {
        previousNodes: canonicalNodesRef.current,
        activeWorkbenchNodeId: session.state.selectedNodeId,
      })
      : [];
    canonicalNodesRef.current = nextNodes;
    return nextNodes;
  }, [live.state.runtime, nodeCallbacks, session.state.selectedNodeId, workflow]);
  useLayoutEffect(() => {
    syncRevealCanonicalNodeIds(canonicalNodes.map((node) => node.id));
  }, [canonicalNodes, syncRevealCanonicalNodeIds]);
  const visibleCanonicalNodes = useMemo(
    () => canonicalNodes.filter((node) => visibleRevealNodeIds.has(node.id)),
    [canonicalNodes, visibleRevealNodeIds],
  );
  const presentedNodes = useMemo<AgentCanvasFlowNode[]>(() => {
    const highlighted = new Set(highlightedNodeIds);
    return (overlayLayoutPreview(visibleCanonicalNodes) as AgentCanvasFlowNode[]).map((node) => {
      const classNames = (node.className ?? "")
        .split(/\s+/)
        .filter((className) => className && className !== "is-conversation-highlighted");
      if (highlighted.has(node.id)) classNames.push("is-conversation-highlighted");
      if (progressiveActiveNodeId === node.id) classNames.push("is-progressive-reveal");
      return classNames.join(" ") === (node.className ?? "")
        ? node
        : { ...node, className: classNames.join(" ") };
    });
  }, [highlightedNodeIds, overlayLayoutPreview, progressiveActiveNodeId, visibleCanonicalNodes]);
  const canonicalEdges = useMemo(
    () => workflow ? toAgentCanvasFlowEdges(workflow.bindings, visibleCanonicalNodes.map((node) => node.data.node)) : [],
    [visibleCanonicalNodes, workflow],
  );
  const presentedEdges = useMemo(
    () => highlightNodeRelatedCanvasEdges(canonicalEdges, session.state.selectedNodeId),
    [canonicalEdges, session.state.selectedNodeId],
  );

  useEffect(() => {
    if (!workflow || !needsInitialCanvasLayout(visibleCanonicalNodes.map((node) => node.data.node))) return;
    const workflowId = workflow.workflow_id;
    const repairAttempts = initialLayoutRepairWorkflowIdsRef.current;
    if (repairAttempts.has(workflowId)) return;
    repairAttempts.add(workflowId);

    const visibleNodeIds = new Set(visibleCanonicalNodes.map((node) => node.id));
    let layoutResult: ReturnType<typeof computeAgentCanvasAutoLayout>;
    try {
      layoutResult = computeAgentCanvasAutoLayout(
        visibleCanonicalNodes.map(agentCanvasLayoutNodeFromFlowNode),
        enabledNodeLayoutEdges(workflow.bindings, visibleNodeIds),
        {
          isolatedRowWidth: Math.max(
            960,
            (pointerSpotlight.hostRef.current?.clientWidth ?? 960)
              / (flowRef.current?.getViewport().zoom ?? 1),
          ),
        },
      );
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "Canvas layout could not be calculated.");
      return;
    }

    if (!layoutResult.positions.length) return;
    if (activeWorkflowIdRef.current !== workflowId) return;
    void updateNodePositions(layoutResult.positions)
      .then(() => {
        if (
          activeWorkflowIdRef.current !== workflowId
          || readAgentCanvasViewport(workflowId)
          || !flowRef.current
        ) return;
        const reducedMotion = typeof window.matchMedia === "function"
          && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.requestAnimationFrame(() => {
          if (activeWorkflowIdRef.current !== workflowId) return;
          void flowRef.current?.fitView({
            nodes: layoutResult.positions.map(({ node_id }) => ({ id: node_id })),
            padding: 0.22,
            maxZoom: 1,
            duration: reducedMotion ? 0 : 350,
          });
        });
      })
      .catch((error) => {
        if (activeWorkflowIdRef.current === workflowId) {
          setSurfaceError(error instanceof Error ? error.message : "Canvas layout could not be saved.");
        }
      });
  }, [pointerSpotlight.hostRef, updateNodePositions, visibleCanonicalNodes, workflow]);

  useEffect(() => {
    latestPresentedNodesRef.current = presentedNodes;
    const deferred = deferNodeSnapshotDuringDrag(
      presentedNodes,
      flowNodesRef.current,
      activeDraggedNodeIdsRef.current,
    );
    pendingPresentedNodesRef.current = deferred.pendingNodes;
    if (!deferred.nodes) return;
    flowNodesRef.current = deferred.nodes;
    setNodes(deferred.nodes);
  }, [presentedNodes, setNodes]);

  const cancelActiveNodeDrag = useCallback(() => {
    endCanvasInteraction("node-drag");
    if (!activeDraggedNodeIdsRef.current.size) return;
    dragCancellationPendingRef.current = true;
    const nextNodes = cancelNodeDrag(
      pendingPresentedNodesRef.current ?? latestPresentedNodesRef.current,
      flowNodesRef.current,
      activeDraggedNodeIdsRef.current,
    );
    pendingPresentedNodesRef.current = null;
    flowNodesRef.current = nextNodes;
    setNodes(nextNodes);
  }, [endCanvasInteraction, setNodes]);

  useEffect(() => {
    const activeDraggedNodeIds = activeDraggedNodeIdsRef.current;
    const handleWindowBlur = () => {
      clearCanvasInteractions();
      cancelActiveNodeDrag();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") handleWindowBlur();
    };
    window.addEventListener("blur", handleWindowBlur);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("blur", handleWindowBlur);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      activeDraggedNodeIds.clear();
      pendingPresentedNodesRef.current = null;
    };
  }, [cancelActiveNodeDrag, clearCanvasInteractions]);

  useEffect(() => {
    setEdges((current) => reconcileSelectableCanvasEdges(presentedEdges, current));
  }, [presentedEdges, setEdges]);

  const clearEdgeSelection = useCallback(() => {
    setEdges((current) => {
      if (!current.some((edge) => edge.selected)) return current;
      return current.map((edge) => edge.selected ? { ...edge, selected: false } : edge);
    });
  }, [setEdges]);

  useEffect(() => {
    if (
      session.state.selectedNodeId
      && !canonicalNodes.some((node) => node.id === session.state.selectedNodeId)
    ) {
      setSelectedNodeId(null);
    }
  }, [canonicalNodes, session.state.selectedNodeId, setSelectedNodeId]);

  useEffect(() => {
    if (focusedNodeId && !canonicalNodes.some((node) => node.id === focusedNodeId)) {
      exitCanvasNodeFocus();
    }
  }, [canonicalNodes, exitCanvasNodeFocus, focusedNodeId]);

  const handleNodeChanges = useCallback((changes: NodeChange<AgentCanvasFlowNode>[]) => {
    setNodes((current) => {
      const next = applyNodeChanges(changes, current);
      flowNodesRef.current = next;
      return next;
    });
  }, [setNodes]);

  const connect = useCallback(async (connection: Connection) => {
    if (!workflow || !connectionPolicy || !connection.source || !connection.target || connection.source === connection.target) {
      if (!connectionPolicy) setSurfaceError("Connection policy is still loading.");
      return;
    }
    const source = workflow.nodes.find((node) => node.node_id === connection.source);
    const target = workflow.nodes.find((node) => node.node_id === connection.target);
    if (!source || !target) return;
    const rule = connectionRuleForPair(connectionPolicy, source.node_type, target.node_type);
    if (!rule) {
      setSurfaceError("These node types cannot be connected.");
      return;
    }
    setSurfaceError(null);
    try {
      await createBinding({
        source: { kind: "node_output", source_node_id: source.node_id },
        target_node_id: connection.target,
        input_role: rule.default_role,
        required: MANUAL_BINDING_REQUIRED,
        enabled: true,
        order: workflow.bindings.filter((binding) => binding.target_node_id === connection.target).length,
      });
    } catch (error) {
      setSurfaceError(canvasAuthoringErrorMessage(error));
    }
  }, [connectionPolicy, createBinding, workflow]);

  const recoverDeletedCanvasState = useCallback(async () => {
    setNodes(presentedNodes);
    setEdges((current) => reconcileSelectableCanvasEdges(presentedEdges, current));
    await refreshWorkflow();
  }, [presentedEdges, presentedNodes, refreshWorkflow, setEdges, setNodes]);

  const deleteEdges = useCallback((deleted: Edge[]) => {
    void deleteCanvasEntities(
      deleted.map((edge) => edge.id),
      deleteBinding,
      recoverDeletedCanvasState,
    )
      .catch((error) => setSurfaceError(error instanceof Error ? error.message : "The connection could not be removed."));
  }, [deleteBinding, recoverDeletedCanvasState]);

  const deleteNodes = useCallback((deleted: AgentCanvasFlowNode[]) => {
    void deleteCanvasEntities(
      deleted.map((node) => node.id),
      deleteNode,
      recoverDeletedCanvasState,
    )
      .catch((error) => setSurfaceError(error instanceof Error ? error.message : "The node could not be deleted."));
  }, [deleteNode, recoverDeletedCanvasState]);

  const cancelCurrentRun = useCallback(async () => {
    setSurfaceError(null);
    try {
      await cancelRun();
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "The run could not be cancelled.");
    }
  }, [cancelRun]);

  const createNode = useCallback(async (
    nodeType: AgentCanvasVisibleNodeTypeV2,
    preferredPosition?: CanvasPositionV2,
  ) => {
    if (!workflow) return;
    const instance = flowRef.current;
    const defaultPosition = instance
      ? instance.screenToFlowPosition({ x: window.innerWidth * 0.48, y: window.innerHeight * 0.46 })
      : { x: 120, y: 120 };
    const position = findAvailableCanvasPosition(
      workflow.nodes,
      preferredPosition ?? defaultPosition,
      {
        assets: workflow.assets,
        candidateNodeType: nodeType,
      },
    );
    setSurfaceError(null);
    setAddMenuOpen(false);
    setContextMenu(null);
    try {
      await createCanvasNode(createDefaultCanvasNodeRequest(nodeType, position));
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "The node could not be created.");
    }
  }, [createCanvasNode, workflow]);

  const addReferences = useCallback(async (selections: AgentAssetReferenceSelection[]) => {
    if (!workflow || !session.state.selectedNode) {
      throw new Error("Select a target node before adding image references.");
    }
    if (session.state.selectedNode.node_type === "editing") {
      throw new Error("Editing nodes accept connected Video nodes and one BGM node, not image references.");
    }
    const targetNodeId = session.state.selectedNode.node_id;
    const startOrder = workflow.bindings.filter((binding) => binding.target_node_id === targetNodeId).length;
    for (const [index, selection] of selections.entries()) {
      await createBinding({
        source: toImageBindingSource(selection),
        target_node_id: targetNodeId,
        input_role: "image_reference",
        required: true,
        enabled: true,
        order: startOrder + index,
      });
    }
  }, [createBinding, session.state.selectedNode, workflow]);

  const createReadySourceNode = useCallback(async (selection: AgentAssetSourceNodeSelection) => {
    if (!workflow) return;
    const instance = flowRef.current;
    const preferredPosition = instance
      ? instance.screenToFlowPosition({ x: window.innerWidth * 0.5, y: window.innerHeight * 0.5 })
      : { x: 180, y: 160 };
    const position = findAvailableCanvasPosition(workflow.nodes, preferredPosition, {
      assets: workflow.assets,
      candidateNodeType: selection.mediaType,
      candidateDimensions: { width: selection.width, height: selection.height },
    });
    await createCanvasNode({
      node_type: selection.mediaType,
      creative_role: selection.mediaType === "image"
        ? "general_image"
        : selection.mediaType === "video"
          ? "general_video"
          : "general_audio",
      role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
      title: selection.displayName,
      structured_content: sourceAssetStructuredContent(
        selection.mediaType,
        selection.displayName,
        selection.durationSeconds,
      ),
      position,
      source_asset_id: selection.assetId,
    });
  }, [createCanvasNode, workflow]);

  const createConnectedNodeFromMenu = useCallback(async (
    nodeType: AgentCanvasVisibleNodeTypeV2,
    inputRole: CanvasBindingInputRoleV2,
  ) => {
    if (!workflow || !connectedNodeMenu) return;
    const anchor = workflow.nodes.find((node) => node.node_id === connectedNodeMenu.anchorNodeId);
    if (!anchor) return;
    const anchorAsset = anchor.output_asset_id
      ? workflow.assets.find((asset) => asset.asset_id === anchor.output_asset_id) ?? null
      : null;
    const anchorSize = agentCanvasNodePlacementSize(
      anchor.node_type,
      anchorAsset ? { width: anchorAsset.width, height: anchorAsset.height } : null,
    );
    const candidateSize = agentCanvasNodePlacementSize(nodeType);
    const preferred = {
      x: connectedNodeMenu.direction === "downstream"
        ? anchor.position.x + anchorSize.width + AGENT_CANVAS_NODE_HORIZONTAL_GAP
        : anchor.position.x - candidateSize.width - AGENT_CANVAS_NODE_HORIZONTAL_GAP,
      y: anchor.position.y,
    };
    const position = findAvailableCanvasPosition(workflow.nodes, preferred, {
      assets: workflow.assets,
      candidateNodeType: nodeType,
    });
    const targetNodeId = connectedNodeMenu.direction === "downstream"
      ? null
      : anchor.node_id;
    const order = targetNodeId
      ? workflow.bindings.filter((binding) => binding.target_node_id === targetNodeId).length
      : 0;
    setConnectedNodeMenu(null);
    setSurfaceError(null);
    try {
      await createConnectedNode({
        anchor_node_id: anchor.node_id,
        direction: connectedNodeMenu.direction,
        node: createDefaultCanvasNodeRequest(nodeType, position),
        binding: {
          input_role: inputRole,
          required: MANUAL_BINDING_REQUIRED,
          order,
        },
      });
    } catch (error) {
      setSurfaceError(canvasAuthoringErrorMessage(error));
    }
  }, [connectedNodeMenu, createConnectedNode, workflow]);

  const placeReceiptNodes = useCallback((receipt: Parameters<typeof placeActionReceiptNodes>[0]) => {
    reserveRevealNodeIds(receipt.created_node_ids);
    void placeActionReceiptNodes(receipt)
      .then((plan) => {
        if (!plan) {
          releaseRevealNodeIds(receipt.created_node_ids);
          return;
        }
        const planned = new Set(plan.orderedNodeIds);
        releaseRevealNodeIds(
          receipt.created_node_ids.filter((nodeId) => !planned.has(nodeId)),
        );
        enqueueReveal(plan);
      })
      .catch((error) => {
        setSurfaceError(error instanceof Error ? error.message : "New canvas nodes could not be positioned.");
      });
  }, [enqueueReveal, placeActionReceiptNodes, releaseRevealNodeIds, reserveRevealNodeIds]);

  const organizeCanvas = useCallback(() => {
    const instance = flowRef.current;
    if (!workflow || !instance || layoutPreviewActive) return;

    const flowNodes = instance.getNodes();
    if (!flowNodes.length) return;
    const viewport = instance.getViewport();
    const isolatedRowWidth = Math.max(
      960,
      (pointerSpotlight.hostRef.current?.clientWidth ?? 960) / viewport.zoom,
    );
    let result: ReturnType<typeof computeAgentCanvasAutoLayout>;
    try {
      const visibleNodeIds = new Set(flowNodes.map((node) => node.id));
      result = computeAgentCanvasAutoLayout(
        flowNodes.map(agentCanvasLayoutNodeFromFlowNode),
        enabledNodeLayoutEdges(workflow.bindings, visibleNodeIds),
        { isolatedRowWidth },
      );
    } catch (error) {
      setSurfaceError(error instanceof Error ? error.message : "Canvas layout could not be calculated.");
      return;
    }

    setSurfaceError(null);
    beginLayoutPreview({
      workflowId: workflow.workflow_id,
      workflow,
      nodes: flowNodes,
      targetPositions: result.positions,
      viewport,
    });
    const reducedMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.requestAnimationFrame(() => {
      void instance.fitView({
        nodes: result.positions.map(({ node_id }) => ({ id: node_id })),
        padding: 0.2,
        maxZoom: 1,
        duration: reducedMotion ? 0 : 420,
      });
    });
  }, [beginLayoutPreview, layoutPreviewActive, pointerSpotlight.hostRef, workflow]);

  const scheduleWorkflowViewportInstall = useCallback((
    instance: ReactFlowInstance<AgentCanvasFlowNode, Edge>,
    nextWorkflow: AgentCanvasWorkflowV2,
  ) => {
    if (installedViewportWorkflowIdRef.current === nextWorkflow.workflow_id) return;
    if (viewportInstallFrameRef.current !== null) {
      window.cancelAnimationFrame(viewportInstallFrameRef.current);
    }
    installedViewportWorkflowIdRef.current = nextWorkflow.workflow_id;
    const workflowId = nextWorkflow.workflow_id;
    const nodeIds = nextWorkflow.nodes.map((node) => node.node_id);
    viewportInstallFrameRef.current = window.requestAnimationFrame(() => {
      viewportInstallFrameRef.current = null;
      if (activeWorkflowIdRef.current !== workflowId) return;
      const reducedMotion = typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      void installAgentCanvasWorkflowViewport({
        instance: {
          setViewport: (viewport, options) => instance.setViewport(viewport, options),
          fitView: (options) => instance.fitView(options),
        },
        workflowId,
        nodeIds,
        reducedMotion,
      }).catch(() => undefined);
    });
  }, []);

  const initializeFlow = useCallback((instance: ReactFlowInstance<AgentCanvasFlowNode, Edge>) => {
    flowRef.current = instance;
    if (workflow) scheduleWorkflowViewportInstall(instance, workflow);
  }, [scheduleWorkflowViewportInstall, workflow]);

  useEffect(() => {
    if (!workflow) {
      installedViewportWorkflowIdRef.current = null;
      return;
    }
    const instance = flowRef.current;
    if (instance) scheduleWorkflowViewportInstall(instance, workflow);
  }, [scheduleWorkflowViewportInstall, workflow]);

  useEffect(() => () => {
    if (viewportInstallFrameRef.current !== null) {
      window.cancelAnimationFrame(viewportInstallFrameRef.current);
    }
  }, []);

  const openCanvasContextMenu = useCallback((menuPosition: CanvasPositionV2) => {
    const canvasPosition = flowRef.current?.screenToFlowPosition(menuPosition) ?? { x: 120, y: 120 };
    clearEdgeSelection();
    setSelectedNodeId(null);
    setAddMenuOpen(false);
    setConnectedNodeMenu(null);
    setContextMenu({ menuPosition, canvasPosition });
  }, [clearEdgeSelection, setSelectedNodeId]);

  if (!session.state.workspaceHydrated) {
    return <div className="agent-canvas-state">Opening project...</div>;
  }
  if (!workflow) {
    return (
      <div className="agent-canvas-state agent-canvas-state--error">
        <strong>Project canvas unavailable</strong>
        <span>{session.state.workspaceRestoreError || "Open a project or create a new one."}</span>
      </div>
    );
  }

  const editingNode = editingNodeId
    ? workflow.nodes.find((node) => node.node_id === editingNodeId && node.node_type === "editing") ?? null
    : null;
  const editingPreparation = editingNode
    ? live.state.editingPreparationByNodeId[editingNode.node_id]
    : undefined;
  const connectedMenuAnchor = connectedNodeMenu
    ? workflow.nodes.find((node) => node.node_id === connectedNodeMenu.anchorNodeId) ?? null
    : null;
  const running = Boolean(live.state.runtime?.active_execution_id);
  return (
    <div className={`agent-canvas-page${chatCollapsed ? " is-chat-collapsed" : ""}`}>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- React Flow owns canvas keyboard and pointer semantics; this listener only distinguishes pane double-clicks. */}
      <div
        ref={pointerSpotlight.hostRef}
        className={`agent-canvas-board${layoutPreview.active ? " is-layout-previewing" : ""}${canvasInteracting ? " is-interacting" : ""}`}
        onContextMenu={(event) => event.preventDefault()}
        onPointerMove={pointerSpotlight.onPointerMove}
        onPointerLeave={pointerSpotlight.onPointerLeave}
        onPointerCancel={(event) => {
          pointerSpotlight.onPointerCancel(event);
          clearCanvasInteractions();
          cancelActiveNodeDrag();
        }}
        onDoubleClick={(event) => {
          const target = event.target;
          if (target instanceof Element && target.classList.contains("react-flow__pane")) {
            exitCanvasNodeFocus();
          }
        }}
      >
        <ReactFlow<AgentCanvasFlowNode, Edge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          minZoom={0.05}
          maxZoom={focusedNodeId ? AGENT_CANVAS_FOCUS_MAX_ZOOM : 2}
          deleteKeyCode={["Backspace", "Delete"]}
          multiSelectionKeyCode={["Meta", "Control"]}
          selectionKeyCode="Shift"
          panOnScroll
          zoomOnDoubleClick={false}
          selectionOnDrag
          onlyRenderVisibleElements={false}
          nodesDraggable={!layoutPreview.active}
          onInit={initializeFlow}
          onEdgesChange={onEdgesChange}
          onNodesChange={handleNodeChanges}
          onNodeClick={(_event, node) => {
            clearEdgeSelection();
            setSelectedNodeId(node.id);
            scheduleExitForNodeSelection(node.id);
          }}
          onNodeDoubleClick={(event, node) => {
            event.preventDefault();
            event.stopPropagation();
            clearEdgeSelection();
            setSelectedNodeId(node.id);
            focusCanvasNode(node.id);
          }}
          onNodeDragStart={(_event, node, draggedNodes) => {
            interruptReveal();
            beginCanvasInteraction("node-drag");
            dragCancellationPendingRef.current = false;
            beginNodeDrag(
              activeDraggedNodeIdsRef.current,
              node.id,
              draggedNodes.map((item) => item.id),
            );
          }}
          onNodeDragStop={(_event, node, draggedNodes) => {
            endCanvasInteraction("node-drag");
            if (dragCancellationPendingRef.current) {
              dragCancellationPendingRef.current = false;
              return;
            }
            const changed = draggedNodes.length ? draggedNodes : [node];
            const dragResult = finishNodeDrag(
              pendingPresentedNodesRef.current ?? latestPresentedNodesRef.current,
              flowNodesRef.current,
              activeDraggedNodeIdsRef.current,
              changed,
            );
            pendingPresentedNodesRef.current = null;
            flowNodesRef.current = dragResult.nodes;
            setNodes(dragResult.nodes);
            if (dragResult.positions.length) {
              void updateNodePositions(dragResult.positions).catch(() => {
                void refreshWorkflow().catch(() => {});
              });
            }
          }}
          onNodesDelete={deleteNodes}
          onConnect={(connection) => void connect(connection)}
          onEdgesDelete={deleteEdges}
          onPaneContextMenu={(event) => {
            event.preventDefault();
            openCanvasContextMenu({ x: event.clientX, y: event.clientY });
          }}
          onPaneClick={() => {
            clearEdgeSelection();
            setSelectedNodeId(null);
            setAddMenuOpen(false);
            setConnectedNodeMenu(null);
            setContextMenu(null);
          }}
          onMoveStart={() => {
            interruptReveal();
            beginCanvasInteraction("viewport");
          }}
          onMoveEnd={(_event, viewport) => {
            endCanvasInteraction("viewport");
            if (shouldPersistAgentCanvasViewport({ focusedNodeId, layoutPreviewActive })) {
              writeAgentCanvasViewport(workflow.workflow_id, viewport);
            }
          }}
          fitView={false}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <AgentCanvasPointerBackgrounds />
          <Controls position="bottom-left" showInteractive={false} />
        </ReactFlow>

        <div className="agent-canvas-toolbar" aria-label="Canvas controls">
          <div className="agent-canvas-toolbar__add">
            <button
              type="button"
              className={addMenuOpen ? "is-active" : ""}
              aria-label="Add node"
              title="Add node"
              onClick={() => setAddMenuOpen((current) => !current)}
            >
              <PlusIcon />
            </button>
            {addMenuOpen ? (
              <AgentCanvasNodePicker
                className="agent-canvas-node-picker agent-canvas-add-menu"
                menuLabel="Add node types"
                onSelect={(nodeType) => void createNode(nodeType)}
              />
            ) : null}
          </div>
          <div className="agent-canvas-toolbar__layout">
            <button
              ref={layoutButtonRef}
              type="button"
              aria-label="Organize canvas"
              title="Organize canvas"
              disabled={!nodes.length || layoutPreview.active}
              onClick={organizeCanvas}
            >
              <LayoutIcon />
            </button>
            {layoutPreview.active ? (
              <AgentCanvasLayoutConfirmation
                status={layoutPreview.status === "idle" ? "previewing" : layoutPreview.status}
                error={layoutPreview.error}
                onUndo={undoLayoutPreview}
                onDismiss={dismissLayoutPreview}
                onKeep={() => void keepLayoutPreview()}
                dismissExemptRef={pointerSpotlight.hostRef}
              />
            ) : null}
          </div>
          <button
            type="button"
            className={assetsOpen ? "is-active" : ""}
            aria-label="Open assets"
            title="Assets"
            onClick={() => setAssetsOpen(true)}
          >
            <AssetsIcon />
          </button>
          {running ? (
            <button
              type="button"
              aria-label="Cancel run"
              title="Cancel run"
              onClick={() => void cancelCurrentRun()}
            >
              <PauseIcon />
            </button>
          ) : (
            <button
              type="button"
              className="agent-canvas-toolbar__run"
              aria-label="Run all draft nodes"
              title={hasRunnableDraft ? "Run all" : "No prompt-ready drafts"}
              disabled={live.state.runPending || !hasRunnableDraft}
              onClick={() => void runAll().catch((error) => {
                setSurfaceError(error instanceof Error ? error.message : "Run could not start.");
              })}
            >
              <PlayIcon />
            </button>
          )}
          <span className={`agent-canvas-toolbar__connection is-${live.state.connectionState}`} title={live.state.runtimeError ?? undefined}>
            <i aria-hidden="true" />
            {live.state.connectionState}
          </span>
        </div>

        {workflow.nodes.length === 0 ? (
          <div className="agent-canvas-empty">
            <strong>Start with a node or talk to AdCraft Video Agent.</strong>
          </div>
        ) : null}

        {(surfaceError || session.state.authoringError || live.state.runtimeError) ? (
          <button
            type="button"
            className="agent-canvas-notice"
            onClick={() => {
              setSurfaceError(null);
              clearAuthoringError();
            }}
          >
            {surfaceError || session.state.authoringError || live.state.runtimeError}
          </button>
        ) : null}

        {live.state.autoRunNotice ? (
          <button
            type="button"
            className="agent-canvas-notice agent-canvas-notice--info"
            aria-label="Dismiss automatic run notice"
            onClick={clearAutoRunNotice}
          >
            {live.state.autoRunNotice}
          </button>
        ) : null}

        {assetsOpen ? (
          <div className="agent-canvas-overlay" role="dialog" aria-modal="true" aria-label="Project assets">
            <button
              type="button"
              className="agent-canvas-overlay__close"
              aria-label="Close assets"
              title="Close assets"
              onClick={() => setAssetsOpen(false)}
            >
              <CloseIcon />
            </button>
            <Suspense fallback={null}>
              <AgentAssetBrowser
                workflowId={workflow.workflow_id}
                onAddReferences={addReferences}
                onCreateReadySourceNode={createReadySourceNode}
                onUploadComplete={refreshWorkflow}
              />
            </Suspense>
          </div>
        ) : null}

        {editingNode ? (
          <Suspense fallback={null}>
            <AgentCanvasEditingPanel
              workflow={workflow}
              node={editingNode}
              omittedNodeIds={editingPreparation?.omittedNodeIds ?? []}
              patchNode={patchNode}
              onClose={() => setEditingNodeId(null)}
              onAddExportToCanvas={addEditingExportToCanvas}
            />
          </Suspense>
        ) : null}

        {videoPreview ? (
          <Suspense fallback={null}>
            <AgentCanvasVideoPreviewDialog
              asset={videoPreview.asset}
              title={videoPreview.title}
              onClose={closeVideoPreview}
            />
          </Suspense>
        ) : null}

        <input
          ref={referenceUploadInputRef}
          className="agent-canvas-reference-upload-input"
          type="file"
          accept="image/*"
          multiple
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => void uploadSelectedNodeReferences(event)}
        />

        {contextMenu ? (
          <AgentCanvasContextMenu
            menuPosition={contextMenu.menuPosition}
            canvasPosition={contextMenu.canvasPosition}
            onCreateNode={(nodeType, position) => void createNode(nodeType, position)}
            onClose={() => setContextMenu(null)}
            onRelocate={openCanvasContextMenu}
          />
        ) : null}

        {connectedNodeMenu && connectedMenuAnchor && connectionPolicy ? (
          <AgentCanvasConnectedNodeMenu
            anchorNode={connectedMenuAnchor}
            direction={connectedNodeMenu.direction}
            point={connectedNodeMenu.point}
            policy={connectionPolicy}
            onSelect={(nodeType, inputRole) => void createConnectedNodeFromMenu(nodeType, inputRole)}
            onClose={() => setConnectedNodeMenu(null)}
          />
        ) : null}
      </div>

      <Suspense fallback={null}>
        <AgentCanvasChatPanel
          workflow={workflow}
          runtime={live.state.runtime}
          chatRevision={live.state.chatRevision}
          chatEvents={live.state.chatEvents}
          settingsRevision={live.state.settingsRevision}
          documentEvents={live.state.documentEvents}
          onFocusNode={focusNode}
          onActionReceipt={placeReceiptNodes}
          onWorkflowRefresh={refreshWorkflow}
          onRuntimeRefresh={refreshRuntime}
          collapsed={chatCollapsed}
          onCollapsedChange={setChatCollapsed}
          onViewNodes={revealAvailableCanvasNodes}
        />
      </Suspense>
    </div>
  );
}
