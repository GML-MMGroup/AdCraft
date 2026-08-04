import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { WorkflowAutosaveSnapshot } from "../workflowAutosave.ts";
import { isSnapshotCompatibleWithWorkflow, LOCAL_WORKFLOW_ID } from "./workflowSnapshotModel.ts";

const retiredDemoSnapshot = {
  workflowId: LOCAL_WORKFLOW_ID,
  nodes: [
    { id: "prompt", type: "text", title: "Prompt" },
    { id: "image-set", type: "image_generation", title: "Image Set" },
    { id: "video-preview", type: "preview", title: "Video Preview" },
  ],
  flowNodes: [],
  edges: [
    { id: "prompt-image-set", source: "prompt", target: "image-set" },
    { id: "image-set-video-preview", source: "image-set", target: "video-preview" },
  ],
  savedAt: "2026-07-27T00:00:00.000Z",
} as unknown as WorkflowAutosaveSnapshot;

describe("workflow snapshot compatibility", () => {
  it("does not restore the retired default demo graph as a local draft", () => {
    expect(isSnapshotCompatibleWithWorkflow(retiredDemoSnapshot, null)).toBe(false);
  });

  it("continues to restore a user-created local draft", () => {
    const userDraft = {
      ...retiredDemoSnapshot,
      nodes: [{ id: "custom-node", type: "text", title: "Custom node" }],
      edges: [],
    } as WorkflowAutosaveSnapshot;

    expect(isSnapshotCompatibleWithWorkflow(userDraft, null)).toBe(true);
  });

  it("does not keep the retired demo graph in active workflow code", () => {
    const activeWorkflowFiles = [
      "workflowPageDefaults.ts",
      "useWorkflowPageLifecycle.ts",
      "useWorkflowPageModel.tsx",
      "useWorkflowPageRunGraphControllers.ts",
      "workflowPageContracts.ts",
      "../graph/workflowGraphMutationControllerTypes.ts",
    ];

    for (const file of activeWorkflowFiles) {
      const source = readFileSync(resolve(process.cwd(), "src/features/workflow/page", file), "utf8");
      expect(source).not.toMatch(/\bdemo(?:Nodes|Edges)\b/);
      expect(source).not.toContain("shouldUseDemo");
    }
  });
});
