import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { legacyApi, v2Api } = vi.hoisted(() => ({
  legacyApi: {
    listAssets: vi.fn(async () => ({ assets: [] })),
    nodeCatalog: vi.fn(async () => ({ nodes: [] })),
    workflowNodes: vi.fn(async () => ({ nodes: [] })),
  },
  v2Api: {
    listProjects: vi.fn(async () => ({ items: [], next_cursor: null })),
    createAgentCanvasProject: vi.fn(),
    projectWithEtag: vi.fn(),
    agentCanvasWorkflowWithEtag: vi.fn(),
    trashProject: vi.fn(),
    restoreProject: vi.fn(),
    updateProject: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api: legacyApi }));
vi.mock("../api/v2Client", () => ({
  v2Api,
  isV2ApiError: (value: unknown) => Boolean(value && typeof value === "object" && "status" in value),
  isNetworkError: (value: unknown) => value instanceof Error && value.name === "V2NetworkError",
}));

import { useApp } from "../AppContextValue.ts";
import { v2AuthoringConflictStore } from "../api/v2AuthoringConflictStore.ts";
import { normalizeCanvasNodeV2 } from "../features/agent-canvas/model/normalizers.ts";
import { saveProjectCatalogCache } from "../projects/projectCatalogCache.ts";
import { WORKSPACE_ACTIVE_PROJECT_KEY, WORKSPACE_WORKFLOW_KEY } from "../projects/newProject.ts";
import { WorkspaceProvider } from "./WorkspaceProvider.tsx";

const workflow = {
  workflow_id: "workflow-1",
  project_id: "project-1",
  workflow_schema_version: 2,
  canvas_model: "agent_canvas_v1",
  revision: 1,
  nodes: [],
  bindings: [],
  assets: [],
} as const;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createWorkflowContractError() {
  try {
    normalizeCanvasNodeV2(null, "workflow.nodes[8]");
  } catch (error) {
    return error;
  }
  throw new Error("Expected malformed workflow data to fail validation.");
}

function Probe() {
  const {
    agentCanvasWorkflow,
    activeProjectId,
    startNewProject,
    workspaceHydrated,
    workspaceRestoreError,
    projectCatalogError,
    refreshProjects,
    savedProjects,
  } = useApp();
  return (
    <div>
      <span>{workspaceHydrated ? "hydrated" : "loading"}</span>
      <span>{activeProjectId ?? "no-project"}</span>
      <span>{agentCanvasWorkflow?.workflow_id ?? "no-workflow"}</span>
      <span>{`projects:${savedProjects.length}`}</span>
      <span>{projectCatalogError ?? "catalog-ok"}</span>
      <span>{workspaceRestoreError ?? "restore-ok"}</span>
      <button type="button" onClick={() => void startNewProject()}>Create</button>
      <button type="button" onClick={() => void refreshProjects()}>Refresh projects</button>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  v2Api.listProjects.mockResolvedValue({ items: [], next_cursor: null });
  v2Api.createAgentCanvasProject.mockResolvedValue({ value: workflow, etag: '"workflow-1-r1"' });
  v2Api.projectWithEtag.mockResolvedValue({
    value: {
      project_id: "project-1",
      workflow_id: "workflow-1",
      name: "Campaign",
    },
    etag: '"project-1-v1"',
  });
  v2Api.agentCanvasWorkflowWithEtag.mockResolvedValue({
    value: workflow,
    etag: '"workflow-1-r1"',
  });
});

afterEach(() => {
  v2AuthoringConflictStore.clear();
  cleanup();
});

describe("WorkspaceProvider Agent Canvas authority", () => {
  it("renders the persisted project catalog before the refresh completes", async () => {
    saveProjectCatalogCache({
      active: [{
        project_id: "cached-project",
        workflow_id: "cached-workflow",
        name: "Cached campaign",
        status: "active",
        is_favorite: false,
        cover_asset_id: null,
        project_version: 1,
        updated_at: "2026-08-28T00:00:00Z",
      }],
      trashed: [],
      savedAt: Date.now(),
    });

    render(
      <WorkspaceProvider restoreActiveWorkflow={false} projectCatalogScope="active">
        <Probe />
      </WorkspaceProvider>,
    );

    expect(screen.getByText("projects:1")).toBeTruthy();
    await screen.findByText("hydrated");
    expect(screen.getByText("projects:0")).toBeTruthy();
  });

  it("loads the active project catalog without restoring a workflow for a catalog-only route", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");

    render(
      <WorkspaceProvider restoreActiveWorkflow={false} projectCatalogScope="active">
        <Probe />
      </WorkspaceProvider>,
    );

    await screen.findByText("hydrated");
    expect(v2Api.listProjects).toHaveBeenCalledWith("active", 100, undefined);
    expect(v2Api.listProjects).not.toHaveBeenCalledWith("trashed", 100, undefined);
    expect(v2Api.projectWithEtag).not.toHaveBeenCalled();
    expect(v2Api.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
  });

  it("creates the backend project before exposing a new workflow", async () => {
    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await screen.findByText("hydrated");

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("workflow-1");
    expect(v2Api.createAgentCanvasProject).toHaveBeenCalledTimes(1);
    expect(v2Api.createAgentCanvasProject.mock.calls[0]?.[0]).toEqual({
      name: "Untitled Project",
      description: "",
    });
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBe("project-1");
  });

  it("restores only backend identity and ignores a complete local workflow document", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    window.localStorage.setItem(WORKSPACE_WORKFLOW_KEY, JSON.stringify({
      workflow_id: "local-workflow",
      nodes: [{ id: "local-node" }],
    }));

    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);

    await screen.findByText("workflow-1");
    expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-1");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-1");
    expect(screen.queryByText("local-workflow")).toBeNull();
  });

  it("restores the workflow before the project catalog refresh completes", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    const catalog = deferred<{ items: never[]; next_cursor: null }>();
    v2Api.listProjects.mockReturnValue(catalog.promise);

    render(<WorkspaceProvider projectCatalogScope="active"><Probe /></WorkspaceProvider>);

    await waitFor(() => expect(screen.getByText("workflow-1")).toBeTruthy(), { timeout: 250 });
    expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-1");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-1");

    catalog.resolve({ items: [], next_cursor: null });
    await waitFor(() => expect(screen.getByText("projects:0")).toBeTruthy());
  });

  it("uses a cached project workflow identity without waiting for project detail", async () => {
    saveProjectCatalogCache({
      active: [{
        project_id: "project-1",
        workflow_id: "workflow-1",
        name: "Cached campaign",
        description: "",
        status: "active",
        is_favorite: false,
        cover_asset_id: null,
        project_version: 1,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      }],
      trashed: [],
      savedAt: Date.now(),
    });
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    const catalog = deferred<{ items: never[]; next_cursor: null }>();
    v2Api.listProjects.mockReturnValue(catalog.promise);

    render(<WorkspaceProvider projectCatalogScope="active"><Probe /></WorkspaceProvider>);

    await waitFor(() => expect(screen.getByText("workflow-1")).toBeTruthy(), { timeout: 250 });
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-1");
    expect(v2Api.projectWithEtag).not.toHaveBeenCalled();
    catalog.resolve({ items: [], next_cursor: null });
  });

  it("falls back to authoritative project detail when the cached workflow is stale", async () => {
    saveProjectCatalogCache({
      active: [{
        project_id: "project-1",
        workflow_id: "workflow-stale",
        name: "Cached campaign",
        description: "",
        status: "active",
        is_favorite: false,
        cover_asset_id: null,
        project_version: 1,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      }],
      trashed: [],
      savedAt: Date.now(),
    });
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    v2Api.agentCanvasWorkflowWithEtag.mockImplementation(async (workflowId: string) => ({
      value: workflowId === "workflow-stale" ? { ...workflow, project_id: "other-project" } : workflow,
      etag: `"${workflowId}-r1"`,
    }));

    render(<WorkspaceProvider projectCatalogScope="active"><Probe /></WorkspaceProvider>);

    await screen.findByText("workflow-1");
    expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-1");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenNthCalledWith(1, "workflow-stale");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenNthCalledWith(2, "workflow-1");
  });

  it("creates a backend project when the route requests a fresh project", async () => {
    render(
      <StrictMode>
        <WorkspaceProvider startWithNewProject><Probe /></WorkspaceProvider>
      </StrictMode>,
    );

    await waitFor(() => expect(v2Api.createAgentCanvasProject).toHaveBeenCalledTimes(1));
    await screen.findByText("workflow-1");
  });

  it("keeps a successfully created Project open when the list refresh is unavailable", async () => {
    v2Api.listProjects
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockResolvedValueOnce({ items: [], next_cursor: null })
      .mockRejectedValue(new Error("Project list unavailable"));

    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await screen.findByText("hydrated");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("workflow-1");
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBe("project-1");
    expect(v2Api.createAgentCanvasProject).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Existing projects are still shown/)).toBeTruthy();
  });

  it("retains the last successful project catalog when a later refresh fails", async () => {
    v2Api.listProjects.mockImplementation(async (status: string) => ({
      items: status === "active" ? [{
        project_id: "project-catalog-1",
        workflow_id: "workflow-catalog-1",
        name: "Catalog project",
        description: "",
        status: "active",
        is_favorite: false,
        cover_asset_id: null,
        project_version: 1,
        created_at: "2026-08-18T00:00:00Z",
        updated_at: "2026-08-18T00:00:00Z",
      }] : [],
      next_cursor: null,
    }));
    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await screen.findByText("projects:1");

    v2Api.listProjects.mockRejectedValue(new Error("Project list unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh projects" }));

    await screen.findByText(/Existing projects are still shown/);
    expect(screen.getByText("projects:1")).toBeTruthy();
  });

  it("reports a network restore failure without clearing the active project preference", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    const networkError = new Error("Failed to fetch");
    networkError.name = "V2NetworkError";
    v2Api.projectWithEtag.mockRejectedValue(networkError);

    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);

    await screen.findByText(/backend could not be reached/i);
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBe("project-1");
    expect(screen.getByText("project-1")).toBeTruthy();
  });

  it("reports an incompatible workflow contract without clearing the active project preference", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    v2Api.agentCanvasWorkflowWithEtag.mockRejectedValue(createWorkflowContractError());

    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);

    await screen.findByText(/workflow data does not match this frontend/i);
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBe("project-1");
    expect(screen.getByText("project-1")).toBeTruthy();
  });

  it("clears only a backend-confirmed missing active project identity", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    v2Api.projectWithEtag.mockRejectedValue({
      status: 404,
      code: "project_not_found",
      message: "Project not found",
    });

    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);

    await screen.findByText("no-project");
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBeNull();
  });

  it("preserves the local workflow until the user resolves a revision conflict", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await screen.findByText("workflow-1");
    v2Api.agentCanvasWorkflowWithEtag.mockClear();

    v2AuthoringConflictStore.raise({
      target: { resource: "workflow", id: "workflow-1" },
      operationPath: "/workflows/workflow-1/nodes/node-1",
      message: "Workflow revision changed.",
      retry: vi.fn(async () => {}),
      discard: vi.fn(async () => {}),
    });

    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(v2Api.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
    expect(screen.getByText("workflow-1")).toBeTruthy();
  });
});
