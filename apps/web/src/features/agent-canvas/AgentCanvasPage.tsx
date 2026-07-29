import {
  Controls,
  MiniMap,
  ReactFlow,
  type Connection,
  type Edge,
  type NodeChange,
  type ReactFlowInstance,
  type Viewport,
  useNodesState,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createOperationKey } from "../../api/operationKey.ts";
import { isV2ApiError, v2Api } from "../../api/v2Client.ts";
import {
  AssetsIcon,
  CloseIcon,
  DocumentIcon,
  EditIcon,
  ImageIcon,
  MuteIcon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  VideoIcon,
} from "../../icons.tsx";
import type {
  CanvasNodeTypeV2,
  CanvasNodeV2,
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
  type AgentCanvasFlowNode,
  type AgentCanvasNodeCallbacks,
} from "./canvas/index.ts";
import { AgentCanvasPointerBackgrounds } from "./canvas/AgentCanvasPointerBackgrounds.tsx";
import { useCanvasPointerSpotlight } from "./canvas/canvasPointerSpotlight.ts";
import {
  bindingKindForSourceNode,
  findAvailableCanvasPosition,
  toAgentCanvasFlowEdges,
  toAgentCanvasFlowNodes,
} from "./canvas/canvasGraphModel.ts";
import { deleteCanvasEntities } from "./canvas/deleteCanvasEntities.ts";
import { AgentCanvasChatPanel } from "./chat/AgentCanvasChatPanel.tsx";
import { AgentCanvasEditingPanel } from "./editing/AgentCanvasEditingPanel.tsx";
import {
  AGENT_CANVAS_NODE_LABELS,
  createDefaultCanvasNodeRequest,
  sourceAssetSemanticRole,
  sourceAssetStructuredContent,
} from "./model/nodeDefaults.ts";
import { useAgentCanvasProviderModels } from "./model/useAgentCanvasProviderModels.ts";
import { useAgentCanvasRuntime } from "./runtime/useAgentCanvasRuntime.ts";
import { useAgentCanvasSession } from "./session/useAgentCanvasSession.ts";
import { AgentCanvasInspector } from "./AgentCanvasInspector.tsx";
import "@xyflow/react/dist/style.css";
import "./agent-canvas-page.css";

const nodeTypes = { agentCanvas: AgentCanvasNodeRenderer };

function nodeIcon(type: CanvasNodeTypeV2) {
  if (type === "text") return <EditIcon />;
  if (type === "script") return <DocumentIcon />;
  if (type === "image") return <ImageIcon />;
  if (type === "video") return <VideoIcon />;
  if (type === "audio") return <MuteIcon />;
  return <EditIcon />;
}

function viewportStorageKey(workflowId: string): string {
  return `adcraft:agent-canvas:viewport:${workflowId}`;
}

function readViewport(workflowId: string): Viewport | null {
  try {
    const value = window.localStorage.getItem(viewportStorageKey(workflowId));
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<Viewport>;
    if (
      typeof parsed.x !== "number"
      || typeof parsed.y !== "number"
      || typeof parsed.zoom !== "number"
    ) return null;
    return { x: parsed.x, y: parsed.y, zoom: parsed.zoom };
  } catch {
    return null;
  }
}

function writeViewport(workflowId: string, viewport: Viewport): void {
  try {
    window.localStorage.setItem(viewportStorageKey(workflowId), JSON.stringify(viewport));
  } catch {
    // Viewport persistence is disposable and must never block the canvas.
  }
}

function MediaViewer({
  asset,
  onClose,
}: {
  asset: ProjectAssetSummaryV2;
  onClose: () => void;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div
      className="agent-canvas-media-viewer"
      role="dialog"
      aria-modal="true"
      aria-label={asset.display_name}
    >
      <button
        type="button"
        className="agent-canvas-media-viewer__backdrop"
        aria-label="Close media preview"
        onClick={onClose}
      />
      <button
        type="button"
        className="agent-canvas-media-viewer__close"
        aria-label="Close media preview"
        title="Close"
        onClick={onClose}
      >
        <CloseIcon />
      </button>
      <div className="agent-canvas-media-viewer__content">
        {asset.media_type === "image" ? (
          <img src={asset.media_url ?? asset.preview_url ?? ""} alt={asset.display_name} />
        ) : asset.media_type === "video" ? (
          <video
            src={asset.media_url ?? ""}
            poster={asset.preview_url ?? undefined}
            controls
            autoPlay
            playsInline
          />
        ) : (
          <audio src={asset.media_url ?? ""} controls autoPlay />
        )}
      </div>
    </div>
  );
}

export function AgentCanvasPage() {
  const session = useAgentCanvasSession();
  const pointerSpotlight = useCanvasPointerSpotlight<HTMLDivElement>();
  const workflow = session.state.workflow;
  const {
    applyWorkflow,
    clearAuthoringError,
    createBinding,
    createNode: createCanvasNode,
    discardVariationDraft,
    deleteBinding,
    deleteNode,
    materializeVariationDraft,
    mergeNode,
    mergePublishedAsset,
    patchNode,
    placeActionReceiptNodes,
    saveVariationDraft,
    setSelectedNodeId,
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
  const live = useAgentCanvasRuntime(workflow, runtimeCallbacks);
  const providerModels = useAgentCanvasProviderModels(workflow, session.state.selectedNode);
  const {
    cancelRun,
    refreshWorkflow,
    runAll,
    runNode,
  } = live.actions;
  const [nodes, setNodes, onNodesChange] = useNodesState<AgentCanvasFlowNode>([]);
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [mediaAssetId, setMediaAssetId] = useState<string | null>(null);
  const [surfaceError, setSurfaceError] = useState<string | null>(null);
  const flowRef = useRef<ReactFlowInstance<AgentCanvasFlowNode, Edge> | null>(null);

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

  const nodeCallbacks = useMemo<AgentCanvasNodeCallbacks>(() => ({
    onRun: (nodeId) => runNodeById(nodeId, false),
    onRetry: (nodeId) => runNodeById(nodeId, true),
    onExport: openEditing,
    onOpenMedia: (nodeId, assetId) => {
      setSelectedNodeId(nodeId);
      setMediaAssetId(assetId);
    },
  }), [openEditing, runNodeById, setSelectedNodeId]);

  const canonicalNodes = useMemo(
    () => workflow
      ? toAgentCanvasFlowNodes(workflow, live.state.runtime, nodeCallbacks)
      : [],
    [live.state.runtime, nodeCallbacks, workflow],
  );
  const edges = useMemo(
    () => workflow ? toAgentCanvasFlowEdges(workflow.bindings) : [],
    [workflow],
  );

  useEffect(() => {
    setNodes((current) => {
      const byId = new Map(current.map((node) => [node.id, node]));
      return canonicalNodes.map((node) => {
        const existing = byId.get(node.id);
        return existing?.dragging
          ? { ...node, position: existing.position, dragging: true, selected: existing.selected }
          : { ...node, selected: existing?.selected ?? false };
      });
    });
  }, [canonicalNodes, setNodes]);

  useEffect(() => {
    if (
      session.state.selectedNodeId
      && !workflow?.nodes.some((node) => node.node_id === session.state.selectedNodeId)
    ) {
      setSelectedNodeId(null);
    }
  }, [session.state.selectedNodeId, setSelectedNodeId, workflow?.nodes]);

  const handleNodeChanges = useCallback((changes: NodeChange<AgentCanvasFlowNode>[]) => {
    onNodesChange(changes);
  }, [onNodesChange]);

  const connect = useCallback(async (connection: Connection) => {
    if (!workflow || !connection.source || !connection.target || connection.source === connection.target) return;
    const source = workflow.nodes.find((node) => node.node_id === connection.source);
    const target = workflow.nodes.find((node) => node.node_id === connection.target);
    if (!source || !target) return;
    setSurfaceError(null);
    try {
      await createBinding({
        source: { kind: "node", node_id: source.node_id },
        target_node_id: connection.target,
        binding_kind: bindingKindForSourceNode(source),
        required: false,
        display_order: workflow.bindings.filter((binding) => binding.target_node_id === connection.target).length,
      });
    } catch (error) {
      if (isV2ApiError(error) && error.code === "binding_model_incompatible") {
        const compatible = Array.isArray(error.details.compatible_model_ids)
          ? error.details.compatible_model_ids.filter((value): value is string => typeof value === "string")
          : [];
        setSurfaceError(
          compatible.length
            ? `The selected model cannot use this input. Choose ${compatible.join(", ")} in the node settings.`
            : "The selected model cannot use this input. Choose a compatible model in the node settings.",
        );
      } else {
        setSurfaceError(error instanceof Error ? error.message : "The nodes could not be connected.");
      }
    }
  }, [createBinding, workflow]);

  const recoverDeletedCanvasState = useCallback(async () => {
    setNodes(canonicalNodes);
    await refreshWorkflow();
  }, [canonicalNodes, refreshWorkflow, setNodes]);

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

  const createNode = useCallback(async (nodeType: CanvasNodeTypeV2) => {
    if (!workflow) return;
    const instance = flowRef.current;
    const preferredPosition = instance
      ? instance.screenToFlowPosition({ x: window.innerWidth * 0.48, y: window.innerHeight * 0.46 })
      : { x: 120, y: 120 };
    const position = findAvailableCanvasPosition(workflow.nodes, preferredPosition);
    setSurfaceError(null);
    setAddMenuOpen(false);
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
        source: { kind: "image_asset", asset_id: selection.assetId },
        target_node_id: targetNodeId,
        binding_kind: "image_reference",
        required: false,
        display_order: startOrder + index,
      });
    }
  }, [createBinding, session.state.selectedNode, workflow]);

  const createReadySourceNode = useCallback(async (selection: AgentAssetSourceNodeSelection) => {
    if (!workflow) return;
    const instance = flowRef.current;
    const preferredPosition = instance
      ? instance.screenToFlowPosition({ x: window.innerWidth * 0.5, y: window.innerHeight * 0.5 })
      : { x: 180, y: 160 };
    const position = findAvailableCanvasPosition(workflow.nodes, preferredPosition);
    await createCanvasNode({
      node_type: selection.mediaType,
      semantic_role: sourceAssetSemanticRole(selection.mediaType),
      role_contract_version: "ad-media-role-v1",
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

  const saveImageToLibrary = useCallback(async (
    assetId: string,
    request: SaveAgentCanvasImageToLibraryRequestV2,
  ) => {
    await v2Api.saveAgentCanvasImageToLibrary(
      assetId,
      request,
      createOperationKey("save-image-to-library"),
    );
  }, []);

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

  const initializeFlow = useCallback((instance: ReactFlowInstance<AgentCanvasFlowNode, Edge>) => {
    flowRef.current = instance;
    if (!workflow) return;
    const saved = readViewport(workflow.workflow_id);
    if (saved) {
      void instance.setViewport(saved, { duration: 0 });
    } else if (workflow.nodes.length) {
      window.setTimeout(() => void instance.fitView({ padding: 0.22, maxZoom: 1, duration: 350 }), 0);
    }
  }, [workflow]);

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
  const mediaAsset = mediaAssetId
    ? workflow.assets.find((asset) => asset.asset_id === mediaAssetId) ?? null
    : null;
  const running = Boolean(live.state.runtime?.active_execution_id);
  const proposalPreferredPosition = flowRef.current?.screenToFlowPosition({
    x: window.innerWidth * 0.46,
    y: window.innerHeight * 0.42,
  }) ?? { x: 160, y: 120 };
  const proposalPosition = findAvailableCanvasPosition(
    workflow.nodes,
    proposalPreferredPosition,
  );

  return (
    <div className="agent-canvas-page">
      <div
        ref={pointerSpotlight.hostRef}
        className="agent-canvas-board"
        onPointerMove={pointerSpotlight.onPointerMove}
        onPointerLeave={pointerSpotlight.onPointerLeave}
        onPointerCancel={pointerSpotlight.onPointerCancel}
      >
        <ReactFlow<AgentCanvasFlowNode, Edge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          minZoom={0.05}
          maxZoom={2}
          deleteKeyCode={["Backspace", "Delete"]}
          multiSelectionKeyCode={["Meta", "Control"]}
          selectionKeyCode="Shift"
          panOnScroll
          selectionOnDrag
          onInit={initializeFlow}
          onNodesChange={handleNodeChanges}
          onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
          onNodeDragStop={(_event, node, draggedNodes) => {
            const changed = draggedNodes.length ? draggedNodes : [node];
            void updateNodePositions(changed.map((item) => ({
              node_id: item.id,
              x: item.position.x,
              y: item.position.y,
            }))).catch(() => {});
          }}
          onNodesDelete={deleteNodes}
          onConnect={(connection) => void connect(connection)}
          onEdgesDelete={deleteEdges}
          onPaneClick={() => {
            setSelectedNodeId(null);
            setAddMenuOpen(false);
          }}
          onMoveEnd={(_event, viewport) => writeViewport(workflow.workflow_id, viewport)}
          fitView={false}
          colorMode="system"
        >
          <AgentCanvasPointerBackgrounds />
          <Controls position="bottom-left" showInteractive={false} />
          <MiniMap
            position="bottom-right"
            pannable
            zoomable
            nodeColor={(node) => {
              const type = (node.data as AgentCanvasFlowNode["data"]).node.node_type;
              if (type === "image") return "#4c9d8d";
              if (type === "audio") return "#b88248";
              if (type === "video" || type === "editing") return "#567dd0";
              return "#7667b5";
            }}
          />
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
              <div className="agent-canvas-add-menu">
                {(Object.keys(AGENT_CANVAS_NODE_LABELS) as CanvasNodeTypeV2[]).map((type) => (
                  <button type="button" key={type} onClick={() => void createNode(type)}>
                    {nodeIcon(type)}
                    <span>{AGENT_CANVAS_NODE_LABELS[type]}</span>
                  </button>
                ))}
              </div>
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
              title="Run all"
              disabled={live.state.runPending}
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

        {session.state.selectedNode ? (
          <AgentCanvasInspector
            workflow={workflow}
            node={session.state.selectedNode}
            patchNode={patchNode}
            providerCapabilities={providerModels.capabilities}
            providerCapabilitiesLoading={providerModels.loading}
            providerCapabilitiesError={providerModels.error}
            onRun={runNode}
            onSaveVariation={saveVariationDraft}
            onDiscardVariation={discardVariationDraft}
            onMaterializeVariation={materializeVariationDraft}
            onSaveImageToLibrary={saveImageToLibrary}
            onDelete={deleteNode}
            onOpenEditing={() => openEditing(session.state.selectedNode!.node_id)}
            onClose={() => setSelectedNodeId(null)}
          />
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
            patchNode={patchNode}
            onClose={() => setEditingNodeId(null)}
          />
        ) : null}

        {mediaAsset ? (
          <MediaViewer asset={mediaAsset} onClose={() => setMediaAssetId(null)} />
        ) : null}
      </div>

      <AgentCanvasChatPanel
        workflow={workflow}
        chatRevision={live.state.chatRevision}
        chatEvents={live.state.chatEvents}
        proposalPosition={proposalPosition}
        onFocusNode={focusNode}
        onActionReceipt={placeReceiptNodes}
      />
    </div>
  );
}
