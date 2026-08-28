import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import manifest from "./agent-canvas-contract-manifest.json" with { type: "json" };

function sorted(values) {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function difference(left, right) {
  const rightValues = new Set(right);
  return sorted(left.filter((value) => !rightValues.has(value)));
}

function resolveReference(root, reference) {
  if (typeof reference !== "string" || !reference.startsWith("#/")) return null;
  return reference.slice(2).split("/").reduce((value, segment) => {
    if (!value || typeof value !== "object") return null;
    return value[segment.replaceAll("~1", "/").replaceAll("~0", "~")];
  }, root);
}

function enumValues(schema, root = schema, seen = new Set()) {
  if (!schema || typeof schema !== "object") return [];
  if (typeof schema.$ref === "string") {
    if (seen.has(schema.$ref)) return [];
    const resolved = resolveReference(root, schema.$ref);
    if (!resolved) return [];
    const nextSeen = new Set(seen);
    nextSeen.add(schema.$ref);
    return enumValues(resolved, root, nextSeen);
  }
  if (typeof schema.const === "string") return [schema.const];
  if (Array.isArray(schema.enum)) return schema.enum.filter((value) => typeof value === "string");
  if (Array.isArray(schema.anyOf)) return schema.anyOf.flatMap((member) => enumValues(member, root, seen));
  if (Array.isArray(schema.oneOf)) return schema.oneOf.flatMap((member) => enumValues(member, root, seen));
  if (Array.isArray(schema.allOf)) return schema.allOf.flatMap((member) => enumValues(member, root, seen));
  return [];
}

export function agentCanvasContractMismatches(openApi, contractManifest = manifest) {
  const schemas = openApi?.components?.schemas ?? openApi?.$defs;
  if (!schemas || typeof schemas !== "object") {
    return ["OpenAPI components.schemas and JSON Schema $defs are unavailable"];
  }

  const mismatches = [];
  Object.entries(contractManifest.schemas).forEach(([schemaName, expected]) => {
    const actual = schemas[schemaName];
    if (!actual || typeof actual !== "object") {
      mismatches.push(`${schemaName} is missing from backend OpenAPI`);
      return;
    }
    const actualProperties = Object.keys(actual.properties ?? {});
    const backendOnly = difference(actualProperties, expected.properties);
    const frontendOnly = difference(expected.properties, actualProperties);
    if (backendOnly.length || frontendOnly.length) {
      mismatches.push(
        `${schemaName} properties differ: backend-only [${backendOnly.join(", ")}]; frontend-only [${frontendOnly.join(", ")}]`,
      );
    }

    Object.entries(expected.enums ?? {}).forEach(([property, expectedValues]) => {
      const actualValues = enumValues(actual.properties?.[property], openApi);
      const backendEnumOnly = difference(actualValues, expectedValues);
      const frontendEnumOnly = difference(expectedValues, actualValues);
      if (backendEnumOnly.length || frontendEnumOnly.length) {
        mismatches.push(
          `${schemaName}.${property} enum differs: backend-only [${backendEnumOnly.join(", ")}]; frontend-only [${frontendEnumOnly.join(", ")}]`,
        );
      }
    });
  });
  return mismatches;
}

async function loadOpenApi(source) {
  if (/^https?:\/\//u.test(source)) {
    const response = await fetch(source);
    if (!response.ok) throw new Error(`OpenAPI request failed with HTTP ${response.status}`);
    return response.json();
  }
  return JSON.parse(await readFile(source, "utf8"));
}

async function main() {
  const source = process.argv[2] ?? process.env.ADWORKFLOW_OPENAPI;
  if (!source) {
    throw new Error(
      "Provide an OpenAPI JSON file or URL: npm run check:agent-canvas-contract -- <source>",
    );
  }
  const mismatches = agentCanvasContractMismatches(await loadOpenApi(source));
  if (mismatches.length) throw new Error(mismatches.join("\n"));
  process.stdout.write("Agent Canvas frontend contract matches the tracked backend schemas.\n");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
