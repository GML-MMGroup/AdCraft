import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { api } from "./api/client";
import { v2Api } from "./api/v2Client";
import { AppContext, type AppContextValue } from "./AppContextValue";
import { assetLibraryUploadOptionsForKind, dispatchAssetLibraryUploadEvent, isSupportedUploadFile, uploadOptionsForNode } from "./api/workflowNormalizers";
import { clearNewProjectStorage, createNewProjectState, loadActiveProjectId, loadDemoProjectFavorites, saveActiveProjectId, setDemoProjectFavorite, WORKSPACE_MESSAGES_KEY, WORKSPACE_WORKFLOW_KEY, type ProjectSessionState, type SavedWorkflowProject } from "./projects/newProject";
import {
  deleteHybridRecordSync,
  HYBRID_STORAGE_ERROR_EVENT,
  hybridStoragePointer,
  type HybridStorageErrorDetail,
  isHybridStoragePointer,
  loadHybridRecord,
  loadHybridRecordSync,
  safeRemoveItem,
  safeWriteJson,
  saveHybridRecordSync,
} from "./storage/hybridStorage";
import { shouldApplyWorkflowScopedResult } from "./workflow/sessionGuards";
import { isWorkflowV2Graph } from "./workflowSchema";
import { workflowV2ToWorkflowGraph } from "./workflow-v2/pageAdapter";
import type { ProjectV2Summary } from "./types-v2";
import type {
  AssetLibraryEntitySummary,
  AssetLibraryUploadKind,
  AssetUploadOptions,
  FrontDeskMessage,
  NodeCatalogItem,
  NodeRunResult,
  UploadedAsset,
  WorkflowGraph,
} from "./types";

type WorkspaceRestoreRequest = {
  generation: number;
  activeProjectId: string | null;
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [apiMessage, setApiMessage] = useState("Checking FastAPI...");
  const [assets, setAssets] = useState<UploadedAsset[]>([]);
  const [selectedAssets, setSelectedAssets] = useState<UploadedAsset[]>([]);
  const [promptLibraryEntities, setPromptLibraryEntities] = useState<AssetLibraryEntitySummary[]>([]);
  const [messages, setMessages] = useState<FrontDeskMessage[]>(() => loadStoredMessages());
  const [workflow, setWorkflow] = useState<WorkflowGraph | null>(() => loadStoredWorkflow());
  const [nodeCatalog, setNodeCatalog] = useState<NodeCatalogItem[]>([]);
  const [nodeRuns, setNodeRuns] = useState<NodeRunResult[]>([]);
  const [savedProjects, setSavedProjects] = useState<ProjectV2Summary[]>([]);
  const [trashedProjects, setTrashedProjects] = useState<ProjectV2Summary[]>([]);
  const [demoProjectFavorites, setDemoProjectFavorites] = useState<Record<string, boolean>>(() => loadDemoProjectFavorites(window.localStorage));
  const [activeProjectId, setActiveProjectId] = useState<string | null>(() => loadActiveProjectId(window.localStorage));
  const [workspaceHydrated, setWorkspaceHydrated] = useState(false);
  const [workspaceRestoreError, setWorkspaceRestoreError] = useState<string | null>(null);
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const activeWorkflowIdRef = useRef<string | null>(workflow?.workflow_id ?? null);
  const workspaceSessionGenerationRef = useRef(0);

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

  const saveProject = useCallback((state: ProjectSessionState = currentProjectState()) => {
    if (!state.workflow?.project_id) saveStoredWorkflow(state.workflow);
    return null;
  }, [currentProjectState]);

  const refreshProjects = useCallback(async () => {
    const [active, trashed] = await Promise.all([
      v2Api.listProjects("active"),
      v2Api.listProjects("trashed"),
    ]);
    setSavedProjects(active.items);
    setTrashedProjects(trashed.items);
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
    invalidateWorkspaceRestoreRequests();
    const nextState = createNewProjectState();
    activeWorkflowIdRef.current = null;
    setWorkspaceRestoreError(null);
    clearNewProjectStorage(window.localStorage, workflow?.workflow_id);
    saveActiveProjectId(window.localStorage, null);
    setActiveProjectId(null);
    setWorkflow(nextState.workflow);
    setMessages(nextState.messages);
    setNodeRuns(nextState.nodeRuns);
    setSelectedAssets(nextState.selectedAssets);
    setPromptLibraryEntities(nextState.promptLibraryEntities);
    setWorkspaceHydrated(true);
  }, [invalidateWorkspaceRestoreRequests, workflow?.workflow_id]);

  const openProject = useCallback(async (projectId: string) => {
    const requestGeneration = invalidateWorkspaceRestoreRequests();
    const response = await v2Api.projectWorkflow(projectId);
    if (requestGeneration !== workspaceSessionGenerationRef.current) return false;
    clearNewProjectStorage(window.localStorage, workflow?.workflow_id);
    const nextWorkflow = workflowV2ToWorkflowGraph(response.value);
    activeWorkflowIdRef.current = nextWorkflow.workflow_id;
    saveActiveProjectId(window.localStorage, projectId);
    setActiveProjectId(projectId);
    setWorkspaceRestoreError(null);
    setWorkflow(nextWorkflow);
    setNodeRuns([]);
    setWorkspaceHydrated(true);
    return true;
  }, [invalidateWorkspaceRestoreRequests, workflow?.workflow_id]);

  const moveProjectToTrash = useCallback(async (projectId: string) => {
    await v2Api.trashProject(projectId);
    if (activeProjectId === projectId) {
      saveActiveProjectId(window.localStorage, null);
      setActiveProjectId(null);
    }
    await refreshProjects();
    return true;
  }, [activeProjectId, refreshProjects]);

  const restoreTrashedProject = useCallback(async (projectId: string) => {
    await v2Api.restoreProject(projectId);
    await refreshProjects();
    return true;
  }, [refreshProjects]);

  const renameProject = useCallback(async (projectId: string, name: string) => {
    await v2Api.updateProject(projectId, { name });
    await refreshProjects();
    return true;
  }, [refreshProjects]);

  const toggleProjectFavorite = useCallback(async (project: ProjectV2Summary) => {
    await v2Api.updateProject(project.project_id, { is_favorite: !project.is_favorite });
    await refreshProjects();
    return true;
  }, [refreshProjects]);

  useEffect(() => {
    activeWorkflowIdRef.current = workflow?.workflow_id ?? null;
    if (!workflow?.project_id || workflow.project_id === activeProjectId) return;
    saveActiveProjectId(window.localStorage, workflow.project_id);
    setActiveProjectId(workflow.project_id);
    void refreshProjects();
  }, [activeProjectId, refreshProjects, workflow?.project_id, workflow?.workflow_id]);

  useEffect(() => {
    let cancelled = false;
    async function hydrateLocalDrafts() {
      const restoreRequest = beginWorkspaceRestoreRequest();
      try {
        const [activeProjects, trashProjects, storedWorkflow, storedMessages] = await Promise.all([
          v2Api.listProjects("active"),
          v2Api.listProjects("trashed"),
          loadStoredWorkflowAsync(),
          loadStoredMessagesAsync(),
        ]);
        if (cancelled || !shouldApplyWorkspaceRestoreRequest(restoreRequest)) return;
        setSavedProjects(activeProjects.items);
        setTrashedProjects(trashProjects.items);
        const storedProjectId = loadActiveProjectId(window.localStorage);
        if (storedProjectId) {
          try {
            const response = await v2Api.projectWorkflow(storedProjectId);
            if (cancelled || !shouldApplyWorkspaceRestoreRequest(restoreRequest)) return;
            const nextWorkflow = workflowV2ToWorkflowGraph(response.value);
            activeWorkflowIdRef.current = nextWorkflow.workflow_id;
            setActiveProjectId(storedProjectId);
            setWorkflow(nextWorkflow);
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
        setWorkflow((current) => {
          const next = current ?? storedWorkflow;
          activeWorkflowIdRef.current = next?.workflow_id ?? null;
          return next;
        });
        setMessages((current) => (current.length ? current : storedMessages));
        setWorkspaceHydrated(true);
      } catch {
        if (cancelled || !shouldApplyWorkspaceRestoreRequest(restoreRequest)) return;
        setWorkspaceRestoreError("Saved project could not be restored.");
        setWorkspaceHydrated(true);
      }
    }

    void hydrateLocalDrafts();
    return () => {
      cancelled = true;
    };
  }, [beginWorkspaceRestoreRequest, shouldApplyWorkspaceRestoreRequest]);

  useEffect(() => {
    function handleHybridStorageError(event: Event) {
      const detail = (event as CustomEvent<HybridStorageErrorDetail>).detail;
      setStorageWarning(detail?.message || "Local project storage failed. Recent changes may not persist after refresh.");
    }

    window.addEventListener(HYBRID_STORAGE_ERROR_EVENT, handleHybridStorageError as EventListener);
    return () => {
      window.removeEventListener(HYBRID_STORAGE_ERROR_EVENT, handleHybridStorageError as EventListener);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const health = await api.health();
        if (cancelled) return;
        setApiOnline(true);
        setApiMessage(`${health.service} · ${health.mode}`);
        await Promise.all([refreshAssets(), refreshNodeCatalog()]);
      } catch (error) {
        if (cancelled) return;
        setApiOnline(false);
        setApiMessage("FastAPI is not reachable. Demo data is shown until the backend starts.");
      }
    }

    void boot();
    return () => {
      cancelled = true;
    };
  }, [refreshAssets, refreshNodeCatalog]);

  useEffect(() => {
    if (!workspaceHydrated) return;
    saveStoredMessages(messages);
  }, [messages, workspaceHydrated]);

  useEffect(() => {
    if (!workspaceHydrated) return;
    saveStoredWorkflow(workflow);
  }, [workflow, workspaceHydrated]);

  const value = useMemo<AppContextValue>(
    () => ({
      apiOnline,
      apiMessage,
      assets,
      selectedAssets,
      promptLibraryEntities,
      messages,
      workflow,
      nodeCatalog,
      nodeRuns,
      savedProjects,
      trashedProjects,
      demoProjectFavorites,
      activeProjectId,
      workspaceHydrated,
      workspaceRestoreError,
      storageWarning,
      busy,
      setMessages,
      setPromptLibraryEntities,
      setWorkflow: setWorkflowState,
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
      apiMessage,
      apiOnline,
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
      storageWarning,
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

function loadStoredWorkflow(): WorkflowGraph | null {
  try {
    const value = window.localStorage.getItem(WORKSPACE_WORKFLOW_KEY);
    if (!value) return null;
    const parsed = JSON.parse(value);
    if (isUnsavedWorkflowDraftPointer(parsed)) {
      return loadHybridRecordSync<WorkflowGraph>("workflowDrafts", parsed.key) ?? null;
    }
    return null;
  } catch {
    return null;
  }
}

async function loadStoredWorkflowAsync(): Promise<WorkflowGraph | null> {
  try {
    const value = window.localStorage.getItem(WORKSPACE_WORKFLOW_KEY);
    const parsed = value ? JSON.parse(value) : null;
    if (isUnsavedWorkflowDraftPointer(parsed)) {
      return (await loadHybridRecord<WorkflowGraph>("workflowDrafts", parsed.key)) ?? null;
    }
  } catch {
    return null;
  }
  return null;
}

function saveStoredWorkflow(workflow: WorkflowGraph | null) {
  if (!workflow || workflow.project_id) {
    deleteHybridRecordSync("workflowDrafts", "active");
    safeRemoveItem(window.localStorage, WORKSPACE_WORKFLOW_KEY);
    return;
  }
  saveHybridRecordSync("workflowDrafts", "active", workflow);
  safeWriteJson(window.localStorage, WORKSPACE_WORKFLOW_KEY, {
    ...hybridStoragePointer("workflowDrafts", "active"),
    workflow_id: workflow.workflow_id,
    unsaved_project_draft: true,
  });
}

function isUnsavedWorkflowDraftPointer(value: unknown): value is ReturnType<typeof hybridStoragePointer> & {
  unsaved_project_draft: true;
} {
  return Boolean(
    isHybridStoragePointer(value) &&
    value.namespace === "workflowDrafts" &&
    (value as Record<string, unknown>).unsaved_project_draft === true,
  );
}

function loadStoredMessages(): FrontDeskMessage[] {
  try {
    const value = window.localStorage.getItem(WORKSPACE_MESSAGES_KEY);
    const parsed = value ? JSON.parse(value) : null;
    if (isHybridStoragePointer(parsed) && parsed.namespace === "messageThreads") {
      return loadHybridRecordSync<FrontDeskMessage[]>("messageThreads", parsed.key) ?? [];
    }
    if (!Array.isArray(parsed)) return [];
    saveStoredMessages(parsed);
    return Array.isArray(parsed)
      ? parsed.filter((message): message is FrontDeskMessage => (
          message &&
          (message.role === "user" || message.role === "assistant") &&
          typeof message.content === "string"
        ))
      : [];
  } catch {
    return loadHybridRecordSync<FrontDeskMessage[]>("messageThreads", "active") ?? [];
  }
}

async function loadStoredMessagesAsync(): Promise<FrontDeskMessage[]> {
  try {
    const value = window.localStorage.getItem(WORKSPACE_MESSAGES_KEY);
    const parsed = value ? JSON.parse(value) : null;
    if (isHybridStoragePointer(parsed) && parsed.namespace === "messageThreads") {
      return sanitizeMessages((await loadHybridRecord<FrontDeskMessage[]>("messageThreads", parsed.key)) ?? []);
    }
  } catch {
    // Fall through to the standard active thread key.
  }
  return sanitizeMessages((await loadHybridRecord<FrontDeskMessage[]>("messageThreads", "active")) ?? []);
}

function saveStoredMessages(messages: FrontDeskMessage[]) {
  const recentMessages = sanitizeMessages(messages).slice(-80);
  saveHybridRecordSync("messageThreads", "active", recentMessages);
  safeWriteJson(window.localStorage, WORKSPACE_MESSAGES_KEY, hybridStoragePointer("messageThreads", "active"));
}

function sanitizeMessages(messages: FrontDeskMessage[]) {
  return Array.isArray(messages)
    ? messages.filter((message): message is FrontDeskMessage => (
        message &&
        (message.role === "user" || message.role === "assistant") &&
        typeof message.content === "string"
      ))
    : [];
}
