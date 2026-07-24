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
        dynamicImports: ["src/features/home/HomeWorkspace.tsx"],
      },
      "src/features/home/HomeWorkspace.tsx": {
        file: "assets/home-workspace.js",
        isDynamicEntry: true,
        dynamicImports: ["src/features/workflow/WorkflowPage.tsx"],
      },
      "src/features/workflow/WorkflowPage.tsx": {
        file: "assets/workflow.js",
        isDynamicEntry: true,
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
    });
  });
});
