import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { videoAgentBasePolicy } from "../src/prompts/agents.js";
import {
  getPromptDescriptor,
  listPromptDescriptors,
} from "../src/prompts/registry.js";
import { listOperationDescriptors } from "../src/registry.js";

describe("Video Agent prompt registry", () => {
  it("registers one prompt for every closed operation and exact contract", () => {
    const operations = listOperationDescriptors();
    const prompts = listPromptDescriptors();

    expect(prompts).toHaveLength(48);
    expect(
      prompts.map(({ agent_name, operation, contract_name }) => ({
        agent_name,
        operation,
        contract_name,
      })),
    ).toEqual(
      operations.map(({ agent_name, operation, result_contract_name }) => ({
        agent_name,
        operation,
        contract_name: result_contract_name,
      })),
    );
    for (const operation of operations) {
      expect(
        getPromptDescriptor(operation.operation, operation.result_contract_name)
          .agent_name,
      ).toBe("video_agent");
    }
  });

  it("uses a concise non-creative base policy", () => {
    expect(videoAgentBasePolicy).toContain("AdCraft Video Agent");
    expect(videoAgentBasePolicy).toContain("current operation");
    expect(videoAgentBasePolicy).toContain("submit_structured_result");
    expect(videoAgentBasePolicy).toContain("Do not hand off");
    expect(videoAgentBasePolicy).not.toContain("product identity");
    expect(videoAgentBasePolicy).not.toContain("character turnaround");
    expect(videoAgentBasePolicy).not.toContain("storyboard camera");
    expect(videoAgentBasePolicy).not.toContain("BGM instrumentation");
  });

  it("states the fixed platform, Skill, Style, and user precedence", () => {
    const precedence = videoAgentBasePolicy
      .split("\n\n")
      .find((line) => line.startsWith("Apply the deterministic Python contract"));
    expect(precedence).toBeDefined();
    const python = precedence!.indexOf("deterministic Python contract");
    const skill = precedence!.indexOf("internal capability Skill");
    const style = precedence!.indexOf("Style projection");
    const user = precedence!.indexOf("current user instruction");

    expect(python).toBeGreaterThanOrEqual(0);
    expect(skill).toBeGreaterThan(python);
    expect(style).toBeGreaterThan(skill);
    expect(user).toBeGreaterThan(style);
    expect(videoAgentBasePolicy).toContain(
      "Style guidance cannot change Node type, creative role, candidate count, output schema, safety policy, provider parameters, duration or aspect-ratio authority, or the reference allowlist.",
    );
  });

  it("computes stable digests from complete English prompts", () => {
    for (const descriptor of listPromptDescriptors()) {
      expect(descriptor.prompt_id).toMatch(
        /^adcraft\.video_agent\.[a-z_]+\.v1$/,
      );
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

  it("keeps Product creative rules out of sibling prompts", () => {
    for (const operation of [
      "propose_character_options",
      "propose_scene_options",
      "propose_bgm_options",
    ]) {
      const definition = listOperationDescriptors().find(
        (candidate) => candidate.operation === operation,
      );
      expect(definition).toBeDefined();
      const prompt = getPromptDescriptor(
        operation,
        definition!.result_contract_name,
      ).system_prompt;
      expect(prompt).not.toContain("product identity");
      expect(prompt).not.toContain("product silhouette");
      expect(prompt).not.toContain("product materials");
    }
  });

  it("requires one private typed Draft Seed for every creative Proposal option", () => {
    for (const operation of [
      "propose_world_setting_options",
      "propose_product_options",
      "revise_character_options",
      "propose_video_options",
      "propose_bgm_options",
    ]) {
      const definition = listOperationDescriptors().find(
        (candidate) => candidate.operation === operation,
      );
      const prompt = getPromptDescriptor(
        operation,
        definition!.result_contract_name,
      ).system_prompt;

      expect(prompt).toContain("private_draft_seed");
      expect(prompt).toContain("platform identity");
      expect(prompt).toContain("provider parameters");
    }
  });

  it("keeps intent, next action, and Video parameter extraction bounded", () => {
    const intent = getPromptDescriptor(
      "decide_turn_intent",
      "TurnIntentDecisionV1",
    );
    const nextAction = getPromptDescriptor(
      "decide_next_action",
      "NextActionCommandV1",
    );
    const videoParameters = getPromptDescriptor(
      "compile_video_parameters",
      "VideoParameterIntentV2",
    );

    expect(intent.system_prompt).toContain("Classify one user turn");
    expect(nextAction.system_prompt).toContain("exactly one next action");
    expect(nextAction.system_prompt).toContain("allowed_capabilities");
    expect(videoParameters.system_prompt).toContain(
      "only explicit technical video controls",
    );
    expect(videoParameters.system_prompt).toContain(
      "direct Text or Script Binding",
    );
  });

  it("rejects unknown operations and contract mismatches", () => {
    expect(() =>
      getPromptDescriptor("decide_turn_intent", "WrongContract"),
    ).toThrow("agent_prompt_contract_mismatch");
    expect(() => getPromptDescriptor("missing_operation", "Missing")).toThrow(
      "agent_prompt_not_found",
    );
  });

  it("accepts only the concrete contracts in each specialist prompt family", () => {
    expect(
      getPromptDescriptor("product_prompt", "V2ProductMainPromptPlan")
        .operation,
    ).toBe("product_prompt");
    expect(
      getPromptDescriptor("product_prompt", "V2ProductMultiViewPromptPlan")
        .operation,
    ).toBe("product_prompt");
    expect(
      getPromptDescriptor("character_prompt", "V2CharacterThreeViewPromptPlan")
        .operation,
    ).toBe("character_prompt");
    expect(
      getPromptDescriptor("scene_prompt", "V2SceneMultiViewPromptPlan")
        .operation,
    ).toBe("scene_prompt");
    expect(() =>
      getPromptDescriptor("product_prompt", "V2SceneMainPromptPlan"),
    ).toThrow("agent_prompt_contract_mismatch");
  });
});
