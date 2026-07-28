import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { api } from "../api/client";
import { createOperationKey } from "../api/operationKey.ts";
import {
  v2AuthoringConflictStore,
} from "../api/v2AuthoringConflictStore";
import {
  V2_AUTHORING_CONFLICT_RESOLVED_EVENT,
  V2_AUTHORING_DRAFT_DISCARDED_EVENT,
  type V2AuthoringConflictResolution,
  type V2AuthoringConflictTarget,
} from "../api/v2AuthoringConflictEvents.ts";
import { AppContext, type AppContextValue } from "../AppContextValue";
import { assetLibraryUploadOptionsForKind, dispatchAssetLibraryUploadEvent, isSupportedUploadFile, uploadOptionsForNode } from "../api/workflowNormalizers";
import { clearNewProjectStorage, loadActiveProjectId, loadDemoProjectFavorites, saveActiveProjectId, setDemoProjectFavorite, type ProjectSessionState, type SavedWorkflowProject } from "../projects/newProject";
import { shouldApplyWorkflowScopedResult } from "../workflow/sessionGuards";
import { isWorkflowV2Graph } from "../workflowSchema";
import type { AgentCanvasWorkflowV2, ProjectV2Summary } from "../types-v2";
import { loadAllBackendProjectPages, projectTrashClearsActiveWorkflow } from "../projects/v2ProjectAuthority";
import type {
  AssetLibraryEntitySummary,
  AssetLibraryUploadKind,
  AssetUploadOptions,
  FrontDeskMessage,
  NodeCatalogItem,
  NodeRunResult,
  UploadedAsset,
  WorkflowGraph,
} from "../types";

type WorkspaceRestoreRequest = {
  generation: number;
  activeProjectId: string | null;
};

export function WorkspaceProvider({ children, startWithNewProject = false }: { children: ReactNode; startWithNewProject?: boolean }) {
  const [assets, setAssets] = useState<UploadedAsset[]>([]);
  const [selectedAssets, setSelectedAssets] = useState<UploadedAsset[]>([]);
  const [promptLibraryEntities, setPromptLibraryEntities] = useState<AssetLibraryEntitySummary[]>([]);
  const [messages, setMessages] = useState<FrontDeskMessage[]>([]);
  const [workflow, setWorkflow] = useState<WorkflowGraph | null>(null);
  const [agentCanvasWorkflow, setAgentCanvasWorkflow] = useState<AgentCanvasWorkflowV2 | null>(null);
  const [nodeCatalog, setNodeCatalog] = useState<NodeCatalogItem[]>([]);
  const [nodeRuns, setNodeRuns] = useState<NodeRunResult[]>([]);
  const [savedProjects, setSavedProjects] = useState<ProjectV2Summary[]>([]);
  const [trashedProjects, setTrashedProjects] = useState<ProjectV2Summary[]>([]);
  const [demoProjectFavorites, setDemoProjectFavorites] = useState<Record<string, boolean>>(() => loadDemoProjectFavorites(window.localStorage));
  const [activeProjectId, setActiveProjectId] = useState<string | null>(() => loadActiveProjectId(window.localStorage));
  const [workspaceHydrated, setWorkspaceHydrated] = useState(false);
  const [workspaceRestoreError, setWorkspaceRestoreError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const activeWorkflowIdRef = useRef<string | null>(null);
  const workspaceSessionGenerationRef = useRef(0);
  const newProjectRequestRef = useRef<Promise<boolean> | null>(null);
  const routeProjectCreationStartedRef = useRef(false);

  const setWorkflowState = useCallback<Dispatch<SetStateAction<WorkflowGraph | null>>>((next) => {
    if (typeof next === "function") {
      setWorkflow((current) => {
        const resolved = next(current);
        activeWorkflowIdRef.current = resolved?.workflow_id ?? null;
        return resolved;
      });
      return;
    }
    activeWorkflowIdRef.current = next?.workflow_id ?? null;
    setWorkflow(next);
  }, []);

  const refreshAssets = useCallback(async () => {
    try {
      const response = await api.listAssets();
      setAssets(response.assets ?? []);
    } catch {
      setAssets([]);
    }
  }, []);

  const refreshNodeCatalog = useCallback(async () => {
    try {
      const response = await api.nodeCatalog();
      setNodeCatalog(response.nodes ?? []);
    } catch {
      setNodeCatalog([]);
    }
  }, []);

  const refreshWorkflowNodes = useCallback(async (workflowId = workflow?.workflow_id) => {
    const requestWorkflowId = workflowId;
    if (!requestWorkflowId) return;
    if (isWorkflowV2Graph(workflow) && requestWorkflowId === workflow.workflow_id) {
      setNodeRuns([]);
      return;
    }
    try {
      const response = await api.workflowNodes(requestWorkflowId);
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, activeWorkflowIdRef.current)) return;
      setNodeRuns(response.nodes ?? []);
    } catch {
      if (!shouldApplyWorkflowScopedResult(requestWorkflowId, activeWorkflowIdRef.current)) return;
      setNodeRuns([]);
    }
  }, [workflow]);

  const uploadAsset = useCallback(async (file: File, options: AssetUploadOptions = {}) => {
    if (!isSupportedUploadFile(file)) {
      throw new Error("Backend uploads currently support image, video, audio, or document files.");
    }

    setBusy(true);
    try {
      const role = options.asset_role ?? "reference";
      const nodeType = role === "character" ? "character-generation" : role === "scene" ? "scene-generation" : "script";
      const uploadKind = defaultAssetLibraryUploadKind(role, file);
      const asset = await api.uploadAsset(file, {
        ...uploadOptionsForNode(nodeType, role, file.type),
        ...assetLibraryUploadOptionsForKind(uploadKind),
        ...options,
      });
      setAssets((current) => [asset, ...current.filter((item) => item.asset_id !== asset.asset_id)]);
      setSelectedAssets((current) => [asset, ...current]);
      await refreshAssets();
      dispatchAssetLibraryUploadEvent(asset);
      return asset;
    } finally {
      setBusy(false);
    }
  }, [refreshAssets]);

  const toggleAssetSelection = useCallback((asset: UploadedAsset) => {
    setSelectedAssets((current) => {
      const exists = current.some((item) => item.asset_id === asset.asset_id);
      return exists ? current.filter((item) => item.asset_id !== asset.asset_id) : [...current, asset];
    });
  }, []);

  const currentProjectState = useCallback(() => {
    return { workflow, messages, nodeRuns, selectedAssets, promptLibraryEntities };
  }, [messages, nodeRuns, promptLibraryEntities, selectedAssets, workflow]);

  const saveProject = useCallback((_state: ProjectSessionState = currentProjectState()) => {
    return null;
  }, [currentProjectState]);

  const refreshProjects = useCallback(async () => {
    const { v2Api } = await import("../api/v2Client");
    const [active, trashed] = await Promise.all([
      loadAllBackendProjectPages((cursor) => v2Api.listProjects("active", 100, cursor)),
      loadAllBackendProjectPages((cursor) => v2Api.listProjects("trashed", 100, cursor)),
    ]);
    setSavedProjects(active);
    setTrashedProjects(trashed);
  }, []);

  const beginWorkspaceRestoreRequest = useCallback((): WorkspaceRestoreRequest => {
    return {
      generation: workspaceSessionGenerationRef.current,
      activeProjectId: loadActiveProjectId(window.localStorage),
    };
  }, []);

  const invalidateWorkspaceRestoreRequests = useCallback(() => {
    workspaceSessionGenerationRef.current += 1;
    return workspaceSessionGenerationRef.current;
  }, []);

  const shouldApplyWorkspaceRestoreRequest = useCallback((request: WorkspaceRestoreRequest) => {
    return (
      request.generation === workspaceSessionGenerationRef.current &&
      request.activeProjectId === loadActiveProjectId(window.localStorage)
    );
  }, []);

  const startNewProject = useCallback(() => {
    if (newProjectRequestRef.current) return newProjectRequestRef.current;
    const request = (async () => {
      invalidateWorkspaceRestoreRequests();
      setBusy(true);
      try {
        const { v2Api } = await import("../api/v2Client");
        const created = await v2Api.createAgentCanvasProject(
          { name: "Untitled Project", description: "" },
          createOperationKey("project"),
        );
        const nextWorkflow = created.value;
        activeWorkflowIdRef.current = nextWorkflow.workflow_id;
        clearNewProjectStorage(window.localStorage, workflow?.workflow_id);
        saveActiveProjectId(window.localStorage, nextWorkflow.project_id);
        setActiveProjectId(nextWorkflow.project_id);
        setWorkflow(null);
        setAgentCanvasWorkflow(nextWorkflow);
        setMessages([]);
        setNodeRuns([]);
        setSelectedAssets([]);
        setPromptLibraryEntities([]);
        setWorkspaceRestoreError(null);
        setWorkspaceHydrated(true);
        void refreshProjects().catch(() => {
          // The backend project already exists; a list refresh must not turn creation into a failure.
        });
        return true;
      } catch (error) {
        setWorkspaceRestoreError(error instanceof Error ? error.message : "Project creation failed.");
        setWorkspaceHydrated(true);
        return false;
      } finally {
        setBusy(false);
      }
    })();
    newProjectRequestRef.current = request;
    void request.finally(() => {
      if (newProjectRequestRef.current === request) newProjectRequestRef.current = null;
    });
    return request;
  }, [invalidateWorkspaceRestoreRequests, refreshProjects, workflow?.workflow_id]);

  const openProject = useCallback(async (projectId: string) => {
    const requestGeneration = invalidateWorkspaceRestoreRequests();
    const { v2Api } = await import("../api/v2Client");
    const project = await v2Api.projectWithEtag(projectId);
    const response = await v2Api.agentCanvasWorkflowWithEtag(project.value.workflow_id);
    if (requestGeneration !== workspaceSessionGenerationRef.current) return false;
    clearNewProjectStorage(window.localStorage, workflow?.workflow_id);
    const nextWorkflow = response.value;
    activeWorkflowIdRef.current = nextWorkflow.workflow_id;
    saveActiveProjectId(window.localStorage, projectId);
    setActiveProjectId(projectId);
    setWorkspaceRestoreError(null);
    setWorkflow(null);
    setAgentCanvasWorkflow(nextWorkflow);
    setMessages([]);
    setNodeRuns([]);
    setWorkspaceHydrated(true);
    return true;
  }, [invalidateWorkspaceRestoreRequests, workflow?.workflow_id]);

  const moveProjectToTrash = useCallback(async (projectId: string) => {
    const { v2Api } = await import("../api/v2Client");
    await v2Api.trashProject(projectId);
    if (projectTrashClearsActiveWorkflow(projectId, activeProjectId)) {
      activeWorkflowIdRef.current = null;
      setWorkflowState(null);
      setAgentCanvasWorkflow(null);
      saveActiveProjectId(window.localStorage, null);
      setActiveProjectId(null);
    }
    await refreshProjects();
    return true;
  }, [activeProjectId, refreshProjects, setWorkflowState]);

  const restoreTrashedProject = useCallback(async (projectId: string) => {
    const { v2Api } = await import("../api/v2Client");
    await v2Api.restoreProject(projectId);
    await refreshProjects();
    return true;
  }, [refreshProjects]);

  const renameProject = useCallback(async (projectId: string, name: string) => {
    const { v2Api } = await import("../api/v2Client");
    const { value: updatedProject } = await v2Api.updateProject(projectId, { name });
    setSavedProjects((current) => current.map((project) => (
      project.project_id === updatedProject.project_id ? updatedProject : project
    )));
    return true;
  }, []);

  const toggleProjectFavorite = useCallback(async (project: ProjectV2Summary) => {
    const { v2Api } = await import("../api/v2Client");
    await v2Api.updateProject(project.project_id, { is_favorite: !project.is_favorite });
    await refreshProjects();
    return true;
  }, [refreshProjects]);

  const refreshAuthoringConflictTarget = useCallback(async (target: V2AuthoringConflictTarget) => {
    if (target.resource === "project") {
      await refreshProjects();
      return;
    }
    if (target.id !== activeWorkflowIdRef.current) return;
    const { v2Api } = await import("../api/v2Client");
    const latest = await v2Api.agentCanvasWorkflowWithEtag(target.id);
    if (target.id !== activeWorkflowIdRef.current) return;
    setAgentCanvasWorkflow(latest.value);
  }, [refreshProjects]);

  useEffect(() => {
    activeWorkflowIdRef.current = agentCanvasWorkflow?.workflow_id ?? null;
    if (!agentCanvasWorkflow?.project_id || agentCanvasWorkflow.project_id === activeProjectId) return;
    saveActiveProjectId(window.localStorage, agentCanvasWorkflow.project_id);
    setActiveProjectId(agentCanvasWorkflow.project_id);
    void refreshProjects();
  }, [activeProjectId, agentCanvasWorkflow?.project_id, agentCanvasWorkflow?.workflow_id, refreshProjects]);

  useEffect(() => {
    if (startWithNewProject) {
      if (routeProjectCreationStartedRef.current) return undefined;
      routeProjectCreationStartedRef.current = true;
      void startNewProject();
      return undefined;
    }
    routeProjectCreationStartedRef.current = false;
    let cancelled = false;
    async function hydrateBackendWorkspace() {
      const restoreRequest = beginWorkspaceRestoreRequest();
      try {
        const { v2Api } = await import("../api/v2Client");
        const [activeProjects, trashProjects] = await Promise.all([
          loadAllBackendProjectPages((cursor) => v2Api.listProjects("active", 100, cursor)),
          loadAllBackendProjectPages((cursor) => v2Api.listProjects("trashed", 100, cursor)),
        ]);
        if (cancelled || !shouldApplyWorkspaceRestoreRequest(restoreRequest)) return;
        setSavedProjects(activeProjects);
        setTrashedProjects(trashProjects);
        const storedProjectId = loadActiveProjectId(window.localStorage);
        if (storedProjectId) {
          try {
            const project = await v2Api.projectWithEtag(storedProjectId);
            const response = await v2Api.agentCanvasWorkflowWithEtag(project.value.workflow_id);
            if (cancelled || !shouldApplyWorkspaceRestoreRequest(restoreRequest)) return;
            const nextWorkflow = response.value;
            activeWorkflowIdRef.current = nextWorkflow.workflow_id;
            setActiveProjectId(storedProjectId);
            setWorkflow(null);
            setAgentCanvasWorkflow(nextWorkflow);
            setMessages([]);
            setWorkspaceRestoreError(null);
            setWorkspaceHydrated(true);
            return;
          } catch {
            // The browser identity is only a preference; backend Project state is authoritative.
          }
          saveActiveProjectId(window.localStorage, null);
          setActiveProjectId(null);
          setWorkspaceRestoreError("The backend project could not be restored.");
        } else {
          setWorkspaceRestoreError(null);
        }
        activeWorkflowIdRef.current = null;
        setWorkflow(null);
        setAgentCanvasWorkflow(null);
        setMessages([]);
        setWorkspaceHydrated(true);
      } catch {
        if (cancelled || !shouldApplyWorkspaceRestoreRequest(restoreRequest)) return;
        setWorkspaceRestoreError("Saved project could not be restored.");
        setWorkspaceHydrated(true);
      }
    }

    void hydrateBackendWorkspace();
    return () => {
      cancelled = true;
    };
  }, [
    beginWorkspaceRestoreRequest,
    shouldApplyWorkspaceRestoreRequest,
    startNewProject,
    startWithNewProject,
  ]);

  useEffect(() => {
    return v2AuthoringConflictStore.subscribe((conflict) => {
      if (!conflict) return;
      void refreshAuthoringConflictTarget(conflict.target).catch(() => {});
    });
  }, [refreshAuthoringConflictTarget]);

  useEffect(() => {
    async function handleAuthoringConflictResolved(event: Event) {
      const resolution = (event as CustomEvent<V2AuthoringConflictResolution>).detail;
      if (!resolution) return;
      try {
        await refreshAuthoringConflictTarget(resolution.target);
      } finally {
        if (resolution.action === "discard") {
          window.dispatchEvent(new CustomEvent(V2_AUTHORING_DRAFT_DISCARDED_EVENT, { detail: resolution }));
        }
      }
    }

    window.addEventListener(V2_AUTHORING_CONFLICT_RESOLVED_EVENT, handleAuthoringConflictResolved as EventListener);
    return () => window.removeEventListener(V2_AUTHORING_CONFLICT_RESOLVED_EVENT, handleAuthoringConflictResolved as EventListener);
  }, [refreshAuthoringConflictTarget]);

  const value = useMemo<AppContextValue>(
    () => ({
      assets,
      selectedAssets,
      promptLibraryEntities,
      messages,
      workflow,
      agentCanvasWorkflow,
      nodeCatalog,
      nodeRuns,
      savedProjects,
      trashedProjects,
      demoProjectFavorites,
      activeProjectId,
      workspaceHydrated,
      workspaceRestoreError,
      busy,
      setMessages,
      setPromptLibraryEntities,
      setWorkflow: setWorkflowState,
      setAgentCanvasWorkflow,
      saveProject,
      startNewProject,
      openProject,
      moveProjectToTrash,
      restoreTrashedProject,
      renameProject,
      toggleProjectFavorite,
      toggleAssetSelection,
      refreshAssets,
      refreshNodeCatalog,
      refreshWorkflowNodes,
      uploadAsset,
    }),
    [
      activeProjectId,
      agentCanvasWorkflow,
      assets,
      busy,
      demoProjectFavorites,
      messages,
      moveProjectToTrash,
      nodeCatalog,
      nodeRuns,
      openProject,
      promptLibraryEntities,
      refreshAssets,
      refreshNodeCatalog,
      refreshWorkflowNodes,
      renameProject,
      restoreTrashedProject,
      saveProject,
      savedProjects,
      selectedAssets,
      setWorkflowState,
      startNewProject,
      toggleAssetSelection,
      toggleProjectFavorite,
      trashedProjects,
      uploadAsset,
      workflow,
      workspaceHydrated,
      workspaceRestoreError,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

function defaultAssetLibraryUploadKind(role: string, file: File): AssetLibraryUploadKind {
  if (role === "character") return "character";
  if (role === "scene") return "scene";
  const mimeType = file.type.toLowerCase();
  const fileName = file.name.toLowerCase();
  if (mimeType.startsWith("audio/") || /\.(mp3|wav|m4a|aac|ogg)$/i.test(fileName)) return "bgm";
  return "";
}
