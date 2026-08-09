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
  it.each([
    ["propose_world_setting_options", "video_agent_world_setting"],
    ["propose_product_options", "video_agent_product_design"],
    ["propose_prop_options", "video_agent_prop_design"],
    ["propose_character_options", "video_agent_character_design"],
    ["propose_scene_options", "video_agent_scene_design"],
    ["propose_script_options", "video_agent_script_authoring"],
    ["propose_storyboard_options", "video_agent_storyboard_design"],
    ["propose_video_options", "video_agent_video_direction"],
    ["propose_bgm_options", "video_agent_bgm_direction"],
    ["free_video", "video_agent_quick_media"],
  ])("loads only the canonical Skill for %s", async (operation, skillId) => {
    const descriptor = getOperationDescriptor(operation);
    const skills = await loadRequiredSkills(descriptor);

    expect(skills.map((skill) => skill.skill_id)).toEqual([skillId]);
    expect(skills.every((skill) => skill.content.length > 0)).toBe(true);
    expect(skills.every((skill) => /^[a-f0-9]{64}$/.test(skill.sha256))).toBe(true);
  });

  it.each([
    "decide_turn_intent",
    "decide_next_action",
    "workflow_conversation",
    "conversation_summary",
    "execute_canvas_text",
  ])("loads no creative Skill for %s", async (operation) => {
    const descriptor = getOperationDescriptor(operation);

    await expect(loadRequiredSkills(descriptor)).resolves.toEqual([]);
  });

  it("rejects arbitrary and sibling Skill selection", async () => {
    const descriptor = getOperationDescriptor("propose_character_options");

    await expect(
      loadRequiredSkills(descriptor, ["video_agent_scene_design"]),
    ).rejects.toThrow("agent_optional_skill_not_allowed");
    await expect(
      loadRequiredSkills(descriptor, ["untrusted_skill"]),
    ).rejects.toThrow("agent_optional_skill_not_allowed");
  });

  it("keeps Character materialization lean and delegates the companion to Python", async () => {
    const descriptor = getOperationDescriptor("materialize_character");
    const [skill] = await loadRequiredSkills(descriptor);

    expect(skill?.content).toContain("Return one lean identity-master design result");
    expect(skill?.content).toContain("Python derives the Turnaround companion");
    expect(skill?.content).toContain("Do not construct a two-Node payload");
    expect(skill?.content).toContain("Do not write a provider prompt");
  });

  it("fails closed for missing required skills and context overflow", async () => {
    const descriptor = getOperationDescriptor("propose_character_options");
    await expect(
      loadRequiredSkills({
        ...descriptor,
        required_skill: "missing_skill",
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
    expect(verified.skills.size).toBe(10);

    const temporaryRoot = await mkdtemp(join(tmpdir(), "adcraft-skills-"));
    await cp(skillRoot, temporaryRoot, { recursive: true });
    const target = join(
      temporaryRoot,
      "video_agent_character_design",
      "SKILL.md",
    );
    const content = await readFile(target, "utf8");
    await writeFile(
      target,
      content.replace(
        "Make character descriptions",
        "Change character descriptions",
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
