import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

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
  WorkflowPage: () => <div>Workflow page</div>,
}));
vi.mock("../components/V2WorkflowRevisionControl", async () => {
  const { useApp } = await import("../AppContextValue");
  return {
    default: () => {
      const { workspaceHydrated } = useApp();
      return <span>Workspace shell {workspaceHydrated ? "hydrated" : "loading"}</span>;
    },
  };
});

import App from "../App";
import { AppProvider } from "../AppContext";
import { WORKSPACE_ACTIVE_PROJECT_KEY } from "../projects/newProject";

const webRoot = process.cwd();
const entryGraphAnalyzer = join(webRoot, "scripts/perf/check-entry-graph.mjs");
const manifestPath = join(webRoot, "dist/.vite/manifest.json");

function resetApiMocks() {
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({ service: "AdCraft", mode: "test" }),
  });
  api.health.mockResolvedValue({ service: "AdCraft", mode: "test" });
  api.listAssets.mockResolvedValue({ assets: [] });
  api.nodeCatalog.mockResolvedValue({ nodes: [] });
  api.workflowNodes.mockResolvedValue({ nodes: [] });
  v2Api.listProjects.mockResolvedValue({ projects: [], next_cursor: null });
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
    expect(screen.getByText("Workflow page")).toBeTruthy();
  });

  test("starts an empty workflow draft from Home without restoring the previous project", async () => {
    window.localStorage.setItem(WORKSPACE_ACTIVE_PROJECT_KEY, "persisted-project");
    window.localStorage.setItem("ad-workflow-active-workflow", "persisted-workflow");
    window.localStorage.setItem("ad-workflow-copilot-messages", "persisted-messages");

    render(
      <AppProvider>
        <App />
      </AppProvider>,
    );

    await screen.findByText("API ready");
    fireEvent.click(screen.getByRole("button", { name: /create your project/i }));

    await screen.findByText("Workflow page");

    expect(window.localStorage.getItem(WORKSPACE_ACTIVE_PROJECT_KEY)).toBeNull();
    expect(window.localStorage.getItem("ad-workflow-active-workflow")).toBeNull();
    expect(window.localStorage.getItem("ad-workflow-copilot-messages")).not.toBe("persisted-messages");
    expect(v2Api.listProjects).not.toHaveBeenCalled();
    expect(v2Api.projectWorkflow).not.toHaveBeenCalled();
  });

  test("keeps workflow and React Flow chunks out of the built Home entry graph", () => {
    execFileSync("npm", ["run", "build"], { cwd: webRoot, stdio: "pipe" });

    const graphResult = spawnSync(process.execPath, [
      entryGraphAnalyzer,
      "--manifest",
      manifestPath,
      "--entry",
      "src/pages/HomePage.tsx",
      "--json",
    ], { encoding: "utf8" });

    expect(graphResult.status).toBe(0);

    const graph = JSON.parse(graphResult.stdout) as { modules: string[] };
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, { file: string }>;
    const homeFiles = graph.modules.map((moduleId) => manifest[moduleId]?.file ?? moduleId);

    expect([...graph.modules, ...homeFiles]).not.toEqual(
      expect.arrayContaining([
        expect.stringMatching(/(?:WorkflowPage|features\/workflow|vendor-react-flow|react-flow)/i),
      ]),
    );
  }, 30_000);
});
