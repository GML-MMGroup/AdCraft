import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = resolve(process.cwd(), "src");

function source(path: string) {
  return readFileSync(resolve(sourceRoot, path), "utf8");
}

describe("route-scoped styles", () => {
  it("loads only shared primitives from the application entry", () => {
    expect(source("main.tsx")).toContain('import "./styles/base.css"');
    expect(source("main.tsx")).not.toContain('import "./styles.css"');
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
    expect(source("pages/AssetsPage.tsx")).toContain('import "./assets.css"');
    expect(source("pages/WorkflowPage.tsx")).toContain(
      'import "../features/workflow/workflow.css"',
    );
  });
});
