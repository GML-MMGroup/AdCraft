import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");

function source(path: string) {
  return readFileSync(resolve(sourceRoot, path), "utf8");
}

function declarationBlock(styles: string, selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(new RegExp(`(?:^|\\n)${escapedSelector}\\s*\\{([^}]*)\\}`, "m"));
  expect(match, `missing ${selector} declaration`).not.toBeNull();
  return match?.[1] ?? "";
}

describe("route-scoped styles", () => {
  it("loads only shared primitives from the application entry", () => {
    expect(source("main.tsx")).toContain('import "./styles/base.css"');
    expect(source("main.tsx")).not.toContain('import "./styles.css"');
  });

  it("keeps the shared shell full-bleed without a visible frame", () => {
    const baseStyles = source("styles/base.css");
    const shell = declarationBlock(baseStyles, ".app-shell");
    const workflowShell = declarationBlock(baseStyles, ".app-shell--workflow");

    expect(shell).toContain("width: 100%");
    expect(shell).toContain("min-height: 100dvh");
    expect(shell).toContain("margin: 0");
    expect(shell).toContain("overflow: visible");
    expect(shell).toContain("border: 0");
    expect(shell).toContain("border-radius: 0");
    expect(shell).toContain("background: transparent");
    expect(shell).toContain("box-shadow: none");
    expect(shell).toContain("backdrop-filter: none");
    expect(workflowShell).toContain("min-height: 100dvh");
    expect(workflowShell).toContain("margin: 0");
  });

  it("keeps complete cross-route primitives in the shared stylesheet", () => {
    const baseStyles = source("styles/base.css");

    expect(declarationBlock(baseStyles, ".composer-footer")).toMatch(
      /justify-content:\s*space-between;[\s\S]*gap:\s*12px;[\s\S]*border-top:[\s\S]*padding-top:\s*13px;/,
    );
    expect(declarationBlock(baseStyles, ".toolbar-row")).toMatch(
      /display:\s*flex;[\s\S]*flex-wrap:\s*wrap;[\s\S]*gap:\s*9px;/,
    );
    expect(declarationBlock(baseStyles, ".filter-btn.is-active")).toMatch(
      /background:\s*linear-gradient[\s\S]*color:\s*white;/,
    );
    expect(declarationBlock(baseStyles, ".send-btn")).toMatch(
      /min-width:\s*112px;[\s\S]*padding:\s*0 18px;[\s\S]*background:\s*linear-gradient[\s\S]*color:\s*white;[\s\S]*font-weight:\s*600;/,
    );
    expect(declarationBlock(baseStyles, ".send-btn.icon-only")).toMatch(
      /width:\s*42px;[\s\S]*min-width:\s*42px;[\s\S]*padding:\s*0;/,
    );
    expect(baseStyles).toMatch(
      /\.send-btn svg,[\s\S]*width:\s*18px;[\s\S]*height:\s*18px;[\s\S]*flex:\s*0 0 auto;/,
    );
    expect(declarationBlock(baseStyles, ".card-meta")).toMatch(
      /justify-content:\s*space-between;[\s\S]*gap:\s*10px;[\s\S]*margin-top:\s*12px;[\s\S]*font-size:\s*13px;[\s\S]*line-height:\s*1\.4;/,
    );

    const workflowStyles = source("features/workflow/workflow.css");
    expect(workflowStyles).not.toContain(".composer-footer {\n  justify-content: space-between;");
    expect(workflowStyles).not.toContain(".toolbar-row {\n  display: flex;");
    expect(workflowStyles).not.toContain(".send-btn {\n  min-width: 112px;");
    expect(workflowStyles).not.toContain(".filter-btn.is-active,");
    expect(source("pages/assets.css")).not.toContain(".card-meta {\n  justify-content: space-between;");
  });

  it("styles the global Suspense fallback without a lazy route stylesheet", () => {
    const appSource = source("App.tsx");
    const baseStyles = source("styles/base.css");

    expect(appSource).toContain('className="route-loading"');
    expect(appSource).toContain('className="route-loading-spinner"');
    expect(appSource).not.toContain("workflow-card-preview-loading");
    expect(declarationBlock(baseStyles, ".route-fallback")).toMatch(
      /display:\s*grid;[\s\S]*min-height:[\s\S]*place-items:\s*center;/,
    );
    expect(declarationBlock(baseStyles, ".route-loading")).toMatch(
      /display:\s*grid;[\s\S]*place-items:\s*center;[\s\S]*border-radius:/,
    );
    expect(declarationBlock(baseStyles, ".route-loading-spinner")).toMatch(
      /border:[\s\S]*border-top-color:[\s\S]*animation:\s*route-loading-spin/,
    );
    expect(baseStyles).toContain("@keyframes route-loading-spin");
  });

  it("loads the Agent Canvas shell and styles directly from the Workflow route", () => {
    const workflowPageSource = source("pages/WorkflowPage.tsx");
    const agentCanvasPageSource = source("features/agent-canvas/AgentCanvasPage.tsx");
    const agentCanvasStyles = source("features/agent-canvas/agent-canvas-page.css");

    expect(workflowPageSource).toContain(
      'import { AgentCanvasPage } from "../features/agent-canvas/AgentCanvasPage.tsx"',
    );
    expect(workflowPageSource).not.toContain("features/workflow/workflow.css");
    expect(agentCanvasPageSource).toContain('import "@xyflow/react/dist/style.css"');
    expect(agentCanvasPageSource).toContain('import "./agent-canvas-page.css"');
    expect(declarationBlock(agentCanvasStyles, ".agent-canvas-page")).toMatch(
      /position:\s*relative;[\s\S]*display:\s*grid;[\s\S]*height:\s*calc\(100dvh - var\(--topbar-height\)\);[\s\S]*overflow:\s*hidden;/,
    );
    expect(declarationBlock(agentCanvasStyles, ".agent-canvas-board")).toMatch(
      /position:\s*relative;[\s\S]*min-width:\s*0;[\s\S]*min-height:\s*0;[\s\S]*overflow:\s*hidden;/,
    );
  });

  it("keeps workflow and final-composition selectors out of Home styles", () => {
    expect(existsSync(resolve(sourceRoot, "pages/home.css"))).toBe(true);
    const homeStyles = source("pages/home.css");
    expect(homeStyles).not.toMatch(/\.workflow-(?:board|card|page)/);
    expect(homeStyles).not.toMatch(/\.v2-(?:composition|final-composition)/);
  });

  it("loads each large feature stylesheet from its lazy route", () => {
    expect(source("pages/HomePage.tsx")).toContain('import "./home.css"');
    expect(source("pages/ProjectsPage.tsx")).toContain('import "./projects.css"');
    expect(source("pages/TrashPage.tsx")).toContain('import "./projects.css"');
    expect(source("pages/AssetsPage.tsx")).toContain('import "./assets.css"');
    expect(source("pages/ApiSpacePage.tsx")).toContain('import "./api-space.css"');
    expect(source("features/agent-canvas/AgentCanvasPage.tsx")).toContain(
      'import "./agent-canvas-page.css"',
    );
  });
});
