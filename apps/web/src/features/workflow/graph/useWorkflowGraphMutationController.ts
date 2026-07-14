import { useEffect, useRef } from "react";
import {
  MarkerType,
  addEdge,
  reconnectEdge,
  type Connection,
  type ReactFlowInstance,
} from "@xyflow/react";
import { api } from "../../../api/client.ts";
import { v2Api } from "../../../api/v2Client.ts";
import {
  assetLibraryUploadOptionsForKind,
  dispatchAssetLibraryUploadEvent,
  isSupportedUploadMime,
  uploadOptionsForNode,
} from "../../../api/workflowNormalizers.ts";
import type {
  AdRequest,
  AssetLibraryEntitySummary,
  AssetLibraryReference,
  AssetLibraryUploadKind,
  FrontDeskMessage,
  GraphValidationResult,
  MediaStatus,
  NodeRunResult,
  ResolvedNodeInputs,
  UploadedAsset,
  WorkflowGraph,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeVersion,
  WorkflowRunResponse,
  WorkflowVariable,
} from "../../../types.ts";
import type { ProjectSessionState, SavedWorkflowProject } from "../../../projects/newProject.ts";
import { shouldApplyWorkflowScopedResult } from "../../../workflow/sessionGuards.ts";
import {
  createNodeRunMap,
  mergeWorkflowNodesWithRuns,
} from "../../../workflow/runtimeResults.ts";
import {
  buildOptimizeOnlyNodeRunRequest,
} from "../../../workflow/nodeRunContext.ts";
import {
  firstVisibleWorkflowNodeId,
  isUserVisibleWorkflowNode,
} from "../../../workflow/visibility.ts";
import {
  getWorkflowNodeType,
} from "../canvas/workflowNodeModel.ts";
import {
  DEFAULT_LAYOUT_VIEWPORT_PADDING,
  edgeStyle,
  getConnectionDataType,
  getConnectionLabel,
  layoutNodes,
  mapWorkflowEdges,
  mapWorkflowNodes,
  mergeBackendEdge,
  portColor,
  syncWorkflowNodePositions,
  validateConnection,
} from "../canvas/workflowCanvasModel.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import {
  getNodePrompt,
  toEdgeMutationPayload,
  toNodeMutationPayload,
  toWorkflowEdges,
  toWorkflowGraphPayload,
} from "./workflowGraphPayloadModel.ts";
import { formatPromptOptimizerError } from "../runtime/workflowExecutionViewModel.ts";
import {
  buildNodePromptPatch,
  mergeResolvedInputContext,
  promptStringFromRun,
  resolvedInputsFromNodeRun,
} from "../runtime/resolvedInputsViewModel.ts";
import { promptFromNodePatch } from "../v2/v2PromptModel.ts";
import { v2RegionItemsForNode } from "../v2/v2RegionNode.ts";
import { splitAssetLibraryTags } from "../assets/assetLibraryReferenceModel.ts";
import type { SaveCanvasOptions, WorkflowGraphMutationControllerArgs } from "./workflowGraphMutationControllerTypes.ts";

export function useWorkflowGraphMutationController(args: WorkflowGraphMutationControllerArgs) {
  const argsRef = useRef(args);

  useEffect(() => {
    argsRef.current = args;
  }, [args]);

  async function saveCanvas(options?: SaveCanvasOptions) {
    const current = argsRef.current;
    const sourceCanvasNodes = options?.nodes ?? current.canvasNodes;
    current.persistLocalSnapshot(sourceCanvasNodes, { immediate: true });
    if (!current.workflow?.workflow_id) {
      current.saveProject();
      const message = "Saved locally. Generate a workflow plan before backend run/save.";
      if (!options?.quiet || options?.requireBackend) current.setStatus(message);
      return !options?.requireBackend;
    }
    const requestWorkflowId = current.workflow.workflow_id;
    if (current.currentWorkflowIsV2()) {
      current.setSaving(true);
      try {
        const graph = await current.refreshV2WorkflowGraph(requestWorkflowId);
        if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return false;
        if (graph) {
          const now = new Date().toLocaleTimeString();
          current.setSavedAt(now);
          current.saveProject({
            workflow: current.workflow,
            messages: current.messages,
            nodeRuns: [],
            selectedAssets: current.selectedAssets,
            promptLibraryEntities: current.promptLibraryEntities,
          });
          if (!options?.quiet) current.setStatus(`Saved ${now}`);
          return true;
        }
        if (options?.requireBackend) current.setStatus("V2 workflow save failed. Run cancelled.");
        return !options?.requireBackend;
      } finally {
        current.setSaving(false);
      }
    }
    current.setSaving(true);
    try {
      let latestNodeRuns = current.nodeRuns;
      try {
        latestNodeRuns = (await api.workflowNodes(requestWorkflowId)).nodes ?? current.nodeRuns;
        if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return false;
        current.applyNodeRunsToCanvas(latestNodeRuns);
      } catch {
        if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return false;
        latestNodeRuns = current.nodeRuns;
      }
      const runtimeRunMap = createNodeRunMap(latestNodeRuns);
      const runtimeNodes = mergeWorkflowNodesWithRuns(sourceCanvasNodes, runtimeRunMap);
      const nextWorkflow = toWorkflowGraphPayload(current.workflow, runtimeNodes, current.flowNodes, current.flowEdges, current.getCurrentRunAdRequest());
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return false;
      current.assertNotV2WorkflowForV1Api(requestWorkflowId, "save");
      const savedGraph = await api.saveWorkflow(requestWorkflowId, nextWorkflow);
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return false;
      const graphNodes = savedGraph.nodes?.length ? mergeWorkflowNodesWithRuns(savedGraph.nodes, runtimeRunMap) : runtimeNodes;
      const graph = {
        ...current.workflow,
        ...savedGraph,
        nodes: graphNodes,
        edges: savedGraph.edges?.length ? savedGraph.edges : nextWorkflow.edges,
        variables: current.workflowVariables,
      };
      current.setWorkflow(graph);
      current.setCanvasNodes(graphNodes);
      current.setFlowNodes((flowNodes) => {
        const nextFlowNodes = mapWorkflowNodes(graphNodes, runtimeRunMap, flowNodes);
        current.setFlowEdges(mapWorkflowEdges(graph.edges, nextFlowNodes));
        return nextFlowNodes;
      });
      current.noteAffected(savedGraph.affected_downstream_nodes);
      const now = new Date().toLocaleTimeString();
      current.setSavedAt(now);
      current.saveProject({
        workflow: graph,
        messages: current.messages,
        nodeRuns: latestNodeRuns,
        selectedAssets: current.selectedAssets,
        promptLibraryEntities: current.promptLibraryEntities,
      });
      if (!options?.quiet) current.setStatus(`Saved ${now}`);
      return true;
    } catch (error) {
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, current.activeWorkflowIdRef.current)) return false;
      const message = error instanceof Error ? `Backend save failed: ${error.message}` : "Backend save failed";
      current.setStatus(options?.requireBackend ? `${message}. Run cancelled.` : `Local saved, ${message}`);
      return false;
    } finally {
      current.setSaving(false);
    }
  }

  function createNewProjectFromCanvas() {
    const current = argsRef.current;
    current.persistLocalSnapshot(undefined, { immediate: true });
    current.activeWorkflowIdRef.current = null;
    current.startNewProject();
    const emptyRunMap = new Map<string, NodeRunResult>();
    const nextFlowNodes = mapWorkflowNodes(current.demoNodes, emptyRunMap, []);
    const nextFlowEdges = mapWorkflowEdges(current.demoEdges, nextFlowNodes);
    const nextLayoutNodes = layoutNodes(nextFlowNodes, nextFlowEdges);
    current.setCanvasNodes(syncWorkflowNodePositions(current.demoNodes, nextLayoutNodes));
    current.setFlowNodes(nextLayoutNodes);
    current.setFlowEdges(nextFlowEdges);
    current.setWorkflowVariables([]);
    current.setSelectedNodeId(firstVisibleWorkflowNodeId(current.demoNodes, "prompt"));
    current.setSelectedNodeRun(null);
    current.setSelectedResolvedInputs(null);
    current.setMediaStatus(null);
    current.setWorkflowRun(null);
    current.setWorkflowRunning(false);
    current.currentNodeRunningRef.current = false;
    current.currentNodeRunRequestRef.current += 1;
    current.setCurrentNodeRunning(false);
    current.setValidationResult(null);
    current.setNodeVersions([]);
    current.setAffectedNodes([]);
    current.resetExportState();
    current.setSavedAt(null);
    current.setDetailsOpen(false);
    current.setMediaLightbox(null);
    current.clearCanvasHistory();
    current.setStatus("New project ready");
    window.setTimeout(() => current.reactFlow?.fitView({ padding: DEFAULT_LAYOUT_VIEWPORT_PADDING }), 0);
  }

  async function flushNodePatch(nodeId: string) {
    const current = argsRef.current;
    const pending = current.pendingNodePatches.current.get(nodeId);
    if (!pending || !current.workflow?.workflow_id) return;
    window.clearTimeout(pending.timerId);
    current.pendingNodePatches.current.delete(nodeId);
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 node edits use item and slot prompt APIs.");
      return;
    }
    try {
      const nextNode = { ...pending.baseNode, ...pending.patch };
      const result = await api.updateWorkflowNode(current.workflow.workflow_id, nodeId, toNodeMutationPayload(nextNode, pending.sourceFlowNode));
      current.setCanvasNodes((nodes) => nodes.map((node) => (node.id === nodeId ? { ...node, ...result.node } : node)));
      current.noteAffected(result.affected_downstream_nodes);
      void current.refreshNodeVersions(nodeId, { force: true });
    } catch (error) {
      current.setStatus(error instanceof Error ? `Local edit saved, backend patch failed: ${error.message}` : "Local edit saved");
    }
  }

  function scheduleNodePatch(nodeId: string, baseNode: WorkflowNode, patch: Partial<WorkflowNode>, sourceFlowNode?: CanvasNode) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) return;
    const queued = current.pendingNodePatches.current.get(nodeId);
    if (queued) window.clearTimeout(queued.timerId);
    const nextPatch = { ...(queued?.patch ?? {}), ...patch };
    const timerId = window.setTimeout(() => {
      void flushNodePatch(nodeId);
    }, 700);
    current.pendingNodePatches.current.set(nodeId, {
      patch: nextPatch,
      baseNode: queued?.baseNode ?? baseNode,
      sourceFlowNode: sourceFlowNode ?? queued?.sourceFlowNode,
      timerId,
    });
  }

  async function updateSelectedNode(patch: Partial<WorkflowNode>, options: { debounce?: boolean } = {}) {
    const current = argsRef.current;
    if (!current.selectedPlanNode) return;
    current.captureCanvasHistory();
    const nextPatch = patch;
    current.setCanvasNodes((nodes) =>
      nodes.map((node) => (node.id === current.selectedPlanNode?.id ? { ...node, ...nextPatch } : node)),
    );
    if (!current.workflow?.workflow_id) return;
    if (current.currentWorkflowIsV2()) {
      const prompt = promptFromNodePatch(nextPatch);
      const item = v2RegionItemsForNode(current.selectedPlanNode)[0];
      if (prompt && item) {
        try {
          const nextWorkflow = await v2Api.updateItemPrompt(current.workflow.workflow_id, item.item_id, { item_prompt: prompt });
          if (!shouldApplyWorkflowScopedResult(current.workflow.workflow_id, current.activeWorkflowIdRef.current)) return;
          await current.refreshV2WorkflowGraph(nextWorkflow.workflow_id);
          current.setStatus(`${item.display_name || current.selectedPlanNode.title} prompt saved`);
        } catch (error) {
          current.setStatus(error instanceof Error ? error.message : "V2 item prompt update failed");
        }
      }
      return;
    }
    const sourceFlowNode = current.flowNodes.find((node) => node.id === current.selectedPlanNode?.id);
    if (options.debounce === false) {
      scheduleNodePatch(current.selectedPlanNode.id, current.selectedPlanNode, nextPatch, sourceFlowNode);
      await flushNodePatch(current.selectedPlanNode.id);
      return;
    }
    scheduleNodePatch(current.selectedPlanNode.id, current.selectedPlanNode, nextPatch, sourceFlowNode);
  }

  function updateSelectedPrompt(prompt: string) {
    const current = argsRef.current;
    if (!current.selectedPlanNode) return;
    void updateSelectedNode(buildNodePromptPatch(current.selectedPlanNode, prompt, "user"));
  }

  function applySystemSuggestion() {
    const current = argsRef.current;
    if (!current.selectedPlanNode || !current.selectedSystemSuggestion) return;
    void updateSelectedNode(buildNodePromptPatch(current.selectedPlanNode, current.selectedSystemSuggestion, "system_suggestion_applied", { has_new_system_suggestion: false }), { debounce: false });
  }

  function applyOptimizedPrompt() {
    const current = argsRef.current;
    if (!current.selectedPlanNode || !current.selectedOptimizedPrompt) return;
    void updateSelectedNode(buildNodePromptPatch(current.selectedPlanNode, current.selectedOptimizedPrompt, "optimized_applied"), { debounce: false });
  }

  async function regenerateOptimizedPrompt() {
    const current = argsRef.current;
    if (!current.selectedPlanNode) {
      current.setStatus("Select a node first.");
      return;
    }
    const editablePrompt = getNodePrompt(current.selectedPlanNode).trim();
    if (!editablePrompt) {
      current.setStatus("Enter an editable prompt before optimizing.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 prompt optimization is handled through item and slot prompt actions.");
      return;
    }
    if (current.workflow?.workflow_id) {
      const saved = await saveCanvas({ quiet: true, requireBackend: true });
      if (!saved) return;
    }

    current.setStatus(`Regenerating optimized prompt for ${current.selectedRunType}...`);
    try {
      const cachedResolvedInputs = current.selectedResolvedInputs?.node_id === current.selectedPlanNode.id ? current.selectedResolvedInputs : null;
      const resolvedInputs = current.workflow?.workflow_id
        ? (await current.refreshSelectedResolvedInputs(current.selectedPlanNode.id, { force: true })) ?? cachedResolvedInputs
        : null;
      const result = await api.runNode(buildOptimizeOnlyNodeRunRequest(
        current.selectedPlanNode,
        current.workflow?.workflow_id,
        editablePrompt,
        current.workflowVariables,
        resolvedInputs,
        current.nodeScopedAssetReferences(),
      ));
      const optimizedResult = {
        ...result,
        node_id: result.node_id || current.selectedPlanNode.id,
        input_assets: current.selectedPlanNode.input_assets,
        output_assets: [],
      };
      const optimizedPrompt =
        promptStringFromRun(optimizedResult, "optimized_generation_prompt") ||
        promptStringFromRun(optimizedResult, "generation_prompt");
      const providerPrompt = promptStringFromRun(optimizedResult, "provider_prompt");
      current.setSelectedNodeRun(optimizedResult);
      current.applyNodeRunsToCanvas([optimizedResult]);
      current.setSelectedResolvedInputs(resolvedInputsFromNodeRun(optimizedResult));
      const mergedInputContext = mergeResolvedInputContext({
        ...(current.selectedPlanNode.input_context ?? {}),
        user_prompt: editablePrompt,
      }, optimizedResult);
      void updateSelectedNode({
        input_context: {
          ...(mergedInputContext ?? {}),
          user_prompt: editablePrompt,
          ...(optimizedPrompt ? { optimized_generation_prompt: optimizedPrompt } : {}),
          ...(providerPrompt ? { provider_prompt: providerPrompt } : {}),
        },
        metadata: {
          ...(current.selectedPlanNode.metadata ?? {}),
          prompt_source: current.selectedPlanNode.metadata?.prompt_source ?? "user",
          manual_prompt_dirty: Boolean(current.selectedPlanNode.metadata?.manual_prompt_dirty),
          ...(optimizedPrompt ? { optimized_generation_prompt: optimizedPrompt } : {}),
        },
      }, { debounce: false });
      if (result.workflow_id) {
        current.setWorkflow((workflow) => workflow ?? { workflow_id: result.workflow_id, nodes: current.canvasNodes, edges: toWorkflowEdges(current.flowEdges) });
        await current.refreshWorkflowGraph(result.workflow_id, [...current.nodeRuns, optimizedResult]);
      }
      current.setStatus(`${current.selectedRunType} optimized prompt regenerated`);
    } catch (error) {
      const optimizerError = formatPromptOptimizerError(error);
      current.setStatus(optimizerError.message || "Optimized prompt regeneration failed");
    }
  }

  function updateSelectedConfig(value: string) {
    const current = argsRef.current;
    if (!current.selectedPlanNode) return;
    try {
      const config = value.trim() ? JSON.parse(value) : {};
      void updateSelectedNode({ config });
    } catch {
      current.setStatus("Config must be valid JSON");
    }
  }

  function updateSelectedConfigField(key: string, value: unknown) {
    const current = argsRef.current;
    if (!current.selectedPlanNode) return;
    void updateSelectedNode({
      config: {
        ...(current.selectedPlanNode.config ?? {}),
        [key]: value,
      },
    });
  }

  async function uploadAssetForSelectedNode(files: FileList | null) {
    const current = argsRef.current;
    if (!current.selectedPlanNode || !files?.length) return;
    const selectedFiles = Array.from(files);
    const unsupportedFiles = selectedFiles.filter((file) => !isSupportedUploadMime(file.type, file.name));
    if (unsupportedFiles.length) {
      current.setStatus(`Backend uploads currently support image, video, audio, or document files: ${unsupportedFiles.map((file) => file.name).join(", ")}`);
      return;
    }

    current.setUploadingAsset(true);
    current.setStatus("Uploading node asset...");
    try {
      const uploaded: UploadedAsset[] = [];
      const nodeType = getWorkflowNodeType(current.selectedPlanNode);
      const selectedUploadKind: AssetLibraryUploadKind = current.nodeUploadKind || (nodeType === "product-generation" ? "product" : "");
      const selectedUploadRole = selectedUploadKind === "product" ? "product" : "reference";
      const uploadMetadata = {
        display_name: current.nodeUploadName,
        tags: splitAssetLibraryTags(current.nodeUploadTags),
      };
      const explicitUploadOptions = assetLibraryUploadOptionsForKind(current.nodeUploadKind, uploadMetadata);
      const effectiveUploadOptions = current.nodeUploadKind ? explicitUploadOptions : assetLibraryUploadOptionsForKind(selectedUploadKind, uploadMetadata);
      for (const file of selectedFiles) {
        const asset = await api.uploadAsset(file, {
          ...uploadOptionsForNode(nodeType, selectedUploadRole, file.type),
          ...effectiveUploadOptions,
          ...(selectedUploadKind === "product"
            ? {
                asset_role: "product",
                entity_type: "product",
                semantic_type: "product_reference",
                use_as_prompt: true,
              }
            : {}),
        });
        uploaded.push(asset);
        dispatchAssetLibraryUploadEvent(asset);
      }
      await updateSelectedNode({
        input_assets: [...(current.selectedPlanNode.input_assets ?? []), ...uploaded],
      }, { debounce: false });
      current.setStatus(`${uploaded.length} asset(s) attached to ${current.selectedPlanNode.title}`);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Asset upload failed");
    } finally {
      current.setUploadingAsset(false);
    }
  }

  function removeSelectedInputAsset(assetId: string) {
    const current = argsRef.current;
    if (!current.selectedPlanNode) return;
    void updateSelectedNode({
      input_assets: (current.selectedPlanNode.input_assets ?? []).filter((asset) => asset.asset_id !== assetId),
    }, { debounce: false });
  }

  function addWorkflowVariable(type: WorkflowVariable["variable_type"] = "string") {
    const current = argsRef.current;
    current.captureCanvasHistory();
    const variable: WorkflowVariable = {
      variable_id: `var-${Date.now().toString(36)}`,
      name: type === "resource" ? "reference_asset" : type === "option" ? "aspect_ratio" : "product_name",
      description: "",
      variable_type: type,
      required: type !== "option",
      resource_types: type === "resource" ? ["image", "video", "audio", "document"] : undefined,
      options: type === "option" ? ["16:9", "9:16", "1:1"] : undefined,
      is_single: true,
      value: type === "option" ? "16:9" : "",
    };
    current.setWorkflowVariables((variables) => [...variables, variable]);
    current.setVariablesPanelOpen(true);
    current.setStatus("Workflow variable added");
  }

  function updateWorkflowVariable(variableId: string, patch: Partial<WorkflowVariable>) {
    const current = argsRef.current;
    current.captureCanvasHistory();
    current.setWorkflowVariables((variables) => variables.map((variable) => (variable.variable_id === variableId ? { ...variable, ...patch } : variable)));
  }

  function deleteWorkflowVariable(variableId: string) {
    const current = argsRef.current;
    current.captureCanvasHistory();
    current.setWorkflowVariables((variables) => variables.filter((variable) => variable.variable_id !== variableId));
  }

  async function toggleSelectedLock() {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a backend workflow before locking nodes.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 lock state is managed by backend item and slot contracts.");
      return;
    }
    try {
      const result = current.selectedPlanNode.locked
        ? await api.unlockWorkflowNode(current.workflow.workflow_id, current.selectedPlanNode.id)
        : await api.lockWorkflowNode(current.workflow.workflow_id, current.selectedPlanNode.id);
      current.patchWorkflowNodeState([current.selectedPlanNode.id], { locked: result.locked });
      current.setStatus(result.locked ? `${current.selectedPlanNode.title} locked` : `${current.selectedPlanNode.title} unlocked`);
      void current.refreshWorkflowGraph(current.workflow.workflow_id);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Lock update failed");
    }
  }

  async function markSelectedStale(includeDownstream: boolean) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id || !current.selectedPlanNode) {
      current.setStatus("Generate a backend workflow before marking stale.");
      return;
    }
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 stale state is managed by backend item, slot, and runtime events.");
      return;
    }
    try {
      const result = await api.markStale(current.workflow.workflow_id, {
        node_ids: [current.selectedPlanNode.id],
        include_downstream: includeDownstream,
        reason: current.staleReason || "Manual canvas change",
      });
      current.markNodesStale(result.stale_nodes, current.staleReason || "Manual canvas change");
      current.setAffectedNodes(result.stale_nodes);
      current.setStatus(`${result.stale_nodes.length} node(s) marked stale`);
      void current.refreshWorkflowGraph(current.workflow.workflow_id);
    } catch (error) {
      current.setStatus(error instanceof Error ? error.message : "Mark stale failed");
    }
  }

  async function deleteSelection() {
    const current = argsRef.current;
    const selectedEdgeIds = new Set(current.flowEdges.filter((edge) => edge.selected).map((edge) => edge.id));
    const selectedFlowNodeIds = current.flowNodes.filter((node) => node.selected).map((node) => node.id);
    const selectedNodeIds = selectedFlowNodeIds.length || selectedEdgeIds.size ? selectedFlowNodeIds : current.selectedNodeId ? [current.selectedNodeId] : [];
    if (!selectedNodeIds.length && !selectedEdgeIds.size) return;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 region nodes and display edges are backend-defined. Use V2 item, slot, reference, or free-node actions instead.");
      return;
    }
    current.captureCanvasHistory();

    if (current.workflow?.workflow_id) {
      for (const edgeId of selectedEdgeIds) await deleteEdgeFromBackend(edgeId);
      for (const nodeId of selectedNodeIds) await deleteNodeFromBackend(nodeId);
    }

    current.setCanvasNodes((nodes) => nodes.filter((node) => !selectedNodeIds.includes(node.id)));
    current.setFlowNodes((nodes) => nodes.filter((node) => !selectedNodeIds.includes(node.id)));
    current.setFlowEdges((edges) =>
      edges.filter((edge) => !selectedEdgeIds.has(edge.id) && !selectedNodeIds.includes(edge.source) && !selectedNodeIds.includes(edge.target)),
    );
    if (current.selectedEdgeId && selectedEdgeIds.has(current.selectedEdgeId)) current.setSelectedEdgeId(null);
    const nextNode = current.flowNodes.find((node) => !selectedNodeIds.includes(node.id) && isUserVisibleWorkflowNode({ id: node.id, node_type: node.data.kind }));
    current.setSelectedNodeId(nextNode?.id ?? "");
    current.setStatus("Selection deleted");
  }

  async function deleteNodeFromBackend(nodeId: string) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) return;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 region nodes cannot be deleted through the V1 graph endpoint.");
      return;
    }
    try {
      const result = await api.deleteWorkflowNode(current.workflow.workflow_id, nodeId);
      current.noteAffected(result.affected_downstream_nodes);
    } catch (error) {
      current.setStatus(error instanceof Error ? `Backend node delete failed: ${error.message}` : "Backend node delete failed");
    }
  }

  async function deleteEdgeFromBackend(edgeId: string) {
    const current = argsRef.current;
    if (!current.workflow?.workflow_id) return;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 display edges are backend-defined and cannot be deleted through the V1 graph endpoint.");
      return;
    }
    try {
      const result = await api.deleteWorkflowEdge(current.workflow.workflow_id, edgeId);
      current.noteAffected(result.affected_downstream_nodes);
    } catch (error) {
      current.setStatus(error instanceof Error ? `Backend edge delete failed: ${error.message}` : "Backend edge delete failed");
    }
  }

  async function duplicateSelectedNode() {
    const current = argsRef.current;
    if (!current.selectedPlanNode) return;
    if (current.currentWorkflowIsV2()) {
      current.setStatus("V2 workflows use backend-defined nodes. Use free generation for ad hoc outputs.");
      return;
    }
    current.captureCanvasHistory();
    const id = `${current.selectedPlanNode.id}-copy-${Date.now().toString(36)}`;
    const sourceFlowNode = current.flowNodes.find((node) => node.id === current.selectedPlanNode?.id);
    const node: WorkflowNode = {
      ...current.selectedPlanNode,
      id,
      node_type: getWorkflowNodeType(current.selectedPlanNode),
      title: `${current.selectedPlanNode.title} Copy`,
      status: "pending",
      version: 1,
      locked: false,
      stale: false,
    };
    const flowNode = mapWorkflowNodes([node], current.nodeRunByType, [])[0];
    flowNode.position = {
      x: (sourceFlowNode?.position.x ?? 520) + 40,
      y: (sourceFlowNode?.position.y ?? 90) + 40,
    };
    node.position = flowNode.position;
    if (current.workflow?.workflow_id) {
      try {
        const result = await api.createWorkflowNode(current.workflow.workflow_id, toNodeMutationPayload(node, flowNode));
        const nextNode = { ...node, ...result.node, id: result.node.id ?? id };
        current.setCanvasNodes((nodes) => [...nodes, nextNode]);
        current.setFlowNodes((nodes) => [...nodes.map((item) => ({ ...item, selected: false })), { ...mapWorkflowNodes([nextNode], current.nodeRunByType, [])[0], position: flowNode.position, selected: true }]);
        current.setSelectedNodeId(nextNode.id);
        current.noteAffected(result.affected_downstream_nodes);
        return;
      } catch (error) {
        current.setStatus(error instanceof Error ? `Duplicated locally, backend create failed: ${error.message}` : "Node duplicated locally");
      }
    }
    current.setCanvasNodes((nodes) => [...nodes, node]);
    current.setFlowNodes((nodes) => [...nodes.map((item) => ({ ...item, selected: false })), { ...flowNode, selected: true }]);
    current.setSelectedNodeId(id);
    current.setStatus("Node duplicated");
  }

  function autoLayout() {
    const current = argsRef.current;
    current.captureCanvasHistory();
    const ordered = layoutNodes(current.flowNodes, current.flowEdges);
    current.setFlowNodes(ordered);
    current.setCanvasNodes((nodes) => syncWorkflowNodePositions(nodes, ordered));
    current.setStatus("Canvas arranged by DAG");
    window.setTimeout(() => current.reactFlow?.fitView({ padding: DEFAULT_LAYOUT_VIEWPORT_PADDING }), 0);
  }

  function persistNodePosition(node: CanvasNode) {
    const current = argsRef.current;
    current.captureCanvasHistory();
    const nextCanvasNodes = current.canvasNodes.map((item) => (item.id === node.id ? { ...item, position: node.position } : item));
    const nextFlowNodes = current.flowNodes.map((item) => (item.id === node.id ? { ...item, position: node.position } : item));
    current.setCanvasNodes(nextCanvasNodes);
    current.setFlowNodes(nextFlowNodes);
    current.persistNodePositionSnapshot(nextCanvasNodes, { flowNodes: nextFlowNodes });
    current.setStatus("Position save queued");
  }

  async function handleConnect(connection: Connection) {
    const current = argsRef.current;
    const validation = validateConnection(connection, current.flowNodes, current.flowEdges);
    if (!validation.ok) {
      current.setStatus(validation.message);
      return;
    }
    if (current.workflow?.workflow_id && current.currentWorkflowIsV2()) {
      current.setStatus("V2 display edges are backend-defined and cannot be changed through the V1 graph endpoint.");
      return;
    }
    current.captureCanvasHistory();
    const edge: CanvasEdge = {
      ...connection,
      id: `${connection.source}-${connection.target}-${Date.now().toString(36)}`,
      type: "default",
      markerEnd: { type: MarkerType.ArrowClosed, color: portColor(getConnectionDataType(connection, current.flowNodes)) },
      style: edgeStyle(getConnectionDataType(connection, current.flowNodes)),
      data: {
        label: getConnectionLabel(connection, current.flowNodes),
        dataType: getConnectionDataType(connection, current.flowNodes),
      },
    };
    current.setFlowEdges((edges) => addEdge(edge, edges));
    if (current.workflow?.workflow_id) {
      try {
        const result = await api.createWorkflowEdge(current.workflow.workflow_id, toEdgeMutationPayload(edge));
        current.setFlowEdges((edges) => edges.map((item) => (item.id === edge.id ? mergeBackendEdge(edge, result.edge) : item)));
        current.noteAffected(result.affected_downstream_nodes);
      } catch (error) {
        current.setStatus(error instanceof Error ? `Connection added locally, backend create failed: ${error.message}` : "Connection added locally");
        return;
      }
    }
    current.setStatus("Connection added");
  }

  async function handleReconnect(oldEdge: CanvasEdge, newConnection: Connection) {
    const current = argsRef.current;
    const validation = validateConnection(
      newConnection,
      current.flowNodes,
      current.flowEdges.filter((edge) => edge.id !== oldEdge.id),
    );
    if (!validation.ok) {
      current.setStatus(validation.message);
      return;
    }
    if (current.workflow?.workflow_id && current.currentWorkflowIsV2()) {
      current.setStatus("V2 display edges are backend-defined and cannot be changed through the V1 graph endpoint.");
      return;
    }
    current.captureCanvasHistory();
    let updatedEdge: CanvasEdge | null = null;
    current.setFlowEdges((edges) =>
      reconnectEdge(oldEdge, newConnection, edges).map((edge) => {
        if (edge.id !== oldEdge.id) return edge;
        updatedEdge = {
          ...edge,
          type: "default",
          markerEnd: { type: MarkerType.ArrowClosed, color: portColor(getConnectionDataType(newConnection, current.flowNodes)) },
          style: edgeStyle(getConnectionDataType(newConnection, current.flowNodes)),
          label: undefined,
          data: {
            ...oldEdge.data,
            label: getConnectionLabel(newConnection, current.flowNodes),
            dataType: getConnectionDataType(newConnection, current.flowNodes),
          },
        };
        return updatedEdge;
      }),
    );
    if (current.workflow?.workflow_id) {
      try {
        const payload = toEdgeMutationPayload(updatedEdge ?? { ...oldEdge, ...newConnection });
        const result = await api.updateWorkflowEdge(current.workflow.workflow_id, oldEdge.id, payload);
        current.noteAffected(result.affected_downstream_nodes);
      } catch (error) {
        current.setStatus(error instanceof Error ? `Connection updated locally, backend patch failed: ${error.message}` : "Connection updated locally");
        return;
      }
    }
    current.setStatus("Connection updated");
  }

  function handleReconnectEnd(
    _event: MouseEvent | TouchEvent,
    edge: CanvasEdge,
    _handleType: unknown,
    connectionState: { isValid: boolean | null },
  ) {
    const current = argsRef.current;
    if (connectionState.isValid) return;
    current.captureCanvasHistory();
    current.setFlowEdges((edges) => edges.filter((item) => item.id !== edge.id));
    if (current.workflow?.workflow_id) void deleteEdgeFromBackend(edge.id);
    current.setStatus("Connection removed");
  }

	  return {
	    actions: {
	      saveCanvas,
	      createNewProjectFromCanvas,
	      flushNodePatch,
      scheduleNodePatch,
      updateSelectedNode,
      updateSelectedPrompt,
      applySystemSuggestion,
      applyOptimizedPrompt,
      regenerateOptimizedPrompt,
      updateSelectedConfig,
      updateSelectedConfigField,
      uploadAssetForSelectedNode,
      removeSelectedInputAsset,
      addWorkflowVariable,
      updateWorkflowVariable,
      deleteWorkflowVariable,
      toggleSelectedLock,
      markSelectedStale,
      deleteSelection,
      deleteNodeFromBackend,
      deleteEdgeFromBackend,
      duplicateSelectedNode,
      autoLayout,
      persistNodePosition,
      handleConnect,
      handleReconnect,
      handleReconnectEnd,
    },
  };
}
