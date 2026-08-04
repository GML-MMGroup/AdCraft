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

describe("generated Agent capability contract", () => {
  it("matches the canonical JSON contract", async () => {
    expect(AGENT_CAPABILITY_CONTRACT).toEqual(
      canonicalizeAgentCapabilities(await sourceContract()),
    );
  });

  it("drives the runtime registry names and operations", () => {
    expect(
      listAgentDefinitions().map(({ name, operations }) => ({
        name,
        operations,
      })),
    ).toEqual(
      AGENT_CAPABILITY_CONTRACT.agents.map(({ name, operations }) => ({
        name,
        operations,
      })),
    );
  });

  it("rejects duplicate Agent names with a stable error", () => {
    expect(() =>
      canonicalizeAgentCapabilities({
        contract_version: "1",
        agents: [
          { name: "director", operations: ["conversation_turn"], model_role: "front_desk" },
          { name: "director", operations: ["proposal_action"], model_role: "front_desk" },
        ],
      }),
    ).toThrow("agent_capability_contract_invalid");
  });

  it("rejects duplicate operations with a stable error", () => {
    expect(() =>
      canonicalizeAgentCapabilities({
        contract_version: "1",
        agents: [
          {
            name: "director",
            operations: ["conversation_turn", "conversation_turn"],
            model_role: "front_desk",
          },
        ],
      }),
    ).toThrow("agent_capability_contract_invalid");
  });
});
