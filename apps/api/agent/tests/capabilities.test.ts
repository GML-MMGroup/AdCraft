import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { canonicalizeAgentCapabilities } from "../scripts/generate-agent-capabilities.js";
import { AGENT_CAPABILITY_CONTRACT } from "../src/generated/agent-capabilities.js";
import { listAgentDefinitions } from "../src/registry.js";

async function sourceContract(): Promise<unknown> {
  return JSON.parse(
    await readFile(resolve("contracts/agent-capabilities.json"), "utf8"),
  );
}

describe("generated Video Agent capability contract", () => {
  it("matches the canonical JSON contract", async () => {
    expect(AGENT_CAPABILITY_CONTRACT).toEqual(
      canonicalizeAgentCapabilities(await sourceContract()),
    );
  });

  it("declares one Agent, one model role, and 57 unique operations", () => {
    expect(AGENT_CAPABILITY_CONTRACT.agents).toHaveLength(1);
    const agent = AGENT_CAPABILITY_CONTRACT.agents[0];

    expect(agent).toMatchObject({ name: "video_agent", model_role: "agent" });
    expect(agent.operations).toHaveLength(57);
    expect(new Set(agent.operations).size).toBe(57);
    expect(listAgentDefinitions().map(({ name }) => name)).toEqual(["video_agent"]);
  });

  it("contains no retired operation", () => {
    const operations = AGENT_CAPABILITY_CONTRACT.agents[0].operations;

    for (const retired of [
      "resolve_creation_mode",
      "conversation_turn",
      "decide_next_guidance_step",
      "proposal_action",
      "direct_response",
      "propose_concepts",
      "revise_concepts",
      "materialize_draft",
      "targeted_revision",
    ]) {
      expect(operations).not.toContain(retired);
    }
  });

  it("rejects duplicate names, operations, and retired identities", () => {
    expect(() =>
      canonicalizeAgentCapabilities({
        contract_version: "1",
        agents: [
          { name: "video_agent", operations: ["free_image"], model_role: "agent" },
          { name: "video_agent", operations: ["free_video"], model_role: "agent" },
        ],
      }),
    ).toThrow("agent_capability_contract_invalid");
    expect(() =>
      canonicalizeAgentCapabilities({
        contract_version: "1",
        agents: [
          {
            name: "video_agent",
            operations: ["free_image", "free_image"],
            model_role: "agent",
          },
        ],
      }),
    ).toThrow("agent_capability_contract_invalid");
    expect(() =>
      canonicalizeAgentCapabilities({
        contract_version: "1",
        agents: [
          { name: "director", operations: ["free_image"], model_role: "agent" },
        ],
      }),
    ).toThrow("agent_capability_contract_invalid");
  });
});
