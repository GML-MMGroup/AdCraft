import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import {
  getPromptDescriptor,
  listPromptDescriptors,
} from "../src/prompts/registry.js";
import { getAgentDefinition } from "../src/registry.js";

const expectedPlanningOperations = [
  ["front_desk", "workflow_creation", "FrontDeskIntentOutput"],
  ["front_desk", "intent_contract_planner", "V2IntentPlan"],
  ["front_desk", "workflow_conversation", "WorkflowConversationReply"],
  ["front_desk", "conversation_summary", "ConversationSummaryResult"],
  ["script_writer", "script_writer", "V2ScriptPlanV2"],
  ["product_designer", "product_expert_brief", "V2ProductExpertPlan"],
  ["character_designer", "character_expert_brief", "V2CharacterExpertPlan"],
  ["scene_designer", "scene_expert_brief", "V2SceneExpertPlan"],
  ["bgm_director", "bgm_expert_brief", "V2BgmExpertPlan"],
  ["product_designer", "product_prompt", "V2ProductMainPromptPlan"],
  ["product_designer", "product_prompt", "V2ProductMultiViewPromptPlan"],
  ["character_designer", "character_prompt", "V2CharacterMainPromptPlan"],
  ["character_designer", "character_prompt", "V2CharacterThreeViewPromptPlan"],
  ["character_designer", "targeted_revision", "SpecialistResult"],
  ["scene_designer", "scene_prompt", "V2SceneMainPromptPlan"],
  ["scene_designer", "scene_prompt", "V2SceneMultiViewPromptPlan"],
  ["scene_designer", "targeted_revision", "SpecialistResult"],
  ["storyboard_artist", "storyboard_detail", "V2StoryboardDetailPlan"],
  ["storyboard_artist", "storyboard_prompt", "V2ShotCellPromptPlan"],
  ["video_director", "shot_video_prompt", "V2ShotVideoPromptPlan"],
  ["bgm_director", "bgm_prompt", "V2BgmPromptPlan"],
  ["quick_media_agent", "free_image", "V2QuickMediaPromptPlan"],
  ["quick_media_agent", "free_video", "V2QuickMediaPromptPlan"],
  ["quick_media_agent", "free_audio", "V2QuickMediaPromptPlan"],
] as const;

describe("versioned planning prompt registry", () => {
  it("registers every planning operation exactly once under its real owner", () => {
    const descriptors = listPromptDescriptors();
    const keys = descriptors.map(
      ({ agent_name, operation, contract_name }) =>
        `${agent_name}:${operation}:${contract_name}`,
    );

    expect(new Set(keys).size).toBe(keys.length);
    expect(
      descriptors.map(({ agent_name, operation, contract_name }) => [
        agent_name,
        operation,
        contract_name,
      ]),
    ).toEqual(expectedPlanningOperations);
    for (const [agentName, operation, contractName] of expectedPlanningOperations) {
      const descriptor = getPromptDescriptor(agentName, operation, contractName);
      expect(getAgentDefinition(agentName).operations).toContain(operation);
      expect(descriptor.agent_name).toBe(agentName);
      expect(descriptor.contract_name).toBe(contractName);
    }
    expect(getAgentDefinition("front_desk").operations).not.toContain(
      "expert_brief_planner",
    );
  });

  it("computes stable digests from complete English operation prompts", () => {
    for (const descriptor of listPromptDescriptors()) {
      expect(descriptor.prompt_id).toMatch(/^adcraft\.[a-z_.]+\.v1$/);
      expect(descriptor.prompt_version).toBe("1");
      expect(descriptor.system_prompt.length).toBeGreaterThan(300);
      expect(descriptor.system_prompt).toContain("submit_structured_result");
      expect(descriptor.system_prompt).toContain(descriptor.contract_name);
      expect(descriptor.system_prompt).not.toMatch(/[^\x00-\x7F]/);
      expect(descriptor.prompt_digest).toBe(
        createHash("sha256")
          .update(descriptor.system_prompt, "utf8")
          .digest("hex"),
      );
    }
  });

  it("keeps exact-target revisions cognition-only", () => {
    for (const agentName of ["character_designer", "scene_designer"] as const) {
      const descriptor = getPromptDescriptor(
        agentName,
        "targeted_revision",
        "SpecialistResult",
      );

      expect(descriptor.system_prompt).toContain("exact target is already resolved");
      expect(descriptor.system_prompt).toContain(
        "Do not call mutation or generation tools",
      );
    }
  });

  it("rejects unknown or contract-mismatched planning descriptors", () => {
    expect(() =>
      getPromptDescriptor(
        "front_desk",
        "workflow_creation",
        "WrongContract",
      ),
    ).toThrow("agent_prompt_contract_mismatch");
    expect(() =>
      getPromptDescriptor("front_desk", "missing_operation", "Missing"),
    ).toThrow("agent_prompt_not_found");
  });
});
