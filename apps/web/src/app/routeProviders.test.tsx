import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { api, fetchMock, v2Api, isV2ApiError, isNetworkError } = vi.hoisted(() => ({
  api: {
    health: vi.fn(),
    listAssets: vi.fn(),
    nodeCatalog: vi.fn(),
    workflowNodes: vi.fn(),
  },
  fetchMock: vi.fn(),
  v2Api: {
    listProjects: vi.fn(),
    createAgentCanvasProject: vi.fn(),
    projectWithEtag: vi.fn(),
    agentCanvasWorkflowWithEtag: vi.fn(),
  },
  isV2ApiError: vi.fn(() => false),
  isNetworkError: vi.fn(() => false),
}));

vi.mock("../api/client", () => ({ api, mediaUrl: (path: string) => path }));
vi.mock("../api/v2Client", () => ({ v2Api, isV2ApiError, isNetworkError }));
vi.mock("../pages/WorkflowPage", () => ({
  WorkflowPage: () => <WorkflowPageProbe />,
}));
vi.mock("../pages/ProjectsPage", () => ({
  ProjectsPage: () => <ProjectsPageProbe />,
}));
vi.mock("../pages/AssetsPage", () => ({
  AssetsPage: () => <div>Assets page</div>,
}));
vi.mock("../pages/ApiSpacePage", () => ({
  ApiSpacePage: () => <div>API Space page</div>,
}));
import App from "../App";
import { AppProvider } from "../AppContext";
import { useApp } from "../AppContextValue";
import {
  loadCanvasSnapshot,
  saveCanvasSnapshot,
  WORKSPACE_ACTIVE_PROJECT_KEY,
} from "../projects/newProject";

const webRoot = process.cwd();
const entryGraphAnalyzer = join(webRoot, "scripts/perf/check-entry-graph.mjs");
const manifestPath = join(webRoot, "dist/.vite/manifest.json");

function WorkflowPageProbe() {
  const { agentCanvasWorkflow } = useApp();
  return <div>Workflow page {agentCanvasWorkflow?.workflow_id ?? "empty"}</div>;
}

function ProjectsPageProbe() {
  const { savedProjects, workspaceHydrated } = useApp();
  return (
    <div>
      <span>Projects page {workspaceHydrated ? "hydrated" : "loading"}</span>
      {savedProjects.map((project) => <span key={project.project_id}>{project.name}</span>)}
    </div>
  );
}

function resetApiMocks() {
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({ service: "AdCraft", mode: "test" }),
  });
  api.health.mockResolvedValue({ service: "AdCraft", mode: "test" });
  api.listAssets.mockResolvedValue({ assets: [] });
  api.nodeCatalog.mockResolvedValue({ nodes: [] });
  api.workflowNodes.mockResolvedValue({ nodes: [] });
  v2Api.listProjects.mockResolvedValue({ items: [], next_cursor: null });
  v2Api.createAgentCanvasProject.mockResolvedValue({
    value: {
      workflow_id: "workflow-created",
      project_id: "project-created",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 1,
      nodes: [],
      bindings: [],
      assets: [],
    },
    etag: '"workflow-created-r1"',
  });
  v2Api.projectWithEtag.mockResolvedValue({
    value: {
      project_id: "project-restored",
      workflow_id: "workflow-restored",
      name: "Restored",
    },
    etag: '"project-restored-v1"',
  });
  v2Api.agentCanvasWorkflowWithEtag.mockResolvedValue({
    value: {
      workflow_id: "workflow-restored",
      project_id: "project-restored",
      workflow_schema_version: 2,
      canvas_model: "agent_canvas_v1",
      revision: 1,
      nodes: [],
      bindings: [],
      assets: [],
    },
    etag: '"workflow-restored-r1"',
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  resetApiMocks();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState({}, "", "/");
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("route providers", () => {
  test("mounts Home without hydrating the persisted workspace", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "persisted-project");

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");

    expect(v2Api.listProjects).not.toHaveBeenCalled();
    expect(v2Api.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
    expect(api.listAssets).not.toHaveBeenCalled();
    expect(api.nodeCatalog).not.toHaveBeenCalled();
    expect(api.workflowNodes).not.toHaveBeenCalled();
  });

  test("uses a dark-only shell without a theme switcher", async () => {
    window.localStorage.setItem("adcraft-theme", "light");

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");

    expect(screen.queryByRole("button", { name: /switch to .* theme/i })).toBeNull();
    expect(document.documentElement.dataset.theme).not.toBe("light");
    expect(readFileSync(join(webRoot, "index.html"), "utf8")).toContain('<meta name="color-scheme" content="dark" />');
    expect(readFileSync(join(webRoot, "index.html"), "utf8")).not.toContain("data-theme");
    expect(readFileSync(join(webRoot, "index.html"), "utf8")).not.toContain("adcraft-theme");
  });

  test("marks non-Workflow application shells for shared cosmic artwork", async () => {
    for (const path of ["/", "/projects", "/assets", "/trash", "/api-space"]) {
      cleanup();
      window.history.replaceState({}, "", path);
      const view = render(
        <AppProvider>
          <App />
        </AppProvider>,
      );

      await screen.findByText("API ready");
      expect(
        view.container.querySelector(".app-shell--cosmic"),
        `${path} should use the cosmic shell`,
      ).toBeTruthy();
    }

    for (const path of ["/workflow", "/Workflow", "/%77orkflow"]) {
      cleanup();
      window.history.replaceState({}, "", path);
      const workflow = render(
        <AppProvider>
          <App />
        </AppProvider>,
      );

      await screen.findByText("Workflow page empty");
      expect(
        workflow.container.querySelector(".app-shell--cosmic"),
        `${path} should retain the Workflow canvas shell`,
      ).toBeNull();
      expect(
        workflow.container.querySelector(".app-shell--workflow"),
        `${path} should use the full-height Workflow canvas shell`,
      ).toBeTruthy();
    }
  });

  test("renders the workflow Layout shell inside WorkspaceProvider", async () => {
    window.history.replaceState({}, "", "/workflow");

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workflow page empty");
    expect(screen.getByText("API ready")).toBeTruthy();
  });

  test("starts an empty workflow draft from Home without restoring the previous project", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "persisted-project");
    window.localStorage.setItem("ad-workflow-active-workflow", "persisted-workflow");
    window.localStorage.setItem("ad-workflow-copilot-messages", "persisted-messages");
    saveCanvasSnapshot(window.localStorage, "local-workflow", { nodes: ["persisted-node"] });
    expect(loadCanvasSnapshot(window.localStorage, "local-workflow")).toEqual({ nodes: ["persisted-node"] });

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");
    fireEvent.click(screen.getByRole("button", { name: /create your project/i }));

    await screen.findByText("Workflow page workflow-created");

    expect(window.location.pathname).toBe("/workflow/project-created");
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBe("project-created");
    expect(window.localStorage.getItem("ad-workflow-active-workflow")).toBeNull();
    expect(window.localStorage.getItem("ad-workflow-copilot-messages")).not.toBe("persisted-messages");
    await waitFor(() => expect(loadCanvasSnapshot(window.localStorage, "local-workflow")).toBeUndefined());
    expect(v2Api.createAgentCanvasProject).toHaveBeenCalledTimes(1);
    expect(v2Api.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
  });

  test("consumes the new-project route state so a reload can restore the saved project", async () => {
    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");
    fireEvent.click(screen.getByRole("button", { name: /create your project/i }));
    await screen.findByText("Workflow page workflow-created");

    await waitFor(() => expect(window.history.state?.usr ?? null).toBeNull());

    cleanup();
    window.history.replaceState({}, "", "/workflow");
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-after-planning");
    v2Api.projectWithEtag.mockResolvedValue({
      value: {
        project_id: "project-after-planning",
        workflow_id: "workflow-after-planning",
        name: "After planning",
      },
      etag: '"project-after-planning-v1"',
    });
    v2Api.agentCanvasWorkflowWithEtag.mockResolvedValue({
      value: {
        workflow_id: "workflow-after-planning",
        project_id: "project-after-planning",
        workflow_schema_version: 2,
        canvas_model: "agent_canvas_v1",
        revision: 1,
        nodes: [],
        bindings: [],
        assets: [],
      },
      etag: '"workflow-after-planning-r1"',
    });

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workflow page workflow-after-planning");
    expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-after-planning");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-after-planning");
  });

  test("restores the persisted active project on a workspace route", async () => {
    window.history.replaceState({}, "", "/workflow");
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-restored");
    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workflow page workflow-restored");
    expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-restored");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-restored");
    expect(v2Api.listProjects).toHaveBeenCalledTimes(1);
  });

  test("uses the workflow URL project before the shared recent-project preference", async () => {
    window.history.replaceState({}, "", "/workflow/project-a");
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-b");
    v2Api.projectWithEtag.mockImplementation(async (projectId: string) => ({
      value: {
        project_id: projectId,
        workflow_id: `workflow-${projectId}`,
        name: projectId,
      },
      etag: `"${projectId}-v1"`,
    }));
    v2Api.agentCanvasWorkflowWithEtag.mockImplementation(async (workflowId: string) => ({
      value: {
        workflow_id: workflowId,
        project_id: workflowId.replace("workflow-", ""),
        workflow_schema_version: 2,
        canvas_model: "agent_canvas_v1",
        revision: 1,
        nodes: [],
        bindings: [],
        assets: [],
      },
      etag: `"${workflowId}-r1"`,
    }));

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workflow page workflow-project-a");
    expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-a");
    expect(v2Api.projectWithEtag).not.toHaveBeenCalledWith("project-b");
    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBe("project-b");
  });

  test("keeps a URL-scoped restore alive when another tab changes recent project storage", async () => {
    window.history.replaceState({}, "", "/workflow/project-a");
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-b");
    let resolveProject: ((value: { value: { project_id: string; workflow_id: string; name: string }; etag: string }) => void) | undefined;
    v2Api.projectWithEtag.mockReturnValueOnce(new Promise((resolve) => {
      resolveProject = resolve;
    }));
    v2Api.agentCanvasWorkflowWithEtag.mockImplementation(async (workflowId: string) => ({
      value: {
        workflow_id: workflowId,
        project_id: "project-a",
        workflow_schema_version: 2,
        canvas_model: "agent_canvas_v1",
        revision: 1,
        nodes: [],
        bindings: [],
        assets: [],
      },
      etag: `"${workflowId}-r1"`,
    }));

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await waitFor(() => expect(v2Api.projectWithEtag).toHaveBeenCalledWith("project-a"));
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-c");
    resolveProject?.({
      value: { project_id: "project-a", workflow_id: "workflow-project-a", name: "Project A" },
      etag: '"project-a-v1"',
    });

    await screen.findByText("Workflow page workflow-project-a");
    expect(v2Api.agentCanvasWorkflowWithEtag).toHaveBeenCalledWith("workflow-project-a");
  });

  test("hydrates projects after leaving a fresh workflow draft", async () => {
    const project = {
      project_id: "project-after-draft",
      workflow_id: "workflow-after-draft",
      name: "Restored project list",
      updated_at: "2026-07-24T00:00:00Z",
      is_favorite: false,
      cover_asset_id: null,
    };
    v2Api.listProjects.mockImplementation(async (scope: string) => ({
      items: scope === "active" ? [project] : [],
      next_cursor: null,
    }));

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");
    fireEvent.click(screen.getByRole("button", { name: /create your project/i }));
    await screen.findByText("Workflow page workflow-created");

    fireEvent.click(screen.getByRole("link", { name: "Projects" }));

    await screen.findByText("Restored project list");
    expect(screen.getByText("Projects page hydrated")).toBeTruthy();
    expect(v2Api.listProjects).toHaveBeenCalledWith("active", 100, undefined);
    expect(v2Api.listProjects).not.toHaveBeenCalledWith("trashed", 100, undefined);
  });

  test.each([
    ["/assets", "Assets page"],
    ["/api-space", "API Space page"],
  ])("renders %s inside the lightweight shell without workspace hydration", async (route, page) => {
    window.history.replaceState({}, "", route);

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText(page);
    expect(v2Api.listProjects).not.toHaveBeenCalled();
    expect(v2Api.agentCanvasWorkflowWithEtag).not.toHaveBeenCalled();
  });

  test("shows the health failure state without workspace hydration", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Demo mode");
    expect(v2Api.listProjects).not.toHaveBeenCalled();
  });

  test("shows hybrid storage warnings from the lightweight provider", async () => {
    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");
    window.dispatchEvent(new CustomEvent("hybrid-storage:error", {
      detail: { message: "Storage write failed" },
    }));

    expect(await screen.findByText("Storage write failed")).toBeTruthy();
    expect(v2Api.listProjects).not.toHaveBeenCalled();
  });

  test("keeps workspace chunks out of the actual built Home route closure", () => {
    execFileSync("npm", ["run", "build"], { cwd: webRoot, stdio: "pipe" });

    function staticGraph(entry: string) {
      const graphResult = spawnSync(process.execPath, [
        entryGraphAnalyzer,
        "--manifest",
        manifestPath,
        "--entry",
        entry,
        "--static-only",
        "--json",
      ], { encoding: "utf8" });

      expect(graphResult.status).toBe(0);
      return JSON.parse(graphResult.stdout) as { modules: string[] };
    }

    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, {
      css?: string[];
      dynamicImports?: string[];
      file: string;
      name?: string;
    }>;
    const filesFor = (graph: { modules: string[] }) => graph.modules.flatMap((moduleId) => {
      const module = manifest[moduleId];
      return module ? [moduleId, module.file, ...(module.css ?? [])] : [moduleId];
    });
    const blocked = /(?:AppContext|projects|storage|workflow|screenplay|react-flow|app-core)/i;
    const home = staticGraph("src/pages/HomePage.tsx");
    const root = staticGraph("index.html");
    const layoutEntry = manifest["index.html"].dynamicImports?.find((entry) => manifest[entry]?.name === "Layout");

    expect([...home.modules, ...filesFor(home)]).not.toEqual(
      expect.arrayContaining([expect.stringMatching(blocked)]),
    );
    expect([...root.modules, ...filesFor(root)]).not.toEqual(
      expect.arrayContaining([expect.stringMatching(blocked)]),
    );

    expect(layoutEntry).toBeDefined();
    const layout = staticGraph(layoutEntry!);
    expect([
      ...root.modules,
      ...filesFor(root),
      ...layout.modules,
      ...filesFor(layout),
      ...home.modules,
      ...filesFor(home),
    ]).not.toEqual(expect.arrayContaining([expect.stringMatching(blocked)]));
  }, 30_000);
});
