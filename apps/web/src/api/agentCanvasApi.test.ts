import { describe, expect, it } from "vitest";

import { agentCanvasApi } from "./agentCanvasApi.ts";

describe("agentCanvasApi", () => {
  it("does not expose the retired V2 provider capability projection", () => {
    expect("agentCanvasProviderCapabilities" in agentCanvasApi).toBe(false);
  });

  it("exposes only the public Video Style catalog and activation APIs", () => {
    expect(agentCanvasApi.listVideoSkills).toBeTypeOf("function");
    expect(agentCanvasApi.getVideoSkill).toBeTypeOf("function");
    expect(agentCanvasApi.createAgentCanvasVideoSkillRun).toBeTypeOf("function");
  });

  it("exposes the persisted creative-session read model", () => {
    expect(agentCanvasApi.agentCanvasCreativeSession).toBeTypeOf("function");
  });

  it("exposes structured production decision bundle actions", () => {
    expect(agentCanvasApi.agentCanvasDecisionBundle).toBeTypeOf("function");
    expect(agentCanvasApi.actOnAgentCanvasDecisionBundle).toBeTypeOf("function");
  });

  it("exposes Editing export download and Canvas import actions", () => {
    expect(agentCanvasApi.downloadAgentCanvasAsset).toBeTypeOf("function");
    expect(agentCanvasApi.importAgentCanvasEditingExport).toBeTypeOf("function");
  });

  it("exposes the workflow-scoped Presentation Stream client", () => {
    expect(agentCanvasApi.openAgentCanvasPresentationStream).toBeTypeOf("function");
  });
});
