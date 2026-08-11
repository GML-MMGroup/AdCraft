import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";

import type {
  AgentProviderConformanceInputV1,
  AgentRunRequest,
} from "./generated/agent-runtime.js";

const schemaPath = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "generated/agent-runtime.schema.json",
);
const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
  readonly $defs: Record<string, unknown>;
};
const ajv = new Ajv2020({
  allErrors: true,
  discriminator: true,
  strict: true,
  validateFormats: false,
});
const validate: ValidateFunction<AgentRunRequest> = ajv.compile({
  $ref: "#/$defs/AgentRunRequest",
  $defs: withoutDiscriminatorAnnotations(schema.$defs),
});
const validateConformanceInput: ValidateFunction<AgentProviderConformanceInputV1> =
  ajv.compile({
    $ref: "#/$defs/AgentProviderConformanceInputV1",
    $defs: withoutDiscriminatorAnnotations(schema.$defs),
  });

export function validateAgentRunRequest(value: unknown): AgentRunRequest {
  if (!validate(value)) throw new Error("agent_protocol_mismatch");
  return value;
}

export function validateAgentProviderConformanceInput(
  value: unknown,
): AgentProviderConformanceInputV1 {
  if (!validateConformanceInput(value)) throw new Error("conformance_parity_failed");
  return value;
}

function withoutDiscriminatorAnnotations(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutDiscriminatorAnnotations);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => key !== "discriminator")
        .map(([key, child]) => [key, withoutDiscriminatorAnnotations(child)]),
    );
  }
  return value;
}
