import type { AgentRunRequest } from "./generated/agent-runtime.js";
import { AGENT_CAPABILITY_CONTRACT } from "./generated/agent-capabilities.js";
import { agentSystemPrompts } from "./prompts/agents.js";

type AgentName = AgentRunRequest["agent_name"];
export type AgentToolName = "submit_structured_result";

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
  ...AGENT_CAPABILITY_CONTRACT.agents.map((capability) =>
    definition(
      capability.name,
      capability.operations,
      capability.name === "director" ? 1 : 0,
    ),
  ),
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
  if (family.startsWith("prop_")) return "prop_designer";
  if (family.startsWith("character_")) return "character_designer";
  if (family.startsWith("scene_")) return "scene_designer";
  if (operationClass(family) === "shot_cell") return "storyboard_artist";
  if (family === "shot_video_segment") return "video_director";
  if (family === "bgm_track") return "bgm_director";
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

export function listOperationDescriptors(): ReadonlyArray<OperationDescriptor> {
  return Object.freeze(
    definitions.flatMap((definition) =>
      definition.operations.map((operation) =>
        getOperationDescriptor(definition.name, operation),
      ),
    ),
  );
}

export function toolsForOperation(
  agentName: AgentName,
  operation: string,
): ReadonlyArray<AgentToolName> {
  return getOperationDescriptor(agentName, operation).allowed_tools;
}

function allowedTools(
  _agentName: AgentName,
  _operation: string,
): ReadonlyArray<AgentToolName> {
  return Object.freeze(["submit_structured_result"]);
}

function skillsForOperation(
  agentName: AgentName,
  operation: string,
): { required: string[]; optional: string[] } {
  if (agentName === "director") {
    return {
      required: ["audience_analysis", "campaign_appeal_generation"],
      optional: [],
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
  if (agentName === "prop_designer") {
    return {
      required: ["creative_idea_generation"],
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
  throw new Error("agent_skill_policy_not_found");
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
