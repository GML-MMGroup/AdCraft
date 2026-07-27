import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const pageRoot = resolve(process.cwd(), "src/features/workflow/page");
const contractBoundaries = [
  "workflowPageContracts.ts",
  "useWorkflowPageRuntimeControllers.ts",
  "useWorkflowPageRunGraphControllers.ts",
  "useWorkflowPageAssetActionControllers.ts",
  "useWorkflowPageSurfaceAssembly.tsx",
  "workflowPageSurfaceBuilders.ts",
  "WorkflowPageFloatingEditors.tsx",
  "WorkflowPageOverlays.tsx",
];

describe("workflow page contracts", () => {
  it("does not allow transitional any-valued bags at active page boundaries", () => {
    for (const file of contractBoundaries) {
      const source = readFileSync(resolve(pageRoot, file), "utf8");
      expect(source).not.toContain("Record<string, any>");
      expect(source).not.toContain("@typescript-eslint/no-explicit-any");
      expect(source).not.toMatch(/\bany\b/);
    }
  });

  it("does not pass whole workflow state and action controllers into boundary hooks", () => {
    const source = readFileSync(resolve(pageRoot, "useWorkflowPageModel.tsx"), "utf8");
    expect(source).not.toMatch(/\.\.\.workflow(?:Ui|Runtime|Canvas|PromptPanel|AssetUi|AssetOperations|Conversation)\.(?:state|actions)/);
    expect(source).not.toMatch(/\.\.\.(?:canvasHistoryController|dynamicItemDrafts|finalCompositionPage)\.(?:state|actions)/);
  });
});
