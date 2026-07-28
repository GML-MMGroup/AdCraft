import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test } from "vitest";

const analyzerPath = join(process.cwd(), "scripts/perf/check-entry-graph.mjs");
const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { force: true, recursive: true });
  }
});

describe("entry graph analyzer", () => {
  test("includes Home's transitive dynamic imports", () => {
    expect(existsSync(analyzerPath)).toBe(true);

    const directory = mkdtempSync(join(tmpdir(), "adcraft-entry-graph-"));
    temporaryDirectories.push(directory);
    const manifestPath = join(directory, "manifest.json");
    writeFileSync(manifestPath, JSON.stringify({
      "src/pages/HomePage.tsx": {
        file: "assets/home.js",
        isDynamicEntry: true,
        css: ["assets/home.css"],
        dynamicImports: ["src/features/home/HomeWorkspace.tsx"],
      },
      "src/features/home/HomeWorkspace.tsx": {
        file: "assets/home-workspace.js",
        isDynamicEntry: true,
        css: ["assets/home-workspace.css"],
        dynamicImports: ["src/features/workflow/WorkflowPage.tsx"],
      },
      "src/features/workflow/WorkflowPage.tsx": {
        file: "assets/workflow.js",
        isDynamicEntry: true,
        css: ["assets/workflow.css"],
      },
    }));

    const output = execFileSync(process.execPath, [
      analyzerPath,
      "--manifest",
      manifestPath,
      "--entry",
      "src/pages/HomePage.tsx",
      "--json",
    ], { encoding: "utf8" });

    expect(JSON.parse(output)).toMatchObject({
      entry: "src/pages/HomePage.tsx",
      modules: [
        "src/pages/HomePage.tsx",
        "src/features/home/HomeWorkspace.tsx",
        "src/features/workflow/WorkflowPage.tsx",
      ],
      css: [
        "assets/home.css",
        "assets/home-workspace.css",
        "assets/workflow.css",
      ],
    });
  });

  test("can inspect only static entry imports", () => {
    const directory = mkdtempSync(join(tmpdir(), "adcraft-entry-graph-"));
    temporaryDirectories.push(directory);
    const manifestPath = join(directory, "manifest.json");
    writeFileSync(manifestPath, JSON.stringify({
      "index.html": {
        file: "assets/index.js",
        imports: ["src/main.tsx"],
        dynamicImports: ["src/pages/HomePage.tsx"],
      },
      "src/main.tsx": {
        file: "assets/main.js",
      },
      "src/pages/HomePage.tsx": {
        file: "assets/home.js",
      },
    }));

    const output = execFileSync(process.execPath, [
      analyzerPath,
      "--manifest",
      manifestPath,
      "--entry",
      "index.html",
      "--static-only",
      "--json",
    ], { encoding: "utf8" });

    expect(JSON.parse(output)).toMatchObject({
      entry: "index.html",
      modules: ["index.html", "src/main.tsx"],
    });
  });

  test("keeps the cosmic renderer outside Home's static graph", () => {
    const directory = mkdtempSync(join(tmpdir(), "adcraft-entry-graph-"));
    temporaryDirectories.push(directory);
    const manifestPath = join(directory, "manifest.json");
    writeFileSync(manifestPath, JSON.stringify({
      "src/pages/HomePage.tsx": {
        file: "assets/home.js",
        imports: ["src/pages/home-cosmic/HomeCosmicScene.tsx"],
      },
      "src/pages/home-cosmic/HomeCosmicScene.tsx": {
        file: "assets/home-cosmic-scene.js",
        dynamicImports: [
          "src/pages/home-cosmic/homeCosmicRenderer.ts",
        ],
      },
      "src/pages/home-cosmic/homeCosmicRenderer.ts": {
        file: "assets/home-cosmic-renderer.js",
        imports: ["_vendor-three.js"],
      },
      "_vendor-three.js": {
        file: "assets/vendor-three.js",
      },
    }));

    const output = execFileSync(process.execPath, [
      analyzerPath,
      "--manifest",
      manifestPath,
      "--entry",
      "src/pages/HomePage.tsx",
      "--static-only",
      "--json",
    ], { encoding: "utf8" });

    expect(JSON.parse(output)).toMatchObject({
      modules: [
        "src/pages/HomePage.tsx",
        "src/pages/home-cosmic/HomeCosmicScene.tsx",
      ],
    });
  });
});
