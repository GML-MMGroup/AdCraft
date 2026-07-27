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

const definitions: ReadonlyArray<AgentDefinition> = [
  definition("front_desk", ["workflow_creation", "intent_contract_planner"], 8),
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
  if (/^shot_cell_[1-4]$/.test(family)) return "storyboard_artist";
  if (family === "shot_video_segment") return "video_director";
  if (family === "bgm_track") return "bgm_director";
  if (family === "free_image" || family === "free_video" || family === "free_audio") {
    return "quick_media_agent";
  }
  throw new Error("agent_semantic_family_not_allowed");
}

export function toolsForOperation(
  agentName: AgentName,
  operation: string,
): ReadonlyArray<AgentToolName> {
  const definition = getAgentDefinition(agentName);
  if (!definition.operations.includes(operation)) {
    throw new Error("agent_operation_not_allowed");
  }
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
