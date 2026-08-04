import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import {
  getPromptDescriptor,
  listPromptDescriptors,
} from "../src/prompts/registry.js";
import { getAgentDefinition } from "../src/registry.js";
import type { AgentRunRequest } from "../src/generated/agent-runtime.js";

const expectedPlanningOperations = [
  ["director", "command_replan", "AgentCommandPlanDraftV2"],
  ["director", "conversation_turn", "AgentActionEnvelopeV2"],
  ["director", "decide_next_guidance_step", "NextGuidanceDecisionV2"],
  ["director", "proposal_action", "DelegatedProposalChoiceV2"],
  ["director", "resolve_creation_mode", "CreationModeDecisionV2"],
  ...[
    "script_writer",
    "product_designer",
    "prop_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
    "quick_media_agent",
  ].flatMap((agentName) => [
    [agentName, "propose_concepts", "ConceptProposalDraftV2"],
    [agentName, "revise_concepts", "ConceptProposalDraftV2"],
    [agentName, "materialize_draft", "SpecialistDraftV2"],
    [agentName, "direct_response", "SpecialistDirectResponseV2"],
  ]),
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
      const name = agentName as AgentRunRequest["agent_name"];
      const descriptor = getPromptDescriptor(name, operation, contractName);
      expect(getAgentDefinition(name).operations).toContain(operation);
      expect(descriptor.agent_name).toBe(agentName);
      expect(descriptor.contract_name).toBe(contractName);
    }
    expect(getAgentDefinition("director").operations).toEqual([
      "command_replan",
      "conversation_turn",
      "decide_next_guidance_step",
      "proposal_action",
      "resolve_creation_mode",
    ]);
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

  it("keeps draft materialization cognition-only", () => {
    for (const agentName of ["character_designer", "scene_designer"] as const) {
      const descriptor = getPromptDescriptor(
        agentName,
        "materialize_draft",
        "SpecialistDraftV2",
      );

      expect(descriptor.system_prompt).toContain("without calling a provider");
      expect(descriptor.system_prompt).toContain("typed context");
    }
  });

  it("requires script materialization to populate structured script content", () => {
    const descriptor = getPromptDescriptor(
      "script_writer",
      "materialize_draft",
      "SpecialistDraftV2",
    );

    expect(descriptor.system_prompt).toContain(
      "structured_content.content with the complete editable script",
    );
    expect(descriptor.system_prompt).toContain(
      'semantic_role exactly to "advertising_script"',
    );
    expect(descriptor.system_prompt).toContain(
      "top-level non-empty string",
    );
    expect(descriptor.system_prompt).toContain(
      'structured_content must be exactly {"content":"<complete editable script>"}',
    );
  });

  it("routes explicit current-topic concept requests to the owning Specialist", () => {
    const descriptor = getPromptDescriptor(
      "director",
      "conversation_turn",
      "AgentActionEnvelopeV2",
    );

    expect(descriptor.system_prompt).toContain(
      "When the user explicitly asks for concepts for the current creative topic",
    );
    expect(descriptor.system_prompt).toContain("script -> script_writer");
    expect(descriptor.system_prompt).toContain(
      "Do not insert prerequisite analysis before that handoff",
    );
  });

  it("separates complete production planning from narrow quick media", () => {
    const mode = getPromptDescriptor(
      "director",
      "resolve_creation_mode",
      "CreationModeDecisionV2",
    );
    const guidance = getPromptDescriptor(
      "director",
      "decide_next_guidance_step",
      "NextGuidanceDecisionV2",
    );
    const specialist = getPromptDescriptor(
      "scene_designer",
      "propose_concepts",
      "ConceptProposalDraftV2",
    );

    expect(mode.system_prompt).toContain("guided_production");
    expect(mode.system_prompt).toContain("quick_media");
    expect(guidance.system_prompt).toContain("one next interaction only");
    expect(guidance.system_prompt).toContain("at most one topic");
    expect(guidance.system_prompt).toContain("completion_claim");
    expect(guidance.system_prompt).not.toContain("production recipe");
    expect(specialist.system_prompt).toContain(
      "exactly the requested candidate_count",
    );
  });

  it("rejects unknown or contract-mismatched planning descriptors", () => {
    expect(() =>
      getPromptDescriptor(
        "director",
        "conversation_turn",
        "WrongContract",
      ),
    ).toThrow("agent_prompt_contract_mismatch");
    expect(() =>
      getPromptDescriptor("director", "missing_operation", "Missing"),
    ).toThrow("agent_prompt_not_found");
  });
});
