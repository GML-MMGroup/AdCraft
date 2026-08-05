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
});
