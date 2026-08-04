import { describe, expect, it } from "vitest";

import {
  agentForSemanticFamily,
  getAgentDefinition,
  getOperationDescriptor,
  listOperationDescriptors,
  listAgentDefinitions,
  operationClass,
  toolsForOperation,
} from "../src/registry.js";

describe("immutable agent registry", () => {
  it("registers the bounded V2 expert set without final composition", () => {
    const names = listAgentDefinitions().map((definition) => definition.name);

    expect(names).toEqual([
      "bgm_director",
      "character_designer",
      "director",
      "product_designer",
      "prop_designer",
      "quick_media_agent",
      "scene_designer",
      "script_writer",
      "storyboard_artist",
      "video_director",
    ]);
    expect(names).not.toContain("final_composition");
  });

  it("allows only Director to hand off and keeps child depth bounded", () => {
    expect(getAgentDefinition("director").max_handoffs).toBe(1);
    for (const definition of listAgentDefinitions()) {
      if (definition.name !== "director") expect(definition.max_handoffs).toBe(0);
    }
  });

  it("registers the persisted Agent Canvas Script Writer operation", () => {
    const definition = getAgentDefinition("script_writer");

    expect(definition.operations).toContain("execute_canvas_script");
    expect(
      getOperationDescriptor("script_writer", "execute_canvas_script").allowed_tools,
    ).toEqual(["submit_structured_result"]);
  });

  it("registers bounded generic Text execution without specialist skills", () => {
    const definition = getAgentDefinition("quick_media_agent");
    const descriptor = getOperationDescriptor(
      "quick_media_agent",
      "execute_canvas_text",
    );

    expect(definition.operations).toContain("execute_canvas_text");
    expect(descriptor.required_skills).toEqual([]);
    expect(descriptor.optional_skills).toEqual([]);
    expect(descriptor.allowed_tools).toEqual(["submit_structured_result"]);
  });

  it("maps every supported semantic family to exactly one owner", () => {
    expect(agentForSemanticFamily("product_main")).toBe("product_designer");
    expect(agentForSemanticFamily("character_side")).toBe("character_designer");
    expect(agentForSemanticFamily("scene_main")).toBe("scene_designer");
    expect(agentForSemanticFamily("shot_cell_3")).toBe("storyboard_artist");
    expect(agentForSemanticFamily("shot_cell_12")).toBe("storyboard_artist");
    expect(agentForSemanticFamily("shot_video_segment")).toBe("video_director");
    expect(agentForSemanticFamily("bgm_track")).toBe("bgm_director");
    expect(agentForSemanticFamily("prop_main")).toBe("prop_designer");
    expect(agentForSemanticFamily("general_image")).toBe("quick_media_agent");
    expect(agentForSemanticFamily("general_video")).toBe("quick_media_agent");
    expect(agentForSemanticFamily("general_audio")).toBe("quick_media_agent");
    expect(() => agentForSemanticFamily("final_composition")).toThrow(
      "agent_semantic_family_not_allowed",
    );
  });

  it("classifies dynamic shot cells and declares operation-scoped capabilities", () => {
    expect(["shot_cell_1", "shot_cell_4", "shot_cell_12"].map(operationClass)).toEqual([
      "shot_cell",
      "shot_cell",
      "shot_cell",
    ]);
    const descriptor = getOperationDescriptor(
      "character_designer",
      "materialize_draft",
    );

    expect(descriptor.required_skills).toContain("character_prompt_expansion");
    expect(descriptor.required_skills).not.toContain("scene_spec_extraction");
    expect(descriptor.allowed_tools).toEqual(["submit_structured_result"]);
    expect(descriptor.max_skill_context_bytes).toBeGreaterThan(0);
  });

  it("enumerates every operation descriptor without media or final-composition tools", () => {
    const descriptors = listOperationDescriptors();
    const registeredOperationCount = listAgentDefinitions().reduce(
      (total, definition) => total + definition.operations.length,
      0,
    );

    expect(descriptors).toHaveLength(registeredOperationCount);
    expect(
      descriptors.some((descriptor) => descriptor.operation === "final_composition"),
    ).toBe(false);
    expect(
      descriptors.flatMap((descriptor) => descriptor.allowed_tools),
    ).not.toContain("start_final_composition_render");
    expect(
      descriptors.filter(
        (descriptor) =>
          descriptor.agent_name === "director" &&
          descriptor.operation === "conversation_turn",
      ),
    ).toHaveLength(1);
  });

  it("keeps progressive Director turns free of fixed prerequisite skill bias", () => {
    const descriptor = getOperationDescriptor(
      "director",
      "decide_next_guidance_step",
    );

    expect(descriptor.required_skills).toEqual([]);
    expect(descriptor.optional_skills).toEqual([]);
    expect(descriptor.max_handoffs).toBe(0);
    expect(getAgentDefinition("director").operations).not.toContain(
      "plan_production_recipe",
    );
  });

  it("exposes only bounded Python tools and never final composition", () => {
    expect(toolsForOperation("character_designer", "materialize_draft")).toEqual([
      "submit_structured_result",
    ]);
    expect(toolsForOperation("prop_designer", "propose_concepts")).toEqual([
      "submit_structured_result",
    ]);
    expect(
      toolsForOperation("director", "conversation_turn"),
    ).toEqual(["submit_structured_result"]);
    expect(
      toolsForOperation("director", "proposal_action"),
    ).toEqual(["submit_structured_result"]);
    expect(
      getOperationDescriptor("director", "proposal_action").max_handoffs,
    ).toBe(0);
    expect(
      toolsForOperation("video_director", "materialize_draft"),
    ).not.toContain("start_final_composition_render");
  });
});
