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
      "front_desk",
      "script_writer",
      "product_designer",
      "character_designer",
      "scene_designer",
      "storyboard_artist",
      "video_director",
      "bgm_director",
      "quick_media_agent",
    ]);
    expect(names).not.toContain("final_composition");
  });

  it("allows only front desk to hand off and keeps child depth bounded", () => {
    expect(getAgentDefinition("front_desk").max_handoffs).toBeGreaterThan(0);
    expect(getAgentDefinition("script_writer").max_handoffs).toBe(0);
    expect(getAgentDefinition("character_designer").max_handoffs).toBe(0);
  });

  it("maps every supported semantic family to exactly one owner", () => {
    expect(agentForSemanticFamily("product_main")).toBe("product_designer");
    expect(agentForSemanticFamily("character_side")).toBe("character_designer");
    expect(agentForSemanticFamily("scene_main")).toBe("scene_designer");
    expect(agentForSemanticFamily("shot_cell_3")).toBe("storyboard_artist");
    expect(agentForSemanticFamily("shot_cell_12")).toBe("storyboard_artist");
    expect(agentForSemanticFamily("shot_video_segment")).toBe("video_director");
    expect(agentForSemanticFamily("bgm_track")).toBe("bgm_director");
    expect(agentForSemanticFamily("free_audio")).toBe("quick_media_agent");
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
      "character_prompt",
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
          descriptor.agent_name === "quick_media_agent" &&
          descriptor.operation === "free_video",
      ),
    ).toHaveLength(1);
  });

  it("exposes only bounded Python tools and never final composition", () => {
    expect(toolsForOperation("character_designer", "targeted_revision")).toEqual([
      "list_canvas_targets",
      "resolve_canvas_target",
      "read_target_context",
      "submit_structured_result",
      "save_prompt_revision",
      "start_slot_generation",
      "select_asset_version",
      "discard_working_version",
    ]);
    expect(toolsForOperation("quick_media_agent", "free_video")).toEqual([
      "submit_structured_result",
      "start_free_media_generation",
    ]);
    expect(
      toolsForOperation("front_desk", "workflow_creation"),
    ).toEqual(["submit_structured_result"]);
    expect(
      toolsForOperation("front_desk", "workflow_conversation"),
    ).toEqual(["submit_structured_result"]);
    expect(
      toolsForOperation("video_director", "targeted_revision"),
    ).not.toContain("start_final_composition_render");
  });
});
