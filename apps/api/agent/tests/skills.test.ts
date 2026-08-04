import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { getOperationDescriptor } from "../src/registry.js";
import { loadRequiredSkills, verifySkillBundle } from "../src/skills.js";

const skillRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../skills",
);

describe("trusted skill bundle", () => {
  it("loads only manifest-pinned skill markdown with verified digests", async () => {
    const descriptor = getOperationDescriptor(
      "character_designer",
      "materialize_draft",
    );
    const skills = await loadRequiredSkills(descriptor, [
      "reference_asset_selection",
    ]);

    expect(skills.map((skill) => skill.skill_id)).toContain("character_prompt_expansion");
    expect(skills.map((skill) => skill.skill_id)).toContain("reference_asset_selection");
    expect(skills.map((skill) => skill.skill_id)).not.toContain(
      "scene_spec_extraction",
    );
    expect(skills.every((skill) => skill.content.length > 0)).toBe(true);
    expect(skills.every((skill) => /^[a-f0-9]{64}$/.test(skill.sha256))).toBe(true);
  });

  it("rejects optional skills that are not declared by the operation", async () => {
    const descriptor = getOperationDescriptor(
      "character_designer",
      "materialize_draft",
    );

    await expect(
      loadRequiredSkills(descriptor, ["scene_spec_extraction"]),
    ).rejects.toThrow("agent_optional_skill_not_allowed");
  });

  it("fails closed for missing required skills and context overflow", async () => {
    const descriptor = getOperationDescriptor(
      "character_designer",
      "materialize_draft",
    );
    await expect(
      loadRequiredSkills({
        ...descriptor,
        required_skills: ["missing_skill"],
      }),
    ).rejects.toThrow("agent_required_skill_missing");
    await expect(
      loadRequiredSkills({
        ...descriptor,
        max_skill_context_bytes: 1,
      }),
    ).rejects.toThrow("agent_skill_context_budget_exceeded");
  });

  it("verifies every manifest entry and rejects a one-byte mutation", async () => {
    const verified = await verifySkillBundle();
    expect(verified.skills.size).toBe(21);

    const temporaryRoot = await mkdtemp(join(tmpdir(), "adcraft-skills-"));
    await cp(skillRoot, temporaryRoot, { recursive: true });
    const target = join(
      temporaryRoot,
      "character_prompt_expansion",
      "SKILL.md",
    );
    const content = await readFile(target, "utf8");
    await writeFile(
      target,
      content.replace(
        "Make character descriptions",
        "Alter character descriptions",
      ),
      "utf8",
    );

    await expect(verifySkillBundle(temporaryRoot)).rejects.toThrow(
      "agent_skill_digest_mismatch",
    );
  });

  it("normalizes line endings and trailing newlines before digest verification", async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "adcraft-skills-canonical-"));
    const skillDirectory = join(temporaryRoot, "canonical_skill");
    await mkdir(skillDirectory, { recursive: true });
    const canonical = "# Canonical Skill\n\nUse bounded context.\n";
    await writeFile(
      join(skillDirectory, "SKILL.md"),
      "# Canonical Skill\r\n\r\nUse bounded context.\r\n\r\n",
      "utf8",
    );
    await writeFile(
      join(temporaryRoot, "manifest.json"),
      JSON.stringify({
        version: "1",
        skills: [
          {
            skill_id: "canonical_skill",
            path: "canonical_skill/SKILL.md",
            sha256: createHash("sha256").update(canonical, "utf8").digest("hex"),
          },
        ],
      }),
      "utf8",
    );

    const verified = await verifySkillBundle(temporaryRoot);

    expect(verified.skills.get("canonical_skill")?.content).toBe(canonical);
  });
});
