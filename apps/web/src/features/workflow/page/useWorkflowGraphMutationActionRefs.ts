import { useCallback, type RefObject } from "react";
import type { Connection } from "@xyflow/react";
import type { WorkflowNode, WorkflowVariable } from "../../../types.ts";
import type { CanvasEdge, CanvasNode } from "../types.ts";
import type { useWorkflowGraphMutationController } from "../graph/useWorkflowGraphMutationController.ts";

type GraphMutationControllerRef = RefObject<ReturnType<typeof useWorkflowGraphMutationController> | null>;

export function useWorkflowGraphMutationActionRefs(workflowGraphMutationsRef: GraphMutationControllerRef) {
  const saveCanvas = useCallback((options?: { quiet?: boolean; requireBackend?: boolean; nodes?: WorkflowNode[] }) => (
    workflowGraphMutationsRef.current?.actions.saveCanvas(options) ?? Promise.resolve(!options?.requireBackend)
  ), [workflowGraphMutationsRef]);

  const createNewProjectFromCanvas = useCallback(() => {
    workflowGraphMutationsRef.current?.actions.createNewProjectFromCanvas();
  }, [workflowGraphMutationsRef]);

  const flushNodePatch = useCallback((nodeId: string) => (
    workflowGraphMutationsRef.current?.actions.flushNodePatch(nodeId) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const scheduleNodePatch = useCallback((nodeId: string, baseNode: WorkflowNode, patch: Partial<WorkflowNode>, sourceFlowNode?: CanvasNode) => {
    workflowGraphMutationsRef.current?.actions.scheduleNodePatch(nodeId, baseNode, patch, sourceFlowNode);
  }, [workflowGraphMutationsRef]);

  const updateSelectedNode = useCallback((patch: Partial<WorkflowNode>, options?: { debounce?: boolean }) => (
    workflowGraphMutationsRef.current?.actions.updateSelectedNode(patch, options) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const updateSelectedPrompt = useCallback((prompt: string) => {
    workflowGraphMutationsRef.current?.actions.updateSelectedPrompt(prompt);
  }, [workflowGraphMutationsRef]);

  const applySystemSuggestion = useCallback(() => {
    workflowGraphMutationsRef.current?.actions.applySystemSuggestion();
  }, [workflowGraphMutationsRef]);

  const applyOptimizedPrompt = useCallback(() => {
    workflowGraphMutationsRef.current?.actions.applyOptimizedPrompt();
  }, [workflowGraphMutationsRef]);

  const regenerateOptimizedPrompt = useCallback(() => (
    workflowGraphMutationsRef.current?.actions.regenerateOptimizedPrompt() ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const updateSelectedConfig = useCallback((value: string) => {
    workflowGraphMutationsRef.current?.actions.updateSelectedConfig(value);
  }, [workflowGraphMutationsRef]);

  const updateSelectedConfigField = useCallback((key: string, value: unknown) => {
    workflowGraphMutationsRef.current?.actions.updateSelectedConfigField(key, value);
  }, [workflowGraphMutationsRef]);

  const uploadAssetForSelectedNode = useCallback((files: FileList | null) => (
    workflowGraphMutationsRef.current?.actions.uploadAssetForSelectedNode(files) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const removeSelectedInputAsset = useCallback((assetId: string) => {
    workflowGraphMutationsRef.current?.actions.removeSelectedInputAsset(assetId);
  }, [workflowGraphMutationsRef]);

  const addWorkflowVariable = useCallback((type: WorkflowVariable["variable_type"] = "string") => {
    workflowGraphMutationsRef.current?.actions.addWorkflowVariable(type);
  }, [workflowGraphMutationsRef]);

  const updateWorkflowVariable = useCallback((variableId: string, patch: Partial<WorkflowVariable>) => {
    workflowGraphMutationsRef.current?.actions.updateWorkflowVariable(variableId, patch);
  }, [workflowGraphMutationsRef]);

  const deleteWorkflowVariable = useCallback((variableId: string) => {
    workflowGraphMutationsRef.current?.actions.deleteWorkflowVariable(variableId);
  }, [workflowGraphMutationsRef]);

  const toggleSelectedLock = useCallback(() => (
    workflowGraphMutationsRef.current?.actions.toggleSelectedLock() ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const markSelectedStale = useCallback((includeDownstream: boolean) => (
    workflowGraphMutationsRef.current?.actions.markSelectedStale(includeDownstream) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const deleteSelection = useCallback(() => (
    workflowGraphMutationsRef.current?.actions.deleteSelection() ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const deleteNodeFromBackend = useCallback((nodeId: string) => (
    workflowGraphMutationsRef.current?.actions.deleteNodeFromBackend(nodeId) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const deleteEdgeFromBackend = useCallback((edgeId: string) => (
    workflowGraphMutationsRef.current?.actions.deleteEdgeFromBackend(edgeId) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const duplicateSelectedNode = useCallback(() => (
    workflowGraphMutationsRef.current?.actions.duplicateSelectedNode() ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const autoLayout = useCallback(() => {
    workflowGraphMutationsRef.current?.actions.autoLayout();
  }, [workflowGraphMutationsRef]);

  const persistNodePosition = useCallback((node: CanvasNode) => {
    workflowGraphMutationsRef.current?.actions.persistNodePosition(node);
  }, [workflowGraphMutationsRef]);

  const handleConnect = useCallback((connection: Connection) => (
    workflowGraphMutationsRef.current?.actions.handleConnect(connection) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const handleReconnect = useCallback((oldEdge: CanvasEdge, newConnection: Connection) => (
    workflowGraphMutationsRef.current?.actions.handleReconnect(oldEdge, newConnection) ?? Promise.resolve()
  ), [workflowGraphMutationsRef]);

  const handleReconnectEnd = useCallback((
    event: MouseEvent | TouchEvent,
    edge: CanvasEdge,
    handleType: unknown,
    connectionState: { isValid: boolean | null },
  ) => {
    workflowGraphMutationsRef.current?.actions.handleReconnectEnd(event, edge, handleType, connectionState);
  }, [workflowGraphMutationsRef]);

  return {
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
  };
}
