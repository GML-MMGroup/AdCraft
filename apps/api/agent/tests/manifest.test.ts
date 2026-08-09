import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildRuntimeManifest,
  generateRuntimeManifest,
} from "../scripts/generate-runtime-manifest.js";
import { AGENT_CAPABILITY_CONTRACT } from "../src/generated/agent-capabilities.js";

const inputs = {
  runtimeVersion: "1.0.0",
  protocolVersion: "1" as const,
  contract: { title: "AgentRunRequest", type: "object" },
  capabilities: AGENT_CAPABILITY_CONTRACT,
  prompts: [
    { prompt_id: "prompt.b", prompt_version: "1", prompt_digest: "b".repeat(64) },
    { prompt_id: "prompt.a", prompt_version: "1", prompt_digest: "a".repeat(64) },
  ],
  skills: [
    {
      skill_id: "skill_b",
      version: "1",
      path: "skill_b/SKILL.md",
      sha256: "d".repeat(64),
    },
    {
      skill_id: "skill_a",
      version: "1",
      path: "skill_a/SKILL.md",
      sha256: "c".repeat(64),
    },
  ],
};

describe("runtime manifest", () => {
  it("is deterministic and changes for contract, prompt, and skill drift", () => {
    const first = buildRuntimeManifest(inputs);
    const reordered = buildRuntimeManifest({
      ...inputs,
      prompts: [...inputs.prompts].reverse(),
      skills: [...inputs.skills].reverse(),
      capabilities: {
        ...inputs.capabilities,
        agents: [...inputs.capabilities.agents]
          .reverse()
          .map((agent) => ({ ...agent, operations: [...agent.operations].reverse() })),
      },
    });

    expect(reordered).toEqual(first);
    expect(first).not.toHaveProperty("generated_at");
    expect(
      buildRuntimeManifest({
        ...inputs,
        capabilities: {
          ...inputs.capabilities,
          agents: inputs.capabilities.agents.map((agent) =>
            agent.name === "video_agent"
              ? { ...agent, operations: [...agent.operations, "new_operation"] }
              : agent,
          ),
        },
      }).capability_digest,
    ).not.toBe(first.capability_digest);
    expect(
      buildRuntimeManifest({ ...inputs, contract: { ...inputs.contract, minimum: 1 } })
        .contract_digest,
    ).not.toBe(first.contract_digest);
    expect(
      buildRuntimeManifest({
        ...inputs,
        prompts: [{ ...inputs.prompts[0]!, prompt_version: "2" }],
      }).prompt_digest,
    ).not.toBe(first.prompt_digest);
    expect(
      buildRuntimeManifest({
        ...inputs,
        skills: [{ ...inputs.skills[0]!, sha256: "e".repeat(64) }],
      }).skill_digest,
    ).not.toBe(first.skill_digest);
  });

  it("writes byte-identical portable JSON", async () => {
    const directory = await mkdtemp(join(tmpdir(), "adcraft-runtime-manifest-"));
    const first = join(directory, "first.json");
    const second = join(directory, "second.json");
    await writeFile(join(directory, "schema.json"), JSON.stringify(inputs.contract));
    await writeFile(
      join(directory, "capabilities.json"),
      JSON.stringify(inputs.capabilities),
    );
    await writeFile(
      join(directory, "skills.json"),
      JSON.stringify({ version: "1", skills: inputs.skills }),
    );

    await generateRuntimeManifest({
      outputPath: first,
      schemaPath: join(directory, "schema.json"),
      capabilityPath: join(directory, "capabilities.json"),
      skillManifestPath: join(directory, "skills.json"),
      runtimeVersion: inputs.runtimeVersion,
      prompts: inputs.prompts,
    });
    await generateRuntimeManifest({
      outputPath: second,
      schemaPath: join(directory, "schema.json"),
      capabilityPath: join(directory, "capabilities.json"),
      skillManifestPath: join(directory, "skills.json"),
      runtimeVersion: inputs.runtimeVersion,
      prompts: [...inputs.prompts].reverse(),
    });

    const firstBytes = await readFile(first);
    expect(await readFile(second)).toEqual(firstBytes);
    expect(firstBytes.toString("utf8")).not.toContain(directory);
    expect(firstBytes.toString("utf8").endsWith("\n")).toBe(true);
  });
});
