import type { AgentRunRequest } from "./generated/agent-runtime.js";
import { agentSystemPrompts } from "./prompts/agents.js";

type AgentName = AgentRunRequest["agent_name"];
export type AgentToolName =
  | "list_canvas_targets"
  | "resolve_canvas_target"
  | "read_target_context"
  | "submit_structured_result"
  | "save_prompt_revision"
  | "start_slot_generation"
  | "start_free_media_generation"
  | "select_asset_version"
  | "discard_working_version";

export interface AgentDefinition {
  readonly name: AgentName;
  readonly system_prompt: string;
  readonly credential_ref: "llm-default";
  readonly operations: ReadonlyArray<string>;
  readonly required_contracts: ReadonlyArray<string>;
  readonly required_skills: ReadonlyArray<string>;
  readonly max_turns: number;
  readonly max_tool_calls: number;
  readonly max_handoffs: number;
}

export interface OperationDescriptor {
  readonly agent_name: AgentName;
  readonly operation: string;
  readonly operation_class: string;
  readonly required_skills: ReadonlyArray<string>;
  readonly optional_skills: ReadonlyArray<string>;
  readonly allowed_tools: ReadonlyArray<AgentToolName>;
  readonly max_skill_context_bytes: number;
}

const definitions: ReadonlyArray<AgentDefinition> = [
  definition(
    "front_desk",
    [
      "workflow_creation",
      "intent_contract_planner",
      "workflow_conversation",
      "conversation_summary",
    ],
    8,
  ),
  definition("script_writer", ["script_writer", "script_edit_normalization", "targeted_revision"], 0),
  definition("product_designer", ["product_expert_brief", "product_prompt", "product_revision", "targeted_revision"], 0),
  definition("character_designer", ["character_expert_brief", "character_prompt", "character_revision", "targeted_revision"], 0),
  definition("scene_designer", ["scene_expert_brief", "scene_prompt", "scene_revision", "visual_style_scope_repair", "targeted_revision"], 0),
  definition("storyboard_artist", ["storyboard_detail", "storyboard_prompt", "targeted_revision"], 0),
  definition("video_director", ["shot_video_prompt", "targeted_revision"], 0),
  definition("bgm_director", ["bgm_expert_brief", "bgm_prompt", "targeted_revision"], 0),
  definition("quick_media_agent", ["free_image", "free_video", "free_audio"], 0),
];

const byName = new Map(definitions.map((item) => [item.name, item]));

export function listAgentDefinitions(): ReadonlyArray<AgentDefinition> {
  return definitions;
}

export function getAgentDefinition(name: AgentName): AgentDefinition {
  const found = byName.get(name);
  if (!found) throw new Error("agent_registry_entry_not_found");
  return found;
}

export function agentForSemanticFamily(family: string): AgentName {
  if (family.startsWith("product_")) return "product_designer";
  if (family.startsWith("character_")) return "character_designer";
  if (family.startsWith("scene_")) return "scene_designer";
  if (operationClass(family) === "shot_cell") return "storyboard_artist";
  if (family === "shot_video_segment") return "video_director";
  if (family === "bgm_track") return "bgm_director";
  if (family === "free_image" || family === "free_video" || family === "free_audio") {
    return "quick_media_agent";
  }
  throw new Error("agent_semantic_family_not_allowed");
}

export function operationClass(operation: string): string {
  return /^shot_cell_\d+$/.test(operation) ? "shot_cell" : operation;
}

export function getOperationDescriptor(
  agentName: AgentName,
  operation: string,
): OperationDescriptor {
  const definition = getAgentDefinition(agentName);
  if (!definition.operations.includes(operation)) {
    throw new Error("agent_operation_not_allowed");
  }
  const skills = skillsForOperation(agentName, operation);
  return Object.freeze({
    agent_name: agentName,
    operation,
    operation_class: operationClass(operation),
    required_skills: Object.freeze(skills.required),
    optional_skills: Object.freeze(skills.optional),
    allowed_tools: Object.freeze(allowedTools(agentName, operation)),
    max_skill_context_bytes: 8_192,
  });
}

export function toolsForOperation(
  agentName: AgentName,
  operation: string,
): ReadonlyArray<AgentToolName> {
  return getOperationDescriptor(agentName, operation).allowed_tools;
}

function allowedTools(
  agentName: AgentName,
  operation: string,
): ReadonlyArray<AgentToolName> {
  if (agentName === "front_desk" || operation !== "targeted_revision") {
    if (
      agentName === "quick_media_agent" &&
      ["free_image", "free_video", "free_audio"].includes(operation)
    ) {
      return Object.freeze([
        "submit_structured_result",
        "start_free_media_generation",
      ]);
    }
    return Object.freeze(["submit_structured_result"]);
  }
  return Object.freeze([
    "list_canvas_targets",
    "resolve_canvas_target",
    "read_target_context",
    "submit_structured_result",
    "save_prompt_revision",
    "start_slot_generation",
    "select_asset_version",
    "discard_working_version",
  ]);
}

function skillsForOperation(
  agentName: AgentName,
  operation: string,
): { required: string[]; optional: string[] } {
  if (agentName === "front_desk") {
    return {
      required: ["audience_analysis", "campaign_appeal_generation"],
      optional: operation === "workflow_creation" ? ["product_info_extraction"] : [],
    };
  }
  if (agentName === "script_writer") {
    return {
      required: ["short_ad_script_structure", "dialogue_copy_generation"],
      optional: [],
    };
  }
  if (agentName === "product_designer") {
    return {
      required:
        operation === "product_expert_brief"
          ? ["product_info_extraction", "selling_point_extraction"]
          : ["selling_point_extraction"],
      optional: ["reference_asset_selection"],
    };
  }
  if (agentName === "character_designer") {
    return {
      required:
        operation === "character_expert_brief"
          ? ["character_spec_extraction"]
          : ["character_prompt_expansion", "character_turnaround_prompt"],
      optional: ["reference_asset_selection"],
    };
  }
  if (agentName === "scene_designer") {
    return {
      required:
        operation === "scene_expert_brief"
          ? ["scene_spec_extraction"]
          : ["pure_scene_prompt_expansion", "multi_view_scene_prompt"],
      optional: ["reference_asset_selection"],
    };
  }
  if (agentName === "storyboard_artist") {
    return {
      required:
        operation === "storyboard_detail"
          ? ["storyboard_beat_extraction"]
          : ["storyboard_image_prompt_generation", "visual_continuity_check"],
      optional: ["reference_asset_selection"],
    };
  }
  if (agentName === "video_director") {
    return {
      required: [
        "storyboard_video_prompt_generation",
        "segment_generation_planning",
      ],
      optional: ["visual_continuity_check", "reference_asset_selection"],
    };
  }
  if (agentName === "bgm_director") {
    return {
      required: ["bgm_prompt_generation", "mood_and_duration_matching"],
      optional: [],
    };
  }
  return {
    required: ["creative_idea_generation"],
    optional: ["reference_asset_selection"],
  };
}

function definition(
  name: AgentName,
  operations: ReadonlyArray<string>,
  maxHandoffs: number,
): AgentDefinition {
  return Object.freeze({
    name,
    system_prompt: agentSystemPrompts[name],
    credential_ref: "llm-default",
    operations: Object.freeze([...operations]),
    required_contracts: Object.freeze([]),
    required_skills: Object.freeze([]),
    max_turns: 8,
    max_tool_calls: 16,
    max_handoffs: maxHandoffs,
  });
}
