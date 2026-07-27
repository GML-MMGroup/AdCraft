import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { AgentRunRequest } from "./generated/agent-runtime.js";

type AgentName = AgentRunRequest["agent_name"];

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
  readonly sha256: string;
  readonly content: string;
}

const bundleRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../skills");
const allowlists: Readonly<Record<AgentName, ReadonlyArray<string>>> = {
  front_desk: ["audience_analysis", "campaign_appeal_generation", "product_info_extraction"],
  script_writer: ["short_ad_script_structure", "dialogue_copy_generation"],
  product_designer: [
    "product_info_extraction",
    "selling_point_extraction",
    "reference_asset_selection",
  ],
  character_designer: [
    "character_spec_extraction",
    "character_prompt_expansion",
    "character_turnaround_prompt",
    "reference_asset_selection",
  ],
  scene_designer: [
    "scene_spec_extraction",
    "pure_scene_prompt_expansion",
    "multi_view_scene_prompt",
    "reference_asset_selection",
  ],
  storyboard_artist: [
    "storyboard_beat_extraction",
    "storyboard_image_prompt_generation",
    "visual_continuity_check",
    "reference_asset_selection",
  ],
  video_director: [
    "storyboard_video_prompt_generation",
    "segment_generation_planning",
    "visual_continuity_check",
    "reference_asset_selection",
  ],
  bgm_director: ["bgm_prompt_generation", "mood_and_duration_matching"],
  quick_media_agent: ["creative_idea_generation", "reference_asset_selection"],
};

export function skillIdsForAgent(
  agentName: AgentName,
  semanticFamily: string,
): ReadonlyArray<string> {
  if (semanticFamily === "final_composition") {
    throw new Error("agent_skill_operation_not_allowed");
  }
  if (
    agentName === "storyboard_artist" &&
    !/^shot_cell_[1-4]$/.test(semanticFamily) &&
    semanticFamily !== "storyboard_prompt"
  ) {
    throw new Error("agent_skill_operation_not_allowed");
  }
  return allowlists[agentName];
}

export async function loadRequiredSkills(
  agentName: AgentName,
  semanticFamily: string,
): Promise<ReadonlyArray<LoadedSkill>> {
  const manifest = await readManifest();
  const entries = new Map(manifest.skills.map((entry) => [entry.skill_id, entry]));
  return Promise.all(
    skillIdsForAgent(agentName, semanticFamily).map(async (skillId) => {
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
        sha256: digest,
        content: bytes.toString("utf-8"),
      };
    }),
  );
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
