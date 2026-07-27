import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { api, fetchMock, v2Api } = vi.hoisted(() => ({
  api: {
    health: vi.fn(),
    listAssets: vi.fn(),
    nodeCatalog: vi.fn(),
    workflowNodes: vi.fn(),
  },
  fetchMock: vi.fn(),
  v2Api: {
    listProjects: vi.fn(),
    projectWorkflow: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({ api, mediaUrl: (path: string) => path }));
vi.mock("../api/v2Client", () => ({ v2Api }));
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
vi.mock("../workflow-v2/pageAdapter", () => ({
  workflowV2ToWorkflowGraph: (workflow: unknown) => workflow,
}));
vi.mock("../components/V2WorkflowRevisionControl", async () => {
  const { useApp } = await import("../AppContextValue");
  return {
    default: function RevisionControlProbe() {
      const { workspaceHydrated } = useApp();
      return <span>Workspace shell {workspaceHydrated ? "hydrated" : "loading"}</span>;
    },
  };
});

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
  const { workflow } = useApp();
  return <div>Workflow page {workflow?.workflow_id ?? "empty"}</div>;
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
  v2Api.projectWorkflow.mockResolvedValue({ value: {} });
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
    expect(v2Api.projectWorkflow).not.toHaveBeenCalled();
    expect(api.listAssets).not.toHaveBeenCalled();
    expect(api.nodeCatalog).not.toHaveBeenCalled();
    expect(api.workflowNodes).not.toHaveBeenCalled();
  });

  test("renders the workflow Layout shell inside WorkspaceProvider", async () => {
    window.history.replaceState({}, "", "/workflow");

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workspace shell hydrated");
    expect(screen.getByText("Workflow page empty")).toBeTruthy();
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

    await screen.findByText("Workflow page empty");

    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBeNull();
    expect(window.localStorage.getItem("ad-workflow-active-workflow")).toBeNull();
    expect(window.localStorage.getItem("ad-workflow-copilot-messages")).not.toBe("persisted-messages");
    await waitFor(() => expect(loadCanvasSnapshot(window.localStorage, "local-workflow")).toBeUndefined());
    expect(v2Api.listProjects).not.toHaveBeenCalled();
    expect(v2Api.projectWorkflow).not.toHaveBeenCalled();
  });

  test("consumes the new-project route state so a reload can restore the saved project", async () => {
    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");
    fireEvent.click(screen.getByRole("button", { name: /create your project/i }));
    await screen.findByText("Workflow page empty");

    await waitFor(() => expect(window.history.state?.usr ?? null).toBeNull());

    cleanup();
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-after-planning");
    v2Api.projectWorkflow.mockResolvedValue({
      value: {
        workflow_id: "workflow-after-planning",
        project_id: "project-after-planning",
      },
    });

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workflow page workflow-after-planning");
    expect(v2Api.projectWorkflow).toHaveBeenCalledWith("project-after-planning");
  });

  test("restores the persisted active project on a workspace route", async () => {
    window.history.replaceState({}, "", "/workflow");
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "project-restored");
    v2Api.projectWorkflow.mockResolvedValue({
      value: { workflow_id: "workflow-restored", project_id: "project-restored" },
    });

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("Workflow page workflow-restored");
    expect(v2Api.projectWorkflow).toHaveBeenCalledWith("project-restored");
    expect(v2Api.listProjects).toHaveBeenCalledTimes(2);
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
    await screen.findByText("Workflow page empty");
    expect(v2Api.listProjects).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("link", { name: "Projects" }));

    await screen.findByText("Restored project list");
    expect(screen.getByText("Projects page hydrated")).toBeTruthy();
    expect(v2Api.listProjects).toHaveBeenCalledTimes(2);
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
    expect(v2Api.projectWorkflow).not.toHaveBeenCalled();
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
