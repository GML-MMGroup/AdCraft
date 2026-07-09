import { useCallback, useMemo, useRef } from "react";
import { deleteCanvasSnapshot, loadCanvasSnapshot, type ProjectSessionState, type SavedWorkflowProject } from "../../../projects/newProject.ts";
import type {
  AssetLibraryEntitySummary,
  FrontDeskMessage,
  NodeRunResult,
  UploadedAsset,
  WorkflowGraph,
} from "../../../types.ts";
import { isV2WorkflowId, isWorkflowV2Graph } from "../../../workflow-v2/pageAdapter.ts";

export type WorkflowSessionView = {
  workflowId: string | null;
  projectId: string | null;
  isV2: boolean;
  workspaceHydrated: boolean;
  isRestoringWorkspace: boolean;
};

export type WorkflowSessionModuleArgs = {
  workflow: WorkflowGraph | null;
  messages: FrontDeskMessage[];
  nodeRuns: NodeRunResult[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
  activeProjectId: string | null;
  workspaceHydrated: boolean;
  saveProject: (state?: ProjectSessionState) => SavedWorkflowProject | null;
  startNewProject: () => void;
};

export type WorkflowSessionModule = {
  sessionView: WorkflowSessionView;
  currentWorkflowIsV2: () => boolean;
  saveCurrentProject: () => SavedWorkflowProject | null;
  startFreshProject: () => void;
  loadSnapshot: <T = unknown>(workflowId?: string | null) => T | null;
  persistSnapshot: (workflowId: string | null | undefined, snapshot: unknown, options?: { immediate?: boolean }) => void;
  deleteSnapshot: (workflowId?: string | null) => void;
};

function workflowSchemaVersion(workflow: WorkflowGraph | null) {
  const topLevel = workflow && "workflow_schema_version" in workflow ? (workflow as { workflow_schema_version?: unknown }).workflow_schema_version : undefined;
  return topLevel ?? workflow?.metadata?.workflow_schema_version;
}

export function useWorkflowSessionModule(args: WorkflowSessionModuleArgs): WorkflowSessionModule {
  const activeProjectIdRef = useRef(args.activeProjectId);
  activeProjectIdRef.current = args.activeProjectId;

  const currentWorkflowIsV2 = useCallback(() => {
    const workflowId = args.workflow?.workflow_id ?? null;
    return isWorkflowV2Graph(args.workflow) || isV2WorkflowId(workflowId) || workflowSchemaVersion(args.workflow) === 2;
  }, [args.workflow]);

  const sessionView = useMemo<WorkflowSessionView>(() => ({
    workflowId: args.workflow?.workflow_id ?? null,
    projectId: args.activeProjectId,
    isV2: currentWorkflowIsV2(),
    workspaceHydrated: args.workspaceHydrated,
    isRestoringWorkspace: Boolean(args.activeProjectId && !args.workspaceHydrated && !args.workflow),
  }), [args.activeProjectId, args.workflow, args.workspaceHydrated, currentWorkflowIsV2]);

  const saveCurrentProject = useCallback(() => args.saveProject({
    workflow: args.workflow,
    messages: args.messages,
    nodeRuns: args.nodeRuns,
    selectedAssets: args.selectedAssets,
    promptLibraryEntities: args.promptLibraryEntities,
  }), [args]);

  const startFreshProject = useCallback(() => {
    if (args.workflow || args.messages.length || args.nodeRuns.length || args.selectedAssets.length || args.promptLibraryEntities.length) {
      args.saveProject({
        workflow: args.workflow,
        messages: args.messages,
        nodeRuns: args.nodeRuns,
        selectedAssets: args.selectedAssets,
        promptLibraryEntities: args.promptLibraryEntities,
      });
    }
    args.startNewProject();
  }, [args]);

  const loadSnapshot = useCallback(<T = unknown>(workflowId = args.workflow?.workflow_id ?? null) => {
    if (!workflowId) return null;
    return (loadCanvasSnapshot(window.localStorage, workflowId) as T | undefined) ?? null;
  }, [args.workflow?.workflow_id]);

  const persistSnapshot = useCallback((workflowId: string | null | undefined, snapshot: unknown, options: { immediate?: boolean } = {}) => {
    if (!workflowId) return;
    const write = () => {
      window.localStorage.setItem(`workflowCanvasSnapshot:${workflowId}`, JSON.stringify(snapshot));
      saveCurrentProject();
    };
    if (options.immediate) {
      write();
      return;
    }
    if (window.requestIdleCallback) {
      window.requestIdleCallback(write);
      return;
    }
    window.setTimeout(write, 0);
  }, [saveCurrentProject]);

  const deleteSnapshot = useCallback((workflowId = args.workflow?.workflow_id ?? null) => {
    if (!workflowId) return;
    deleteCanvasSnapshot(workflowId, window.localStorage);
  }, [args.workflow?.workflow_id]);

  return {
    sessionView,
    currentWorkflowIsV2,
    saveCurrentProject,
    startFreshProject,
    loadSnapshot,
    persistSnapshot,
    deleteSnapshot,
  };
}
