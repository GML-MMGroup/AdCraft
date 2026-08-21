import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  it("tracks every backend parameter provenance origin", () => {
    const expected = {
      properties: [
        "origin",
        "source_node_id",
        "binding_id",
        "source_revision",
        "requested_value",
        "effective_value",
        "normalization_code",
      ],
      enums: {
        origin: [
          "manual",
          "node_prompt",
          "binding",
          "user_explicit",
          "structured_content",
          "guidance_default",
          "role_default",
          "provider_clamp",
        ],
      },
    };
    const backendSchema = JSON.parse(readFileSync(
      resolve(process.cwd(), "../api/agent/src/generated/agent-runtime.schema.json"),
      "utf8",
    ));

    expect(manifest.schemas.CanvasParameterProvenanceV2).toEqual(expected);
    expect(agentCanvasContractMismatches(backendSchema, {
      schemas: { CanvasParameterProvenanceV2: expected },
    })).toEqual([]);
  });
});
