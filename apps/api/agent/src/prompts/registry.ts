import { createHash } from "node:crypto";

import type { AgentRunRequest } from "../generated/agent-runtime.js";

type AgentName = AgentRunRequest["agent_name"];

export interface PromptDescriptor {
  readonly prompt_id: string;
  readonly prompt_version: string;
  readonly prompt_digest: string;
  readonly agent_name: AgentName;
  readonly operation: string;
  readonly contract_name: string;
  readonly system_prompt: string;
}

type PromptRegistration = Omit<
  PromptDescriptor,
  "prompt_version" | "prompt_digest" | "system_prompt"
> & {
  readonly role: string;
  readonly scope: string;
};

const registrations: ReadonlyArray<PromptRegistration> = [
  registration(
    "adcraft.front_desk.workflow_creation.v1",
    "front_desk",
    "workflow_creation",
    "FrontDeskIntentOutput",
    "Front Desk",
    "Classify the user message, preserve explicit advertising facts, and decide whether a complete workflow request can start.",
  ),
  registration(
    "adcraft.front_desk.intent_contract.v1",
    "front_desk",
    "intent_contract_planner",
    "V2IntentPlan",
    "Front Desk",
    "Normalize the approved advertising request into the canonical intent contract without inventing explicit counts.",
  ),
  registration(
    "adcraft.front_desk.workflow_conversation.v1",
    "front_desk",
    "workflow_conversation",
    "WorkflowConversationReply",
    "Front Desk",
    "Answer one bounded workflow-scoped conversation turn. Ask for one exact Character or Scene target before proposing a targeted revision.",
  ),
  registration(
    "adcraft.front_desk.conversation_summary.v1",
    "front_desk",
    "conversation_summary",
    "ConversationSummaryResult",
    "Front Desk",
    "Compress only visible conversation turns into a bounded factual summary without hidden reasoning or new creative facts.",
  ),
  registration(
    "adcraft.script_writer.screenplay.v1",
    "script_writer",
    "script_writer",
    "V2ScriptPlanV2",
    "Script Writer",
    "Write the canonical screenplay from the approved intent, frozen facts, scoped references, and declared creative inventory.",
  ),
  registration(
    "adcraft.product_designer.expert_brief.v1",
    "product_designer",
    "product_expert_brief",
    "V2ProductExpertPlan",
    "Product Designer",
    "Create product-only identity and presentation briefs from Product inventory and Product-relevant screenplay slices.",
  ),
  registration(
    "adcraft.character_designer.expert_brief.v1",
    "character_designer",
    "character_expert_brief",
    "V2CharacterExpertPlan",
    "Character Designer",
    "Create character-only identity and continuity briefs from Character inventory and Character-relevant screenplay slices.",
  ),
  registration(
    "adcraft.scene_designer.expert_brief.v1",
    "scene_designer",
    "scene_expert_brief",
    "V2SceneExpertPlan",
    "Scene Designer",
    "Create environment-only scene briefs from Scene inventory and Scene-relevant screenplay slices.",
  ),
  registration(
    "adcraft.bgm_director.expert_brief.v1",
    "bgm_director",
    "bgm_expert_brief",
    "V2BgmExpertPlan",
    "BGM Director",
    "Create an instrumental music brief from the screenplay rhythm, duration, emotion, and audio constraints.",
  ),
  registration(
    "adcraft.product_designer.product_prompt.v1",
    "product_designer",
    "product_prompt",
    "V2ProductPromptPlan",
    "Product Designer",
    "Compile one Product slot prompt while preserving exact Product identity and only its declared references.",
  ),
  registration(
    "adcraft.character_designer.character_prompt.v1",
    "character_designer",
    "character_prompt",
    "V2CharacterPromptPlan",
    "Character Designer",
    "Compile one Character slot prompt while preserving exact Character identity, view requirements, and references.",
  ),
  registration(
    "adcraft.scene_designer.scene_prompt.v1",
    "scene_designer",
    "scene_prompt",
    "V2ScenePromptPlan",
    "Scene Designer",
    "Compile one Scene slot prompt from the owning environment brief and only Scene-relevant references.",
  ),
  registration(
    "adcraft.storyboard_artist.storyboard_detail.v1",
    "storyboard_artist",
    "storyboard_detail",
    "V2StoryboardDetailPlan",
    "Storyboard Artist",
    "Expand canonical screenplay shots into deterministic visual detail while preserving shot order and ownership.",
  ),
  registration(
    "adcraft.storyboard_artist.storyboard_prompt.v1",
    "storyboard_artist",
    "storyboard_prompt",
    "V2ShotCellPromptPlan",
    "Storyboard Artist",
    "Compile one storyboard cell prompt from its owning shot, cell role, continuity state, and scoped references.",
  ),
  registration(
    "adcraft.video_director.shot_video_prompt.v1",
    "video_director",
    "shot_video_prompt",
    "V2ShotVideoPromptPlan",
    "Video Director",
    "Compile one shot-video motion prompt from that shot's selected storyboard cells and validated continuity constraints.",
  ),
  registration(
    "adcraft.bgm_director.bgm_prompt.v1",
    "bgm_director",
    "bgm_prompt",
    "V2BgmPromptPlan",
    "BGM Director",
    "Compile one instrumental BGM provider prompt with duration, mood, pacing, no-vocals, and safety constraints.",
  ),
  registration(
    "adcraft.quick_media.free_image.v1",
    "quick_media_agent",
    "free_image",
    "V2QuickMediaPromptPlan",
    "Quick Media Agent",
    "Compile one standalone image provider prompt. Do not classify the output as a Product, Character, Scene, or storyboard asset.",
  ),
  registration(
    "adcraft.quick_media.free_video.v1",
    "quick_media_agent",
    "free_video",
    "V2QuickMediaPromptPlan",
    "Quick Media Agent",
    "Compile one standalone video provider prompt. Do not classify the output as a Product, Character, Scene, or storyboard asset.",
  ),
  registration(
    "adcraft.quick_media.free_audio.v1",
    "quick_media_agent",
    "free_audio",
    "V2QuickMediaPromptPlan",
    "Quick Media Agent",
    "Compile one standalone audio provider prompt. Do not classify the output as a Product, Character, Scene, or BGM-owned workflow asset.",
  ),
];

const descriptors = Object.freeze(
  registrations.map((item) => {
    const systemPrompt = canonicalPrompt(item);
    return Object.freeze({
      prompt_id: item.prompt_id,
      prompt_version: "1",
      prompt_digest: createHash("sha256").update(systemPrompt, "utf8").digest("hex"),
      agent_name: item.agent_name,
      operation: item.operation,
      contract_name: item.contract_name,
      system_prompt: systemPrompt,
    }) satisfies PromptDescriptor;
  }),
);

const byOperation = new Map(
  descriptors.map((item) => [`${item.agent_name}:${item.operation}`, item]),
);
const planningOperations = new Set(descriptors.map((item) => item.operation));

export function listPromptDescriptors(): ReadonlyArray<PromptDescriptor> {
  return descriptors;
}

export function isPlanningOperation(operation: string): boolean {
  return planningOperations.has(operation);
}

export function getPromptDescriptor(
  agentName: AgentName,
  operation: string,
  contractName: string,
): PromptDescriptor {
  const descriptor = byOperation.get(`${agentName}:${operation}`);
  if (!descriptor) throw new Error("agent_prompt_not_found");
  if (descriptor.contract_name !== contractName) {
    throw new Error("agent_prompt_contract_mismatch");
  }
  return descriptor;
}

function registration(
  promptId: string,
  agentName: AgentName,
  operation: string,
  contractName: string,
  role: string,
  scope: string,
): PromptRegistration {
  return {
    prompt_id: promptId,
    agent_name: agentName,
    operation,
    contract_name: contractName,
    role,
    scope,
  };
}

function canonicalPrompt(item: PromptRegistration): string {
  return [
    `You are the AdCraft ${item.role} for the ${item.operation} operation.`,
    item.scope,
    "Use only the typed context supplied for this operation. Do not infer from sibling expert prompts, provider payloads, complete workflow documents, local paths, credentials, or media bytes.",
    "Preserve every frozen explicit user fact exactly. Values marked unspecified may be chosen only within the operation scope and must not be relabeled as user-explicit.",
    `Return exactly the ${item.contract_name} contract by calling submit_structured_result. Do not emit JSON in Markdown or prose.`,
    "If Python rejects the first submission, repair only the reported structured violations and submit once more. A second rejection is terminal.",
  ].join("\n\n");
}
