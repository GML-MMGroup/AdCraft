import type { AgentRunRequest } from "./generated/agent-runtime.js";
import { AGENT_CAPABILITY_CONTRACT } from "./generated/agent-capabilities.js";
import { videoAgentBasePolicy } from "./prompts/agents.js";

type AgentName = AgentRunRequest["agent_name"];
export type AgentToolName = "submit_structured_result";
export type CapabilityId =
  | "world_setting"
  | "product_design"
  | "prop_design"
  | "character_design"
  | "scene_design"
  | "script_authoring"
  | "storyboard_design"
  | "video_direction"
  | "bgm_direction"
  | "quick_media";

export interface AgentDefinition {
  readonly name: AgentName;
  readonly system_prompt: string;
  readonly credential_ref: "llm-default";
  readonly operations: ReadonlyArray<string>;
  readonly required_contracts: ReadonlyArray<string>;
  readonly required_skills: ReadonlyArray<string>;
  readonly max_turns: number;
  readonly max_tool_calls: number;
  readonly max_handoffs: 0;
}

export interface OperationDescriptor {
  readonly agent_name: "video_agent";
  readonly operation: string;
  readonly capability_id: CapabilityId | null;
  readonly result_contract_name: string;
  readonly required_skill: string | null;
  readonly style_projection_role: string | null;
  readonly display_name: string | null;
  readonly allowed_tools: readonly ["submit_structured_result"];
  readonly max_skill_context_bytes: number;
  readonly max_handoffs: 0;
}

interface OperationMetadata {
  readonly result_contract_name: string;
  readonly capability_id?: CapabilityId;
  readonly required_skill?: string;
  readonly style_projection_role?: string;
  readonly display_name?: string;
}

const capabilityDefinitions = [
  ["world_setting", "world_setting", "WorldSettingProposalResultV1", "video_agent_world_setting", "World Setting Designer"],
  ["product_design", "product", "ProductProposalResultV1", "video_agent_product_design", "Product Designer"],
  ["prop_design", "prop", "PropProposalResultV1", "video_agent_prop_design", "Prop Designer"],
  ["character_design", "character", "CharacterProposalResultV1", "video_agent_character_design", "Character Designer"],
  ["scene_design", "scene", "SceneProposalResultV1", "video_agent_scene_design", "Scene Designer"],
  ["script_authoring", "script", "ScriptProposalResultV1", "video_agent_script_authoring", "Script Writer"],
  ["storyboard_design", "storyboard", "StoryboardProposalResultV1", "video_agent_storyboard_design", "Storyboard Artist"],
  ["video_direction", "video", "VideoProposalResultV1", "video_agent_video_direction", "Video Director"],
  ["bgm_direction", "bgm", "BgmProposalResultV1", "video_agent_bgm_direction", "BGM Director"],
] as const satisfies ReadonlyArray<
  readonly [CapabilityId, string, string, string, string]
>;

const materializationContracts: Readonly<Record<CapabilityId, string>> = {
  world_setting: "WorldSettingMaterializationResultV1",
  product_design: "ProductMaterializationResultV1",
  prop_design: "PropMaterializationResultV1",
  character_design: "CharacterMaterializationResultV1",
  scene_design: "SceneMaterializationResultV1",
  script_authoring: "ScriptMaterializationResultV1",
  storyboard_design: "StoryboardMaterializationResultV1",
  video_direction: "VideoMaterializationResultV1",
  bgm_direction: "BgmMaterializationResultV1",
  quick_media: "QuickMediaMaterializationResultV1",
};

const metadata = new Map<string, OperationMetadata>([
  ["decide_turn_intent", { result_contract_name: "TurnIntentDecisionV1" }],
  ["decide_next_action", { result_contract_name: "NextActionCommandV1" }],
  ["command_replan", { result_contract_name: "AgentCommandPlanDraftV2" }],
  ["workflow_conversation", { result_contract_name: "WorkflowConversationReply" }],
  ["conversation_summary", { result_contract_name: "ConversationSummaryResult" }],
]);

for (const [capabilityId, stem, contract, skill, displayName] of capabilityDefinitions) {
  for (const prefix of ["propose", "revise"] as const) {
    metadata.set(`${prefix}_${stem}_options`, {
      capability_id: capabilityId,
      result_contract_name: contract,
      required_skill: skill,
      style_projection_role: stem,
      display_name: displayName,
    });
  }
  metadata.set(`materialize_${stem}`, {
    capability_id: capabilityId,
    result_contract_name: materializationContracts[capabilityId],
    required_skill: skill,
    style_projection_role: stem,
    display_name: displayName,
  });
}

addMetadata(["free_image", "free_video", "free_audio"], {
  capability_id: "quick_media",
  result_contract_name: "V2QuickMediaPromptPlan",
  required_skill: "video_agent_quick_media",
  style_projection_role: "quick_media",
  display_name: "Quick Media",
});
metadata.set("materialize_quick_media", {
  capability_id: "quick_media",
  result_contract_name: materializationContracts.quick_media,
  required_skill: "video_agent_quick_media",
  style_projection_role: "quick_media",
  display_name: "Quick Media",
});
metadata.set("execute_canvas_text", { result_contract_name: "AgentCanvasTextOutput" });
metadata.set("execute_canvas_script", creativeMetadata(
  "script_authoring", "AgentCanvasScriptOutput", "video_agent_script_authoring", "script", "Script Writer",
));
metadata.set("compile_video_parameters", creativeMetadata(
  "video_direction", "VideoParameterIntentV2", "video_agent_video_direction", "video", "Video Director",
));
metadata.set("workflow_creation", { result_contract_name: "FrontDeskIntentOutput" });
metadata.set("intent_contract_planner", { result_contract_name: "V2IntentPlan" });
metadata.set("script_writer", creativeMetadata(
  "script_authoring", "V2ScriptPlanV2", "video_agent_script_authoring", "script", "Script Writer",
));
metadata.set("script_edit_normalization", creativeMetadata(
  "script_authoring", "V2EditableScriptDocument", "video_agent_script_authoring", "script", "Script Writer",
));
metadata.set("product_expert_brief", creativeMetadata(
  "product_design", "V2ProductExpertPlan", "video_agent_product_design", "product", "Product Designer",
));
metadata.set("character_expert_brief", creativeMetadata(
  "character_design", "V2CharacterExpertPlan", "video_agent_character_design", "character", "Character Designer",
));
metadata.set("scene_expert_brief", creativeMetadata(
  "scene_design", "V2SceneExpertPlan", "video_agent_scene_design", "scene", "Scene Designer",
));
metadata.set("bgm_expert_brief", creativeMetadata(
  "bgm_direction", "V2BgmExpertPlan", "video_agent_bgm_direction", "bgm", "BGM Director",
));
metadata.set("product_prompt", creativeMetadata(
  "product_design", "V2ProductPromptPlan", "video_agent_product_design", "product", "Product Designer",
));
metadata.set("character_prompt", creativeMetadata(
  "character_design", "V2CharacterPromptPlan", "video_agent_character_design", "character", "Character Designer",
));
metadata.set("scene_prompt", creativeMetadata(
  "scene_design", "V2ScenePromptPlan", "video_agent_scene_design", "scene", "Scene Designer",
));
metadata.set("storyboard_prompt", creativeMetadata(
  "storyboard_design", "V2ShotCellPromptPlan", "video_agent_storyboard_design", "storyboard", "Storyboard Artist",
));
metadata.set("storyboard_detail", creativeMetadata(
  "storyboard_design", "V2StoryboardDetailPlan", "video_agent_storyboard_design", "storyboard", "Storyboard Artist",
));
metadata.set("shot_video_prompt", creativeMetadata(
  "video_direction", "V2ShotVideoPromptPlan", "video_agent_video_direction", "video", "Video Director",
));
metadata.set("bgm_prompt", creativeMetadata(
  "bgm_direction", "V2BgmPromptPlan", "video_agent_bgm_direction", "bgm", "BGM Director",
));
metadata.set("visual_style_scope_repair", creativeMetadata(
  "world_setting", "V2VisualStyleScopeRepairOutput", "video_agent_world_setting", "world_setting", "World Setting Designer",
));
metadata.set("revise_character_asset", creativeMetadata(
  "character_design", "SpecialistResult", "video_agent_character_design", "character", "Character Designer",
));
metadata.set("revise_scene_asset", creativeMetadata(
  "scene_design", "SpecialistResult", "video_agent_scene_design", "scene", "Scene Designer",
));

const sourceAgent = AGENT_CAPABILITY_CONTRACT.agents[0];
if (
  AGENT_CAPABILITY_CONTRACT.agents.length !== 1 ||
  sourceAgent.name !== "video_agent" ||
  sourceAgent.model_role !== "agent" ||
  sourceAgent.operations.length !== metadata.size ||
  sourceAgent.operations.some((operation) => !metadata.has(operation))
) {
  throw new Error("agent_operation_registry_invalid");
}

const descriptors: ReadonlyArray<OperationDescriptor> = Object.freeze(
  sourceAgent.operations.map((operation) => {
    const item = metadata.get(operation);
    if (!item) throw new Error("agent_operation_registry_invalid");
    return Object.freeze({
      agent_name: "video_agent",
      operation,
      capability_id: item.capability_id ?? null,
      result_contract_name: item.result_contract_name,
      required_skill: item.required_skill ?? null,
      style_projection_role: item.style_projection_role ?? null,
      display_name: item.display_name ?? null,
      allowed_tools: Object.freeze(["submit_structured_result"] as const),
      max_skill_context_bytes: 8_192,
      max_handoffs: 0,
    }) satisfies OperationDescriptor;
  }),
);
const byOperation = new Map<string, OperationDescriptor>(
  descriptors.map((item) => [item.operation, item]),
);
const definition: AgentDefinition = Object.freeze({
  name: "video_agent",
  system_prompt: videoAgentBasePolicy,
  credential_ref: "llm-default",
  operations: Object.freeze([...sourceAgent.operations]),
  required_contracts: Object.freeze([]),
  required_skills: Object.freeze([]),
  max_turns: 8,
  max_tool_calls: 2,
  max_handoffs: 0,
});

export function listAgentDefinitions(): ReadonlyArray<AgentDefinition> {
  return Object.freeze([definition]);
}

export function getAgentDefinition(name: AgentName): AgentDefinition {
  if (name !== "video_agent") throw new Error("agent_registry_entry_not_found");
  return definition;
}

export function getOperationDescriptor(operation: string): OperationDescriptor {
  const found = byOperation.get(operation);
  if (!found) throw new Error("agent_operation_not_allowed");
  return found;
}

export function listOperationDescriptors(): ReadonlyArray<OperationDescriptor> {
  return descriptors;
}

export function toolsForOperation(operation: string): readonly [AgentToolName] {
  return getOperationDescriptor(operation).allowed_tools;
}

function addMetadata(
  operations: ReadonlyArray<string>,
  definition: OperationMetadata,
): void {
  for (const operation of operations) metadata.set(operation, definition);
}

function creativeMetadata(
  capabilityId: CapabilityId,
  resultContractName: string,
  requiredSkill: string,
  styleProjectionRole: string,
  displayName: string,
): OperationMetadata {
  return {
    capability_id: capabilityId,
    result_contract_name: resultContractName,
    required_skill: requiredSkill,
    style_projection_role: styleProjectionRole,
    display_name: displayName,
  };
}
