import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
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
});
