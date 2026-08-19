import { describe, expect, it } from "vitest";

import manifest from "./agent-canvas-contract-manifest.json" with { type: "json" };
import { agentCanvasContractMismatches } from "./check-agent-canvas-backend-contract.mjs";

function openApi() {
  const schemas = Object.fromEntries(Object.entries(manifest.schemas).map(([name, contract]) => [
    name,
    {
      properties: Object.fromEntries(contract.properties.map((property) => [
        property,
        contract.enums[property]
          ? { anyOf: [{ type: "string", enum: [...contract.enums[property]] }, { type: "null" }] }
          : { type: "string" },
      ])),
    },
  ]));
  return { components: { schemas } };
}

describe("Agent Canvas backend contract parity", () => {
  it("accepts the tracked canonical response fields and enum values", () => {
    expect(agentCanvasContractMismatches(openApi(), manifest)).toEqual([]);
  });

  it("reports backend fields and enum values that the strict frontend contract has not consumed", () => {
    const backend = openApi();
    backend.components.schemas.ChatTurnV2.properties.new_backend_field = { type: "string" };
    backend.components.schemas.ChatTurnV2.properties.turn_kind.anyOf[0].enum.push("new_turn_kind");

    expect(agentCanvasContractMismatches(backend, manifest)).toEqual([
      "ChatTurnV2 properties differ: backend-only [new_backend_field]; frontend-only []",
      "ChatTurnV2.turn_kind enum differs: backend-only [new_turn_kind]; frontend-only []",
    ]);
  });
});
