import {
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
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

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
import {
  AgentAssetBrowser,
  type AgentAssetReferenceSelection,
  type AgentAssetSourceNodeSelection,
} from "./assets/AgentAssetBrowser.tsx";
import {
  AgentCanvasNodeRenderer,
  AgentCanvasVideoPreviewDialog,
  type AgentCanvasFlowNode,
  type AgentCanvasNodeCallbacks,
} from "./canvas/index.ts";
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
  writeAgentCanvasViewport,
} from "./canvas/agentCanvasViewport.ts";
import {
  reconcileDragAwareNodes,
  setDraggedNodeIds,
} from "./canvas/draggingNodeState.ts";
import {
  findAvailableCanvasPosition,
  highlightNodeRelatedCanvasEdges,
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
import { useAgentCanvasLayoutPreview } from "./canvas/useAgentCanvasLayoutPreview.ts";
import { AgentCanvasChatPanel } from "./chat/AgentCanvasChatPanel.tsx";
import { AgentCanvasEditingPanel } from "./editing/AgentCanvasEditingPanel.tsx";
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
import { AgentCanvasInlineWorkbench } from "./workbench/AgentCanvasInlineWorkbench.tsx";
import "@xyflow/react/dist/style.css";
import "./agent-canvas-page.css";

const nodeTypes = { agentCanvas: AgentCanvasNodeRenderer };

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
  const [nodes, setNodes, onNodesChange] = useNodesState<AgentCanvasFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
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
  const installedViewportWorkflowIdRef = useRef<string | null>(null);
  const viewportInstallFrameRef = useRef<number | null>(null);
  const layoutButtonRef = useRef<HTMLButtonElement>(null);
  const activeDraggedNodeIdsRef = useRef(new Set<string>());
  const referenceUploadInputRef = useRef<HTMLInputElement>(null);
  activeWorkflowIdRef.current = workflow?.workflow_id ?? "no-workflow";
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
    focusNode: focusCanvasNode,
    exitFocus: exitCanvasNodeFocus,
    scheduleExitForNodeSelection,
  } = useAgentCanvasNodeFocus({
    flowRef,
    scopeKey: workflow?.workflow_id ?? "no-workflow",
  });

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
        await createBinding({
          source: { kind: "image_asset", source_asset_id: uploaded.asset.asset_id },
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
        onOpenAssets={() => setAssetsOpen(true)}
        onUploadReferences={() => referenceUploadInputRef.current?.click()}
        onClose={() => setSelectedNodeId(null)}
      />
    );
  }, [connectionPolicy, deleteBinding, deleteNode, discardVariationDraft, live.state.inputManifestsByNodeId, live.state.inputReadinessIssue, live.state.modelResolutionsByNodeId, materializeVariationDraft, openEditing, patchBinding, patchNode, providerModels.error, providerModels.loading, providerModels.models, runNode, saveImageToLibrary, saveVariationDraft, session.state.selectedNodeId, setSelectedNodeId, workflow]);

  const nodeCallbacks = useMemo<AgentCanvasNodeCallbacks>(() => ({
    onRun: (nodeId) => runNodeById(nodeId, false),
    onRetry: (nodeId) => runNodeById(nodeId, true),
    onExport: openEditing,
    onOpenVideoPreview: (nodeId, asset) => {
      const node = workflow?.nodes.find((candidate) => candidate.node_id === nodeId);
      setVideoPreview({
        asset,
        title: asset.display_name || node?.title || "Video preview",
      });
    },
    renderWorkbench,
    onOpenConnectedNodeMenu: (nodeId, direction, point) => {
      setSelectedNodeId(nodeId);
      setConnectedNodeMenu({ anchorNodeId: nodeId, direction, point });
    },
  }), [openEditing, renderWorkbench, runNodeById, setSelectedNodeId, workflow?.nodes]);

  const canonicalNodes = useMemo(
    () => workflow
      ? toAgentCanvasFlowNodes(workflow, live.state.runtime, nodeCallbacks)
      : [],
    [live.state.runtime, nodeCallbacks, workflow],
  );
  const presentedNodes = useMemo<AgentCanvasFlowNode[]>(
    () => overlayLayoutPreview(canonicalNodes) as AgentCanvasFlowNode[],
    [canonicalNodes, overlayLayoutPreview],
  );
  const canonicalEdges = useMemo(
    () => workflow ? toAgentCanvasFlowEdges(workflow.bindings, workflow.nodes) : [],
    [workflow],
  );
  const presentedEdges = useMemo(
    () => highlightNodeRelatedCanvasEdges(canonicalEdges, session.state.selectedNodeId),
    [canonicalEdges, session.state.selectedNodeId],
  );

  useEffect(() => {
    setNodes((current) => {
      return reconcileDragAwareNodes(
        presentedNodes,
        current,
        activeDraggedNodeIdsRef.current,
      );
    });
  }, [presentedNodes, setNodes]);

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
    onNodesChange(changes);
  }, [onNodesChange]);

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
        source: { kind: "image_asset", source_asset_id: selection.assetId },
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

  const focusNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    void flowRef.current?.fitView({
      nodes: [{ id: nodeId }],
      padding: 0.55,
      duration: 420,
      maxZoom: 1.15,
    });
  }, [setSelectedNodeId]);

  const placeReceiptNodes = useCallback((receipt: Parameters<typeof placeActionReceiptNodes>[0]) => {
    const viewportAnchor = flowRef.current?.screenToFlowPosition({
      x: window.innerWidth * 0.46,
      y: window.innerHeight * 0.42,
    }) ?? { x: 160, y: 120 };
    void placeActionReceiptNodes(receipt, viewportAnchor).catch((error) => {
      setSurfaceError(error instanceof Error ? error.message : "New canvas nodes could not be positioned.");
    });
  }, [placeActionReceiptNodes]);

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
        className={`agent-canvas-board${layoutPreview.active ? " is-layout-previewing" : ""}`}
        onContextMenu={(event) => event.preventDefault()}
        onPointerMove={pointerSpotlight.onPointerMove}
        onPointerLeave={pointerSpotlight.onPointerLeave}
        onPointerCancel={pointerSpotlight.onPointerCancel}
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
            setDraggedNodeIds(
              activeDraggedNodeIdsRef.current,
              node.id,
              draggedNodes.map((item) => item.id),
              true,
            );
          }}
          onNodeDragStop={(_event, node, draggedNodes) => {
            const changed = draggedNodes.length ? draggedNodes : [node];
            setDraggedNodeIds(
              activeDraggedNodeIdsRef.current,
              node.id,
              changed.map((item) => item.id),
              false,
            );
            void updateNodePositions(changed.map((item) => ({
              node_id: item.id,
              x: item.position.x,
              y: item.position.y,
            }))).catch(() => {});
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
          onMoveEnd={(_event, viewport) => {
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
            <AgentAssetBrowser
              workflowId={workflow.workflow_id}
              onAddReferences={addReferences}
              onCreateReadySourceNode={createReadySourceNode}
              onUploadComplete={refreshWorkflow}
            />
          </div>
        ) : null}

        {editingNode ? (
          <AgentCanvasEditingPanel
            workflow={workflow}
            node={editingNode}
            omittedNodeIds={editingPreparation?.omittedNodeIds ?? []}
            patchNode={patchNode}
            onClose={() => setEditingNodeId(null)}
          />
        ) : null}

        {videoPreview ? (
          <AgentCanvasVideoPreviewDialog
            asset={videoPreview.asset}
            title={videoPreview.title}
            onClose={closeVideoPreview}
          />
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

      <AgentCanvasChatPanel
        workflow={workflow}
        chatRevision={live.state.chatRevision}
        chatEvents={live.state.chatEvents}
        settingsRevision={live.state.settingsRevision}
        documentEvents={live.state.documentEvents}
        onFocusNode={focusNode}
        onActionReceipt={placeReceiptNodes}
        onWorkflowRefresh={refreshWorkflow}
        onRuntimeRefresh={refreshRuntime}
        onCollapsedChange={setChatCollapsed}
      />
    </div>
  );
}
