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
}));

import { useApp } from "../AppContextValue.ts";
import { v2AuthoringConflictStore } from "../api/v2AuthoringConflictStore.ts";
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

  it("preserves the active project preference on a transient restore failure", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-1");
    v2Api.projectWithEtag.mockRejectedValue(new Error("Database temporarily unavailable"));

    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);

    await screen.findByText(/project selection was preserved/);
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
