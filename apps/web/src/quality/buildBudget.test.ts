import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test } from "vitest";

const budgetScriptPath = join(process.cwd(), "scripts/perf/check-build-budget.mjs");
const temporaryDirectories: string[] = [];

function writeAsset(assetsDirectory: string, name: string, size = 1) {
  writeFileSync(join(assetsDirectory, name), Buffer.alloc(size));
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { force: true, recursive: true });
  }
});

describe("build budget", () => {
  test("selects the JavaScript Workflow route entry when CSS has the same chunk name", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "WorkflowPage-fixture.js",
      "WorkflowPage-fixture.css",
      "vendor-react-flow-fixture.js",
      "vendor-react-flow-fixture.css",
      "AssetEntityViewer-fixture.js",
      "global-fixture.css",
      "home-fixture.js",
      "home-fixture.css",
    ]) {
      writeAsset(assetsDirectory, asset);
    }

    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        css: ["assets/global-fixture.css"],
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home-fixture.js",
        css: ["assets/home-fixture.css"],
      },
      "_WorkflowPage-fixture.css": {
        file: "assets/WorkflowPage-fixture.css",
        src: "_WorkflowPage-fixture.css",
      },
      "src/pages/WorkflowPage.tsx": {
        name: "WorkflowPage",
        file: "assets/WorkflowPage-fixture.js",
        imports: ["_vendor-react-flow.js"],
        css: ["assets/WorkflowPage-fixture.css"],
      },
      "_vendor-react-flow.js": {
        name: "vendor-react-flow",
        file: "assets/vendor-react-flow-fixture.js",
        css: ["assets/vendor-react-flow-fixture.css"],
      },
    }));

    const result = spawnSync(process.execPath, [
      budgetScriptPath,
      "--dist",
      distDirectory,
    ], { encoding: "utf8" });

    expect(result.status).toBe(0);
    expect(result.stderr).not.toContain("Agent Canvas Workflow route chunk is missing");
    expect(result.stderr).not.toContain("Agent Canvas Workflow route does not own the React Flow vendor chunk");
  });

  test("keeps Agent Canvas and React Flow out of the initial application chunk", () => {
    const appSource = readFileSync(
      join(process.cwd(), "src/App.tsx"),
      "utf8",
    );
    const workflowPageSource = readFileSync(
      join(process.cwd(), "src/pages/WorkflowPage.tsx"),
      "utf8",
    );
    const viteSource = readFileSync(
      join(process.cwd(), "vite.config.ts"),
      "utf8",
    );
    const budgetSource = readFileSync(budgetScriptPath, "utf8");

    expect(appSource).toContain('lazy(() => import("./pages/WorkflowPage")');
    expect(workflowPageSource).toContain(
      'import { AgentCanvasPage } from "../features/agent-canvas/AgentCanvasPage.tsx"',
    );
    expect(viteSource).toContain('return "vendor-react-flow"');
    expect(budgetSource).toContain("MAX_AGENT_CANVAS_ROUTE_JS_BYTES");
    expect(budgetSource).toContain("MAX_VENDOR_REACT_FLOW_JS_BYTES");
    expect(budgetSource).toContain('asset.name.startsWith("WorkflowPage-")');
    expect(budgetSource).toContain('asset.name.startsWith("vendor-react-flow-")');
  });

  test("does not retain the removed Home WebGL renderer budget", () => {
    const viteSource = readFileSync(
      join(process.cwd(), "vite.config.ts"),
      "utf8",
    );
    const budgetSource = readFileSync(budgetScriptPath, "utf8");

    expect(viteSource).not.toContain('return "vendor-three"');
    expect(budgetSource).not.toContain("MAX_HOME_COSMIC_RENDERER_JS_BYTES");
    expect(budgetSource).not.toContain('asset.name.startsWith("homeCosmicRenderer-")');
    expect(budgetSource).not.toContain('asset.name.startsWith("vendor-three-")');
  });

  test("counts deduplicated CSS across Home's full static import graph", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "home-fixture.js",
      "shared-a-fixture.js",
      "shared-b-fixture.js",
      "screenplay-editor-fixture.js",
      "V2FinalCompositionEditor-fixture.js",
      "V2ShotTimeline-fixture.js",
      "timeline-editor-fixture.js",
      "AssetEntityViewer-fixture.js",
      "timeline-editor-fixture.css",
    ]) {
      writeAsset(assetsDirectory, asset);
    }
    writeAsset(assetsDirectory, "home-fixture.css", 2 * 1024);
    writeAsset(assetsDirectory, "shared-fixture.css", 15 * 1024);
    writeAsset(assetsDirectory, "global-fixture.css", 12 * 1024);

    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        css: ["assets/global-fixture.css"],
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home-fixture.js",
        css: ["assets/home-fixture.css"],
        imports: ["_shared-a.js", "_shared-b.js", "index.html"],
      },
      "_shared-a.js": {
        file: "assets/shared-a-fixture.js",
        css: ["assets/shared-fixture.css"],
        imports: ["_shared-b.js"],
      },
      "_shared-b.js": {
        file: "assets/shared-b-fixture.js",
        css: ["assets/shared-fixture.css"],
      },
      "src/features/workflow/final-composition/V2FinalCompositionEditor.tsx": {
        file: "assets/V2FinalCompositionEditor-fixture.js",
        dynamicImports: [
          "src/features/workflow/final-composition/V2ShotTimeline.tsx",
        ],
      },
      "src/features/workflow/final-composition/V2ShotTimeline.tsx": {
        file: "assets/V2ShotTimeline-fixture.js",
        imports: ["_timeline-editor.js"],
      },
      "_timeline-editor.js": {
        file: "assets/timeline-editor-fixture.js",
      },
    }));

    const result = spawnSync(process.execPath, [
      budgetScriptPath,
      "--dist",
      distDirectory,
    ], { encoding: "utf8" });

    expect(result.status).toBe(1);
    expect(result.stdout).toContain("Home route CSS total: 17 KiB");
    expect(result.stderr).toContain("Home route CSS is 17 KiB, expected <= 16 KiB");
  });

  test("rejects a production-shaped Agent Canvas route without the React Flow vendor import", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "home-fixture.js",
      "WorkflowPage-fixture.js",
      "vendor-react-flow-fixture.js",
      "AssetEntityViewer-fixture.js",
      "global-fixture.css",
      "home-fixture.css",
      "WorkflowPage-fixture.css",
      "vendor-react-flow-fixture.css",
    ]) {
      writeAsset(assetsDirectory, asset);
    }

    writeFileSync(join(manifestDirectory, "manifest.json"), JSON.stringify({
      "index.html": {
        file: "assets/index-fixture.js",
        css: ["assets/global-fixture.css"],
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home-fixture.js",
        css: ["assets/home-fixture.css"],
      },
      "src/pages/WorkflowPage.tsx": {
        name: "WorkflowPage",
        file: "assets/WorkflowPage-fixture.js",
        css: ["assets/WorkflowPage-fixture.css"],
      },
      "_vendor-react-flow.js": {
        name: "vendor-react-flow",
        file: "assets/vendor-react-flow-fixture.js",
        css: ["assets/vendor-react-flow-fixture.css"],
      },
    }));

    const result = spawnSync(process.execPath, [
      budgetScriptPath,
      "--dist",
      distDirectory,
    ], { encoding: "utf8" });

    expect(result.status).toBe(1);
    expect(result.stderr).toContain(
      "Agent Canvas Workflow route does not own the React Flow vendor chunk",
    );
  });
});
