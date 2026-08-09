import { describe, expect, it } from "vitest";

import { AGENT_CAPABILITY_CONTRACT } from "../src/generated/agent-capabilities.js";
import {
  getAgentDefinition,
  getOperationDescriptor,
  listAgentDefinitions,
  listOperationDescriptors,
  toolsForOperation,
} from "../src/registry.js";

const operations = AGENT_CAPABILITY_CONTRACT.agents[0].operations;

describe("Video Agent registry", () => {
  it("registers one Video Agent with the exact closed operation set", () => {
    const definitions = listAgentDefinitions();

    expect(definitions).toHaveLength(1);
    expect(definitions[0]?.name).toBe("video_agent");
    expect(definitions[0]?.operations).toEqual(operations);
    expect(definitions[0]?.max_handoffs).toBe(0);
    expect(operations).toHaveLength(48);
  });

  it("resolves operation metadata without an Agent selector", () => {
    const descriptor = getOperationDescriptor("propose_character_options");

    expect(descriptor).toMatchObject({
      agent_name: "video_agent",
      operation: "propose_character_options",
      capability_id: "character_design",
      result_contract_name: "CharacterProposalResultV1",
      required_skill: "video_agent_character_design",
      allowed_tools: ["submit_structured_result"],
      max_handoffs: 0,
    });
    expect(descriptor.max_skill_context_bytes).toBeGreaterThan(0);
  });

  it("keeps only Quick Media on the model-assisted materialization path", () => {
    expect(getOperationDescriptor("materialize_quick_media")).toMatchObject({
      capability_id: "quick_media",
      result_contract_name: "QuickMediaMaterializationResultV1",
      required_skill: "video_agent_quick_media",
    });
    expect(() => getOperationDescriptor("materialize_character")).toThrow(
      "agent_operation_not_allowed",
    );
  });

  it("loads no creative Skill for decision, conversation, and Text operations", () => {
    for (const operation of [
      "decide_turn_intent",
      "decide_next_action",
      "command_replan",
      "workflow_conversation",
      "conversation_summary",
      "execute_canvas_text",
      "workflow_creation",
      "intent_contract_planner",
    ]) {
      expect(getOperationDescriptor(operation).required_skill).toBeNull();
    }
  });

  it("enumerates every operation exactly once with zero handoffs and one tool", () => {
    const descriptors = listOperationDescriptors();

    expect(descriptors.map(({ operation }) => operation)).toEqual(operations);
    expect(new Set(descriptors.map(({ operation }) => operation)).size).toBe(48);
    expect(descriptors.every(({ agent_name }) => agent_name === "video_agent")).toBe(true);
    expect(descriptors.every(({ max_handoffs }) => max_handoffs === 0)).toBe(true);
    expect(
      descriptors.every(({ allowed_tools }) =>
        allowed_tools.length === 1 && allowed_tools[0] === "submit_structured_result"),
    ).toBe(true);
    expect(
      descriptors.every(({ required_skill }) =>
        required_skill === null || required_skill.startsWith("video_agent_")),
    ).toBe(true);
  });

  it("rejects retired identities and unknown operations", () => {
    expect(() => getAgentDefinition("director" as "video_agent")).toThrow(
      "agent_registry_entry_not_found",
    );
    expect(() => getOperationDescriptor("targeted_revision")).toThrow(
      "agent_operation_not_allowed",
    );
    expect(() => getOperationDescriptor("propose_concepts")).toThrow(
      "agent_operation_not_allowed",
    );
  });

  it("exposes only structured result submission", () => {
    expect(toolsForOperation("propose_product_options")).toEqual([
      "submit_structured_result",
    ]);
    expect(toolsForOperation("execute_canvas_text")).toEqual([
      "submit_structured_result",
    ]);
  });
});
