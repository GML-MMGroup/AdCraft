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
  test("keeps advanced shot timeline code out of the default composition editor chunk", () => {
    const editorSource = readFileSync(
      join(process.cwd(), "src/features/workflow/final-composition/V2FinalCompositionEditor.tsx"),
      "utf8",
    );
    const timelineSource = readFileSync(
      join(process.cwd(), "src/features/workflow/final-composition/V2ShotTimeline.tsx"),
      "utf8",
    );
    const budgetSource = readFileSync(budgetScriptPath, "utf8");

    expect(editorSource).not.toContain(
      'import "@xzdarcy/react-timeline-editor/dist/react-timeline-editor.css"',
    );
    expect(editorSource).not.toMatch(/from "\.\/V2ShotTimeline\.tsx"/);
    expect(editorSource).toContain('import("./V2ShotTimeline.tsx")');
    expect(timelineSource).toContain(
      'import "@xzdarcy/react-timeline-editor/dist/react-timeline-editor.css"',
    );
    expect(budgetSource).toContain("MAX_SHOT_TIMELINE_JS_BYTES");
    expect(budgetSource).toContain('asset.name.startsWith("V2ShotTimeline-")');
  });

  test("budgets the dark Home cosmic renderer as a lazy feature", () => {
    const viteSource = readFileSync(
      join(process.cwd(), "vite.config.ts"),
      "utf8",
    );
    const budgetSource = readFileSync(budgetScriptPath, "utf8");

    expect(viteSource).toContain('return "vendor-three"');
    expect(budgetSource).toContain(
      "MAX_HOME_COSMIC_RENDERER_JS_BYTES",
    );
    expect(budgetSource).toContain(
      'asset.name.startsWith("homeCosmicRenderer-")',
    );
    expect(budgetSource).toContain(
      'asset.name.startsWith("vendor-three-")',
    );
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

  test("rejects a production-shaped final composition entry without the shot timeline dynamic import", () => {
    const distDirectory = mkdtempSync(join(tmpdir(), "adcraft-build-budget-"));
    temporaryDirectories.push(distDirectory);
    const assetsDirectory = join(distDirectory, "assets");
    const manifestDirectory = join(distDirectory, ".vite");
    mkdirSync(assetsDirectory);
    mkdirSync(manifestDirectory);

    for (const asset of [
      "index-fixture.js",
      "home-fixture.js",
      "screenplay-editor-fixture.js",
      "V2FinalCompositionEditor-fixture.js",
      "V2ShotTimeline-fixture.js",
      "timeline-editor-fixture.js",
      "AssetEntityViewer-fixture.js",
      "global-fixture.css",
      "home-fixture.css",
      "timeline-editor-fixture.css",
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
      "_V2FinalCompositionEditor-fixture.js": {
        name: "V2FinalCompositionEditor",
        file: "assets/V2FinalCompositionEditor-fixture.js",
      },
      "src/features/workflow/final-composition/V2ShotTimeline.tsx": {
        name: "V2ShotTimeline",
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
    expect(result.stderr).toContain(
      "final composition editor must dynamically import the advanced shot timeline",
    );
  });
});
