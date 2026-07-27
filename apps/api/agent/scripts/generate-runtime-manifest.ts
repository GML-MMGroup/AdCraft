import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { listPromptDescriptors } from "../src/prompts/registry.js";

interface PromptIdentity {
  readonly prompt_id: string;
  readonly prompt_version: string;
  readonly prompt_digest: string;
}

interface SkillIdentity {
  readonly skill_id: string;
  readonly version: string;
  readonly path: string;
  readonly sha256: string;
}

interface RuntimeManifestInputs {
  readonly runtimeVersion: string;
  readonly protocolVersion: "1";
  readonly contract: unknown;
  readonly prompts: ReadonlyArray<PromptIdentity>;
  readonly skills: ReadonlyArray<SkillIdentity>;
}

interface GenerateRuntimeManifestOptions {
  readonly outputPath: string;
  readonly schemaPath: string;
  readonly skillManifestPath: string;
  readonly runtimeVersion: string;
  readonly prompts?: ReadonlyArray<PromptIdentity>;
}

export interface PiRuntimeManifest {
  readonly runtime_version: string;
  readonly protocol_version: "1";
  readonly contract_digest: string;
  readonly prompt_digest: string;
  readonly skill_digest: string;
}

export function buildRuntimeManifest(inputs: RuntimeManifestInputs): PiRuntimeManifest {
  return {
    runtime_version: inputs.runtimeVersion,
    protocol_version: inputs.protocolVersion,
    contract_digest: digest(inputs.contract),
    prompt_digest: digest(
      [...inputs.prompts].sort((left, right) => left.prompt_id.localeCompare(right.prompt_id)),
    ),
    skill_digest: digest(
      [...inputs.skills].sort((left, right) => left.skill_id.localeCompare(right.skill_id)),
    ),
  };
}

export async function generateRuntimeManifest(
  options: GenerateRuntimeManifestOptions,
): Promise<PiRuntimeManifest> {
  const contract: unknown = JSON.parse(await readFile(options.schemaPath, "utf8"));
  const skillManifest = JSON.parse(
    await readFile(options.skillManifestPath, "utf8"),
  ) as {
    readonly version?: string;
    readonly skills?: ReadonlyArray<Omit<SkillIdentity, "version">>;
  };
  if (!skillManifest.version || !Array.isArray(skillManifest.skills)) {
    throw new Error("agent_skill_manifest_invalid");
  }
  const manifest = buildRuntimeManifest({
    runtimeVersion: options.runtimeVersion,
    protocolVersion: "1",
    contract,
    prompts: options.prompts ?? listPromptDescriptors(),
    skills: skillManifest.skills.map((skill) => ({
      ...skill,
      version: skillManifest.version as string,
    })),
  });
  await writeFile(options.outputPath, `${canonicalJson(manifest)}\n`, "utf8");
  return manifest;
}

function digest(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, stableValue(child)]),
    );
  }
  return value;
}

async function main(): Promise<void> {
  const agentRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const packageJson = JSON.parse(
    await readFile(resolve(agentRoot, "package.json"), "utf8"),
  ) as { version: string };
  await generateRuntimeManifest({
    outputPath: resolve(agentRoot, "src/generated/runtime-manifest.json"),
    schemaPath: resolve(agentRoot, "src/generated/agent-runtime.schema.json"),
    skillManifestPath: resolve(agentRoot, "skills/manifest.json"),
    runtimeVersion: packageJson.version,
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
