import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { OperationDescriptor } from "./registry.js";

interface ManifestEntry {
  readonly skill_id: string;
  readonly path: string;
  readonly sha256: string;
}

interface SkillManifest {
  readonly version: "1";
  readonly skills: ReadonlyArray<ManifestEntry>;
}

export interface LoadedSkill {
  readonly skill_id: string;
  readonly version: "1";
  readonly sha256: string;
  readonly content: string;
}

const bundleRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../skills");

export async function loadRequiredSkills(
  descriptor: OperationDescriptor,
  selectedOptionalIds: ReadonlyArray<string> = [],
): Promise<ReadonlyArray<LoadedSkill>> {
  const optional = new Set(descriptor.optional_skills);
  if (selectedOptionalIds.some((skillId) => !optional.has(skillId))) {
    throw new Error("agent_optional_skill_not_allowed");
  }
  const selectedIds = [
    ...descriptor.required_skills,
    ...selectedOptionalIds.filter(
      (skillId) => !descriptor.required_skills.includes(skillId),
    ),
  ];
  const manifest = await readManifest();
  const entries = new Map(manifest.skills.map((entry) => [entry.skill_id, entry]));
  const skills = await Promise.all(
    selectedIds.map(async (skillId) => {
      const entry = entries.get(skillId);
      if (!entry) throw new Error("agent_required_skill_missing");
      if (!/^[a-z0-9_]+\/SKILL\.md$/.test(entry.path)) {
        throw new Error("agent_skill_path_invalid");
      }
      const path = resolve(bundleRoot, entry.path);
      if (!path.startsWith(`${bundleRoot}/`)) throw new Error("agent_skill_path_invalid");
      const bytes = await readFile(path);
      const digest = createHash("sha256").update(bytes).digest("hex");
      if (digest !== entry.sha256) throw new Error("agent_skill_digest_mismatch");
      return {
        skill_id: entry.skill_id,
        version: manifest.version,
        sha256: digest,
        content: bytes.toString("utf-8"),
      };
    }),
  );
  const contextBytes = skills.reduce(
    (total, skill) => total + Buffer.byteLength(skill.content),
    0,
  );
  if (contextBytes > descriptor.max_skill_context_bytes) {
    throw new Error("agent_skill_context_budget_exceeded");
  }
  return skills;
}

async function readManifest(): Promise<SkillManifest> {
  const bytes = await readFile(resolve(bundleRoot, "manifest.json"));
  const value: unknown = JSON.parse(bytes.toString("utf-8"));
  if (
    !value ||
    typeof value !== "object" ||
    (value as { version?: unknown }).version !== "1" ||
    !Array.isArray((value as { skills?: unknown }).skills)
  ) {
    throw new Error("agent_skill_manifest_invalid");
  }
  return value as SkillManifest;
}
