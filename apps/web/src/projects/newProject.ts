import type { AssetLibraryEntitySummary, FrontDeskMessage, NodeRunResult, UploadedAsset, WorkflowGraph } from "../types";
import {
  deleteHybridRecordSync,
  hybridStoragePointer,
  isHybridStoragePointer,
  loadHybridRecord,
  loadHybridRecordSync,
  safeRemoveItem,
  safeWriteJson,
  saveHybridRecordSync,
} from "../storage/hybridStorage.ts";
import { deleteVideoPosterCacheForProject, deleteVideoPosterCacheForWorkflow } from "../workflow/videoPosterCache.ts";

export const WORKSPACE_WORKFLOW_KEY = "ad-workflow-active-workflow";
export const WORKSPACE_MESSAGES_KEY = "ad-workflow-copilot-messages";
export const WORKSPACE_PROJECTS_KEY = "ad-workflow-saved-projects";
export const WORKSPACE_TRASH_PROJECTS_KEY = "ad-workflow-trashed-projects";
export const WORKSPACE_DEMO_PROJECT_FAVORITES_KEY = "ad-workflow-demo-project-favorites";
export const WORKSPACE_ACTIVE_PROJECT_KEY = "ad-workflow-active-project-id";
export const LOCAL_WORKFLOW_ID = "local-workflow";
export const SNAPSHOT_PREFIX = "ad-workflow-canvas:";
export const PROJECT_TRASH_LIMIT = 30;
const PROJECT_TRASH_RETENTION_DAYS = 30;
const OMITTED_INLINE_MEDIA = "[omitted-inline-media]";

export interface ProjectSessionState {
  workflow: WorkflowGraph | null;
  messages: FrontDeskMessage[];
  nodeRuns: NodeRunResult[];
  selectedAssets: UploadedAsset[];
  promptLibraryEntities: AssetLibraryEntitySummary[];
}

export interface NewProjectState extends ProjectSessionState {}

export interface SavedWorkflowProject extends ProjectSessionState {
  project_id: string;
  name: string;
  updated_at: string;
  favorite: boolean;
  img: string;
  canvas_workflow_id?: string;
  canvas_snapshot?: unknown;
}

export type SaveCurrentProjectOptions = {
  allowEmpty?: boolean;
};

export interface DemoProjectRecord {
  project_id: string;
  name: string;
  updated_at: string;
  favorite: boolean;
  img: string;
}

export interface TrashedProjectRecord {
  type: "project";
  project_id: string;
  name: string;
  meta: string;
  deleted_at: string;
  updated_at: string;
  favorite: boolean;
  img: string;
  source: "saved" | "demo";
  project?: SavedWorkflowProject;
}

type SavedProjectIndexRecord = Pick<SavedWorkflowProject, "project_id" | "name" | "updated_at" | "favorite" | "img" | "canvas_workflow_id"> & {
  storage: "indexeddb";
};

type TrashedProjectIndexRecord = Pick<TrashedProjectRecord, "type" | "project_id" | "name" | "meta" | "deleted_at" | "updated_at" | "favorite" | "img" | "source"> & {
  storage: "indexeddb";
};

export function createNewProjectState(): NewProjectState {
  return {
    workflow: null,
    messages: [],
    nodeRuns: [],
    selectedAssets: [],
    promptLibraryEntities: [],
  };
}

export function saveCurrentProject(
  storage: Pick<Storage, "getItem" | "setItem">,
  state: ProjectSessionState,
  projectId?: string | null,
  now = new Date().toISOString(),
  options: SaveCurrentProjectOptions = {},
): SavedWorkflowProject | null {
  const canvasWorkflowId = state.workflow?.workflow_id ?? LOCAL_WORKFLOW_ID;
  const canvasSnapshot = sanitizeStoredValue(loadCanvasSnapshot(storage, canvasWorkflowId));
  const hasCanvasSnapshot = canvasSnapshot !== undefined;
  if (!hasProjectContent(state) && !hasCanvasSnapshot && !options.allowEmpty) return null;
  const projects = loadSavedProjects(storage);
  const existing = projectId ? projects.find((project) => project.project_id === projectId) : null;
  if (hasCanvasSnapshot) saveCanvasSnapshot(storage, canvasWorkflowId, canvasSnapshot);
  const saved: SavedWorkflowProject = {
    project_id: existing?.project_id ?? projectId ?? createProjectId(now),
    name: projectNameFromState(state, existing?.name),
    updated_at: now,
    favorite: existing?.favorite ?? false,
    img: existing?.img ?? "card1.webp",
    workflow: sanitizeStoredValue(state.workflow) as WorkflowGraph | null,
    messages: sanitizeStoredValue(state.messages) as FrontDeskMessage[],
    nodeRuns: sanitizeStoredValue(state.nodeRuns) as NodeRunResult[],
    selectedAssets: sanitizeStoredValue(state.selectedAssets) as UploadedAsset[],
    promptLibraryEntities: sanitizeStoredValue(state.promptLibraryEntities ?? []) as AssetLibraryEntitySummary[],
    canvas_workflow_id: hasCanvasSnapshot ? canvasWorkflowId : existing?.canvas_workflow_id,
    canvas_snapshot: hasCanvasSnapshot ? canvasSnapshot : existing?.canvas_snapshot,
  };
  const nextProjects = [saved, ...projects.filter((project) => project.project_id !== saved.project_id)];
  saveProjectRecord(saved, storage);
  safeWriteJson(storage, WORKSPACE_PROJECTS_KEY, nextProjects.map(savedProjectIndex));
  return saved;
}

export function loadSavedProjects(storage: Pick<Storage, "getItem" | "setItem">): SavedWorkflowProject[] {
  try {
    const value = storage.getItem(WORKSPACE_PROJECTS_KEY);
    const parsed = value ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    const projects = parsed.flatMap((item) => savedProjectFromStoredValue(item, storage));
    return projects.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  } catch {
    return [];
  }
}

export async function loadSavedProjectsAsync(storage: Pick<Storage, "getItem">): Promise<SavedWorkflowProject[]> {
  const indexedProjects = readSavedProjectIndex(storage);
  const projects = await Promise.all(
    indexedProjects.map(async (project) => {
      const storedProject = await loadHybridRecord<SavedWorkflowProject>("projectRecords", project.project_id);
      return isSavedProject(storedProject) ? sanitizeProjectRecord(storedProject) : savedProjectShell(project);
    }),
  );
  return projects.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export function loadSavedProjectSummaries(storage: Pick<Storage, "getItem" | "setItem">): SavedWorkflowProject[] {
  try {
    const value = storage.getItem(WORKSPACE_PROJECTS_KEY);
    const parsed = value ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    const projects = parsed.flatMap((item): SavedWorkflowProject[] => {
      if (isSavedProject(item)) {
        const project = sanitizeProjectRecord(item);
        saveProjectRecord(project, storage);
        rewriteSavedProjectIndex(storage, [project]);
        return [savedProjectShell(savedProjectIndex(project))];
      }
      if (!isSavedProjectIndex(item)) return [];
      return [savedProjectShell(item)];
    });
    return projects.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  } catch {
    return [];
  }
}

export function loadSavedProjectById(storage: Pick<Storage, "getItem" | "setItem">, projectId: string): SavedWorkflowProject | null {
  const storedProject = loadHybridRecordSync<SavedWorkflowProject>("projectRecords", projectId);
  if (isSavedProject(storedProject)) return sanitizeProjectRecord(storedProject);
  return loadSavedProjects(storage).find((project) => project.project_id === projectId) ?? null;
}

export async function loadSavedProjectByIdAsync(storage: Pick<Storage, "getItem" | "setItem">, projectId: string): Promise<SavedWorkflowProject | null> {
  const storedProject = await loadHybridRecord<SavedWorkflowProject>("projectRecords", projectId);
  if (isSavedProject(storedProject)) return sanitizeProjectRecord(storedProject);
  return loadSavedProjectById(storage, projectId);
}

export function loadActiveProject(storage: Pick<Storage, "getItem" | "setItem">): SavedWorkflowProject | null {
  const activeProjectId = loadActiveProjectId(storage);
  if (!activeProjectId) return null;
  return loadSavedProjects(storage).find((project) => project.project_id === activeProjectId) ?? null;
}

export async function loadActiveProjectAsync(storage: Pick<Storage, "getItem">): Promise<SavedWorkflowProject | null> {
  const activeProjectId = loadActiveProjectId(storage);
  if (!activeProjectId) return null;
  const storedProject = await loadHybridRecord<SavedWorkflowProject>("projectRecords", activeProjectId);
  if (isSavedProject(storedProject)) return sanitizeProjectRecord(storedProject);
  return (await loadSavedProjectsAsync(storage)).find((project) => project.project_id === activeProjectId) ?? null;
}

export function loadTrashedProjects(storage: Pick<Storage, "getItem" | "setItem">): TrashedProjectRecord[] {
  try {
    const value = storage.getItem(WORKSPACE_TRASH_PROJECTS_KEY);
    const parsed = value ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    const projects = parsed.flatMap((item) => trashedProjectFromStoredValue(item, storage));
    return projects.sort((a, b) => b.deleted_at.localeCompare(a.deleted_at));
  } catch {
    return [];
  }
}

export async function loadTrashedProjectsAsync(storage: Pick<Storage, "getItem">): Promise<TrashedProjectRecord[]> {
  const indexedProjects = readTrashedProjectIndex(storage);
  const projects = await Promise.all(
    indexedProjects.map(async (project) => (await loadHybridRecord<TrashedProjectRecord>("trashRecords", project.project_id)) ?? trashedProjectShell(project)),
  );
  return projects.sort((a, b) => b.deleted_at.localeCompare(a.deleted_at));
}

export function setSavedProjectFavorite(
  storage: Pick<Storage, "getItem" | "setItem">,
  projectId: string,
  favorite: boolean,
): SavedWorkflowProject | null {
  const projects = loadSavedProjects(storage);
  const existing = projects.find((item) => item.project_id === projectId);
  if (!existing) return null;

  const updated = sanitizeProjectRecord({ ...existing, favorite });
  saveProjectRecord(updated, storage);
  safeWriteJson(storage, WORKSPACE_PROJECTS_KEY, projects.map((item) => item.project_id === projectId ? updated : item).map(savedProjectIndex));
  return updated;
}

export function loadDemoProjectFavorites(storage: Pick<Storage, "getItem">): Record<string, boolean> {
  try {
    const value = storage.getItem(WORKSPACE_DEMO_PROJECT_FAVORITES_KEY);
    const parsed = value ? JSON.parse(value) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean"));
  } catch {
    return {};
  }
}

export function setDemoProjectFavorite(
  storage: Pick<Storage, "getItem" | "setItem">,
  projectId: string,
  favorite: boolean,
): Record<string, boolean> {
  const favorites = loadDemoProjectFavorites(storage);
  const nextFavorites = { ...favorites, [projectId]: favorite };
  safeWriteJson(storage, WORKSPACE_DEMO_PROJECT_FAVORITES_KEY, nextFavorites);
  return nextFavorites;
}

export function moveSavedProjectToTrash(
  storage: Pick<Storage, "getItem" | "setItem">,
  projectId: string,
  now = new Date().toISOString(),
): TrashedProjectRecord | null {
  const projects = loadSavedProjects(storage);
  const project = projects.find((item) => item.project_id === projectId);
  if (!project) return null;

  safeWriteJson(storage, WORKSPACE_PROJECTS_KEY, projects.filter((item) => item.project_id !== projectId).map(savedProjectIndex));
  deleteHybridRecordSync("projectRecords", projectId);
  return saveTrashedProject(storage, {
    type: "project",
    project_id: project.project_id,
    name: project.name,
    meta: deletedMeta(now),
    deleted_at: now,
    updated_at: project.updated_at,
    favorite: project.favorite,
    img: project.img,
    source: "saved",
    project,
  });
}

export function moveDemoProjectToTrash(
  storage: Pick<Storage, "getItem" | "setItem">,
  project: DemoProjectRecord,
  now = new Date().toISOString(),
): TrashedProjectRecord {
  return saveTrashedProject(storage, {
    type: "project",
    project_id: project.project_id,
    name: project.name,
    meta: deletedMeta(now),
    deleted_at: now,
    updated_at: project.updated_at,
    favorite: project.favorite,
    img: project.img,
    source: "demo",
  });
}

export function permanentlyDeleteTrashedProject(
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">,
  projectId: string,
) {
  const trashedProjects = loadTrashedProjects(storage);
  const existing = trashedProjects.find((project) => project.project_id === projectId);
  if (!existing) return false;
  const wasActiveProject = loadActiveProjectId(storage) === projectId;
  const workflowId = existing.project?.workflow?.workflow_id ?? existing.project?.canvas_workflow_id;

  safeWriteJson(storage, WORKSPACE_TRASH_PROJECTS_KEY, trashedProjects.filter((project) => project.project_id !== projectId).map(trashedProjectIndex));
  deleteHybridRecordSync("trashRecords", projectId);
  deleteHybridRecordSync("projectRecords", projectId);
  deleteVideoPosterCacheForTrashedProject(existing);
  if (existing.project?.canvas_workflow_id) deleteCanvasSnapshot(existing.project.canvas_workflow_id, storage);
  if (existing.project?.workflow?.workflow_id && existing.project.workflow.workflow_id !== existing.project.canvas_workflow_id) {
    deleteCanvasSnapshot(existing.project.workflow.workflow_id, storage);
  }
  if (wasActiveProject) clearNewProjectStorage(storage, workflowId);
  return true;
}

export function projectStateFromRecord(project: SavedWorkflowProject): ProjectSessionState {
  return {
    workflow: project.workflow,
    messages: project.messages,
    nodeRuns: project.nodeRuns,
    selectedAssets: project.selectedAssets,
    promptLibraryEntities: project.promptLibraryEntities ?? [],
  };
}

export function restoreProjectStorage(storage: Pick<Storage, "setItem" | "removeItem">, project: SavedWorkflowProject | null) {
  if (!project) return;
  saveActiveProjectId(storage, project.project_id);
  if (project.workflow) {
    saveHybridRecordSync("workflowDrafts", "active", project.workflow);
    safeWriteJson(storage, WORKSPACE_WORKFLOW_KEY, {
      ...hybridStoragePointer("workflowDrafts", "active"),
      workflow_id: project.workflow.workflow_id,
    });
  } else {
    deleteHybridRecordSync("workflowDrafts", "active");
    safeRemoveItem(storage, WORKSPACE_WORKFLOW_KEY);
  }
  saveHybridRecordSync("messageThreads", "active", project.messages);
  safeWriteJson(storage, WORKSPACE_MESSAGES_KEY, hybridStoragePointer("messageThreads", "active"));
  if (project.canvas_workflow_id && project.canvas_snapshot !== undefined) {
    saveCanvasSnapshot(storage, project.canvas_workflow_id, project.canvas_snapshot);
  }
}

export function loadActiveProjectId(storage: Pick<Storage, "getItem">) {
  try {
    const value = storage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY);
    return value && value.trim() ? value : null;
  } catch {
    return null;
  }
}

export function saveActiveProjectId(storage: Pick<Storage, "setItem" | "removeItem">, projectId: string | null) {
  try {
    if (projectId) {
      storage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, projectId);
    } else {
      storage.removeItem(WORKSPACE_ACTIVE_PROJECT_KEY);
    }
  } catch {
    // Ignore localStorage quota and privacy-mode failures.
  }
}

export function clearNewProjectStorage(storage: Pick<Storage, "removeItem">, workflowId?: string | null) {
  safeRemoveItem(storage, WORKSPACE_WORKFLOW_KEY);
  safeRemoveItem(storage, WORKSPACE_MESSAGES_KEY);
  safeRemoveItem(storage, WORKSPACE_ACTIVE_PROJECT_KEY);
  deleteCanvasSnapshot(LOCAL_WORKFLOW_ID, storage);
  if (workflowId && workflowId !== LOCAL_WORKFLOW_ID) {
    deleteCanvasSnapshot(workflowId, storage);
  }
}

export function saveCanvasSnapshot(storage: Pick<Storage, "setItem">, workflowId: string, snapshot: unknown) {
  saveHybridRecordSync("canvasSnapshots", workflowId, sanitizeStoredValue(snapshot));
  safeWriteJson(storage, SNAPSHOT_PREFIX + workflowId, hybridStoragePointer("canvasSnapshots", workflowId));
}

export function loadCanvasSnapshot(storage: Pick<Storage, "getItem" | "setItem">, workflowId: string) {
  try {
    const value = storage.getItem(SNAPSHOT_PREFIX + workflowId);
    const parsed = value ? JSON.parse(value) : undefined;
    if (isHybridStoragePointer(parsed) && parsed.namespace === "canvasSnapshots") {
      return loadHybridRecordSync("canvasSnapshots", parsed.key);
    }
    if (parsed !== undefined) {
      saveCanvasSnapshot(storage, workflowId, parsed);
      return parsed;
    }
    return loadHybridRecordSync("canvasSnapshots", workflowId);
  } catch {
    return loadHybridRecordSync("canvasSnapshots", workflowId);
  }
}

export function deleteCanvasSnapshot(workflowId: string, storage?: Pick<Storage, "removeItem">) {
  deleteHybridRecordSync("canvasSnapshots", workflowId);
  if (storage) safeRemoveItem(storage, SNAPSHOT_PREFIX + workflowId);
}

function hasProjectContent(state: ProjectSessionState) {
  return Boolean(state.workflow || state.messages.length || state.nodeRuns.length || state.selectedAssets.length || (state.promptLibraryEntities?.length ?? 0));
}

function projectNameFromState(state: ProjectSessionState, fallback?: string) {
  const workflowName = state.workflow?.name;
  if (typeof workflowName === "string" && workflowName.trim()) return workflowName.trim();
  const firstUserMessage = state.messages.find((message) => message.role === "user" && message.content.trim());
  if (firstUserMessage) return truncateName(firstUserMessage.content.trim());
  return fallback || "Untitled Project";
}

function createProjectId(value: string) {
  const suffix = value.replace(/[^0-9a-z]/gi, "").slice(0, 18) || String(Date.now());
  return "local_project_" + suffix;
}

function truncateName(value: string) {
  return value.length > 48 ? value.slice(0, 45) + "..." : value;
}

function isSavedProject(value: unknown): value is SavedWorkflowProject {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<SavedWorkflowProject>;
  return (
    typeof record.project_id === "string" &&
    typeof record.name === "string" &&
    typeof record.updated_at === "string" &&
    Array.isArray(record.messages) &&
    Array.isArray(record.nodeRuns) &&
    Array.isArray(record.selectedAssets) &&
    (record.workflow === null || typeof record.workflow === "object")
  );
}

function saveProjectRecord(project: SavedWorkflowProject, storage?: Pick<Storage, "setItem">) {
  const sanitized = sanitizeProjectRecord(project);
  if (sanitized.canvas_workflow_id && sanitized.canvas_snapshot !== undefined) {
    if (storage) {
      saveCanvasSnapshot(storage, sanitized.canvas_workflow_id, sanitized.canvas_snapshot);
    } else {
      saveHybridRecordSync("canvasSnapshots", sanitized.canvas_workflow_id, sanitized.canvas_snapshot);
    }
  }
  saveHybridRecordSync("projectRecords", sanitized.project_id, sanitized);
}

function sanitizeProjectRecord(project: SavedWorkflowProject): SavedWorkflowProject {
  return {
    ...project,
    workflow: sanitizeStoredValue(project.workflow) as WorkflowGraph | null,
    messages: sanitizeStoredValue(project.messages) as FrontDeskMessage[],
    nodeRuns: sanitizeStoredValue(project.nodeRuns) as NodeRunResult[],
    selectedAssets: sanitizeStoredValue(project.selectedAssets) as UploadedAsset[],
    promptLibraryEntities: sanitizeStoredValue(project.promptLibraryEntities ?? []) as AssetLibraryEntitySummary[],
    canvas_snapshot: project.canvas_snapshot === undefined ? undefined : sanitizeStoredValue(project.canvas_snapshot),
  };
}

function sanitizeStoredValue(value: unknown, key = ""): unknown {
  if (typeof value === "string") return sanitizeStoredString(key, value);
  if (!value || typeof value !== "object") return value;
  if (isBinaryLikeValue(value)) return OMITTED_INLINE_MEDIA;
  if (Array.isArray(value)) return value.map((item) => sanitizeStoredValue(item, key));

  const next: Record<string, unknown> = {};
  for (const [entryKey, entryValue] of Object.entries(value)) {
    next[entryKey] = shouldOmitStoredField(entryKey, entryValue)
      ? OMITTED_INLINE_MEDIA
      : sanitizeStoredValue(entryValue, entryKey);
  }
  return next;
}

function sanitizeStoredString(key: string, value: string) {
  if (isInlineDataString(value)) return OMITTED_INLINE_MEDIA;
  if (isRawPayloadKey(key) && value.length > 64) return OMITTED_INLINE_MEDIA;
  return value;
}

function shouldOmitStoredField(key: string, value: unknown) {
  if (isInlineDataString(value)) return true;
  return isRawPayloadKey(key) && (typeof value === "string" || (value !== null && typeof value === "object" && isBinaryLikeValue(value)));
}

function isRawPayloadKey(key: string) {
  const lowerKey = key.toLowerCase();
  return (
    lowerKey.includes("base64") ||
    lowerKey.startsWith("raw_") ||
    lowerKey.includes("_raw_") ||
    lowerKey.includes("blob") ||
    lowerKey.includes("binary") ||
    lowerKey.includes("content_bytes") ||
    lowerKey.includes("file_content")
  );
}

function isInlineDataString(value: unknown) {
  return typeof value === "string" && /^data:(image|video|audio)\//i.test(value);
}

function isBinaryLikeValue(value: object) {
  return (
    (typeof Blob !== "undefined" && value instanceof Blob) ||
    (typeof ArrayBuffer !== "undefined" && value instanceof ArrayBuffer) ||
    ArrayBuffer.isView(value)
  );
}

function saveTrashedProject(storage: Pick<Storage, "getItem" | "setItem">, project: TrashedProjectRecord) {
  const trashedProjects = loadTrashedProjects(storage);
  const candidateProjects = [project, ...trashedProjects.filter((item) => item.project_id !== project.project_id)];
  const retainedProjects = pruneTrashedProjects(candidateProjects);
  const retainedIds = new Set(retainedProjects.map((item) => item.project_id));
  for (const item of candidateProjects) {
    if (!retainedIds.has(item.project_id)) {
      deleteHybridRecordSync("trashRecords", item.project_id);
      deleteVideoPosterCacheForTrashedProject(item);
    }
  }
  for (const item of retainedProjects) {
    saveHybridRecordSync("trashRecords", item.project_id, sanitizeStoredValue(item));
  }
  safeWriteJson(storage, WORKSPACE_TRASH_PROJECTS_KEY, retainedProjects.map(trashedProjectIndex));
  return project;
}

function deleteVideoPosterCacheForTrashedProject(project: TrashedProjectRecord) {
  deleteVideoPosterCacheForProject(project.project_id);
  const workflowId = project.project?.workflow?.workflow_id;
  const canvasWorkflowId = project.project?.canvas_workflow_id;
  if (workflowId) deleteVideoPosterCacheForWorkflow(workflowId);
  if (canvasWorkflowId && canvasWorkflowId !== workflowId) deleteVideoPosterCacheForWorkflow(canvasWorkflowId);
}

function pruneTrashedProjects(projects: TrashedProjectRecord[]) {
  const sortedProjects = [...projects].sort((a, b) => b.deleted_at.localeCompare(a.deleted_at));
  const latestTime = sortedProjects.reduce((latest, project) => {
    const time = new Date(project.deleted_at).getTime();
    return Number.isNaN(time) ? latest : Math.max(latest, time);
  }, 0);
  const cutoffTime = latestTime ? latestTime - PROJECT_TRASH_RETENTION_DAYS * 24 * 60 * 60 * 1000 : 0;
  return sortedProjects
    .filter((project) => {
      if (!cutoffTime) return true;
      const time = new Date(project.deleted_at).getTime();
      return Number.isNaN(time) || time >= cutoffTime;
    })
    .slice(0, PROJECT_TRASH_LIMIT);
}

function isTrashedProject(value: unknown): value is TrashedProjectRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<TrashedProjectRecord>;
  return (
    record.type === "project" &&
    typeof record.project_id === "string" &&
    typeof record.name === "string" &&
    typeof record.meta === "string" &&
    typeof record.deleted_at === "string" &&
    typeof record.updated_at === "string" &&
    typeof record.favorite === "boolean" &&
    typeof record.img === "string" &&
    (record.source === "saved" || record.source === "demo") &&
    (record.project === undefined || isSavedProject(record.project))
  );
}

function deletedMeta(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Deleted recently";
  return "Deleted " + date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function savedProjectIndex(project: SavedWorkflowProject): SavedProjectIndexRecord {
  return {
    storage: "indexeddb",
    project_id: project.project_id,
    name: project.name,
    updated_at: project.updated_at,
    favorite: project.favorite,
    img: project.img,
    canvas_workflow_id: project.canvas_workflow_id,
  };
}

function savedProjectFromStoredValue(value: unknown, storage: Pick<Storage, "getItem" | "setItem">): SavedWorkflowProject[] {
  if (isSavedProject(value)) {
    const project = sanitizeProjectRecord(value);
    saveProjectRecord(project, storage);
    rewriteSavedProjectIndex(storage, [project]);
    return [project];
  }
  if (!isSavedProjectIndex(value)) return [];
  const storedProject = loadHybridRecordSync<SavedWorkflowProject>("projectRecords", value.project_id);
  return [isSavedProject(storedProject) ? sanitizeProjectRecord(storedProject) : savedProjectShell(value)];
}

function savedProjectShell(project: SavedProjectIndexRecord): SavedWorkflowProject {
  return {
    project_id: project.project_id,
    name: project.name,
    updated_at: project.updated_at,
    favorite: project.favorite,
    img: project.img,
    workflow: null,
    messages: [],
    nodeRuns: [],
    selectedAssets: [],
    promptLibraryEntities: [],
    canvas_workflow_id: project.canvas_workflow_id,
  };
}

function isSavedProjectIndex(value: unknown): value is SavedProjectIndexRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<SavedProjectIndexRecord>;
  return (
    record.storage === "indexeddb" &&
    typeof record.project_id === "string" &&
    typeof record.name === "string" &&
    typeof record.updated_at === "string" &&
    typeof record.favorite === "boolean" &&
    typeof record.img === "string"
  );
}

function readSavedProjectIndex(storage: Pick<Storage, "getItem">) {
  try {
    const value = storage.getItem(WORKSPACE_PROJECTS_KEY);
    const parsed = value ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isSavedProjectIndex);
  } catch {
    return [];
  }
}

function rewriteSavedProjectIndex(storage: Pick<Storage, "getItem" | "setItem">, projects: SavedWorkflowProject[]) {
  const existing = readSavedProjectIndex(storage);
  const projectById = new Map(existing.map((project) => [project.project_id, project]));
  for (const project of projects) projectById.set(project.project_id, savedProjectIndex(project));
  safeWriteJson(storage, WORKSPACE_PROJECTS_KEY, [...projectById.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
}

function trashedProjectIndex(project: TrashedProjectRecord): TrashedProjectIndexRecord {
  return {
    storage: "indexeddb",
    type: "project",
    project_id: project.project_id,
    name: project.name,
    meta: project.meta,
    deleted_at: project.deleted_at,
    updated_at: project.updated_at,
    favorite: project.favorite,
    img: project.img,
    source: project.source,
  };
}

function trashedProjectFromStoredValue(value: unknown, storage: Pick<Storage, "getItem" | "setItem">): TrashedProjectRecord[] {
  if (isTrashedProjectIndex(value)) {
    return [loadHybridRecordSync<TrashedProjectRecord>("trashRecords", value.project_id) ?? trashedProjectShell(value)];
  }
  if (isTrashedProject(value)) {
    saveHybridRecordSync("trashRecords", value.project_id, value);
    rewriteTrashedProjectIndex(storage, [value]);
    return [value];
  }
  return [];
}

function trashedProjectShell(project: TrashedProjectIndexRecord): TrashedProjectRecord {
  return {
    type: "project",
    project_id: project.project_id,
    name: project.name,
    meta: project.meta,
    deleted_at: project.deleted_at,
    updated_at: project.updated_at,
    favorite: project.favorite,
    img: project.img,
    source: project.source,
  };
}

function isTrashedProjectIndex(value: unknown): value is TrashedProjectIndexRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<TrashedProjectIndexRecord>;
  return (
    record.storage === "indexeddb" &&
    record.type === "project" &&
    typeof record.project_id === "string" &&
    typeof record.name === "string" &&
    typeof record.meta === "string" &&
    typeof record.deleted_at === "string" &&
    typeof record.updated_at === "string" &&
    typeof record.favorite === "boolean" &&
    typeof record.img === "string" &&
    (record.source === "saved" || record.source === "demo")
  );
}

function readTrashedProjectIndex(storage: Pick<Storage, "getItem">) {
  try {
    const value = storage.getItem(WORKSPACE_TRASH_PROJECTS_KEY);
    const parsed = value ? JSON.parse(value) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isTrashedProjectIndex);
  } catch {
    return [];
  }
}

function rewriteTrashedProjectIndex(storage: Pick<Storage, "getItem" | "setItem">, projects: TrashedProjectRecord[]) {
  const existing = readTrashedProjectIndex(storage);
  const projectById = new Map(existing.map((project) => [project.project_id, project]));
  for (const project of projects) projectById.set(project.project_id, trashedProjectIndex(project));
  safeWriteJson(storage, WORKSPACE_TRASH_PROJECTS_KEY, [...projectById.values()].sort((a, b) => b.deleted_at.localeCompare(a.deleted_at)));
}
