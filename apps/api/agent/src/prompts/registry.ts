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

const specialistProfiles = [
  ["script_writer", "Script Writer", "script"],
  ["product_designer", "Product Designer", "product"],
  ["prop_designer", "Prop Designer", "prop"],
  ["character_designer", "Character Designer", "character"],
  ["scene_designer", "Scene Designer", "scene"],
  ["storyboard_artist", "Storyboard Artist", "storyboard"],
  ["video_director", "Video Director", "video"],
  ["bgm_director", "BGM Director", "bgm"],
  ["quick_media_agent", "Quick Media Agent", "general media"],
] as const satisfies ReadonlyArray<readonly [AgentName, string, string]>;

const registrations: ReadonlyArray<PromptRegistration> = [
  registration(
    "adcraft.director.command_replan.v1",
    "director",
    "command_replan",
    "AgentCommandPlanDraftV2",
    "Video Agent Director",
    "Repair one stale command plan from the supplied original intent, bounded plan summary, current target summaries, and conflict metadata. Do not delegate, recurse, or change targets without making the change explicit.",
  ),
  registration(
    "adcraft.director.conversation_turn.v1",
    "director",
    "conversation_turn",
    "AgentActionEnvelopeV2",
    "Video Agent Director",
    [
      "Answer one bounded user turn and delegate at most one local creative task to one registered Specialist.",
      "When the user explicitly asks for concepts for the current creative topic, set specialist_handoff to that topic's owning Specialist instead of returning only conversational text.",
      "Current topic ownership is: script -> script_writer, product -> product_designer, props -> prop_designer, characters -> character_designer, scenes -> scene_designer, storyboard -> storyboard_artist, videos -> video_director, and bgm -> bgm_director.",
      "Do not insert prerequisite analysis before that handoff.",
    ].join(" "),
  ),
  registration(
    "adcraft.director.proposal_action.v1",
    "director",
    "proposal_action",
    "AgentActionEnvelopeV2",
    "Video Agent Director",
    "Continue the conversation after one validated proposal action without creating provider work.",
  ),
  ...specialistProfiles.flatMap(([agentName, role, subject]) => [
    registration(
      `adcraft.${agentName}.propose_concepts.v1`,
      agentName,
      "propose_concepts",
      "ConceptProposalDraftV2",
      role,
      `Return at most four text-only ${subject} concepts using only the local handoff context.`,
    ),
    registration(
      `adcraft.${agentName}.revise_concepts.v1`,
      agentName,
      "revise_concepts",
      "ConceptProposalDraftV2",
      role,
      `Revise the pending ${subject} concepts using only the explicit revision instruction.`,
    ),
    registration(
      `adcraft.${agentName}.materialize_draft.v1`,
      agentName,
      "materialize_draft",
      "SpecialistDraftV2",
      role,
      [
        `Materialize one complete editable ${subject} draft from the selected concept without calling a provider.`,
        ...(subject === "script"
          ? [
              'Set semantic_role exactly to "advertising_script". Populate structured_content.content with the complete editable script as a top-level non-empty string. structured_content must be exactly {"content":"<complete editable script>"}. Do not use a nested concept object, return multiple concepts, or put the script only in generation_prompt.',
            ]
          : []),
      ].join(" "),
    ),
    registration(
      `adcraft.${agentName}.direct_response.v1`,
      agentName,
      "direct_response",
      "SpecialistDirectResponseV2",
      role,
      `Return one bounded ${subject} response for the precise local request without mutating platform state.`,
    ),
  ]),
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

const byOperationAndContract = new Map(
  descriptors.map((item) => [
    `${item.agent_name}:${item.operation}:${item.contract_name}`,
    item,
  ]),
);
const operationKeys = new Set(
  descriptors.map((item) => `${item.agent_name}:${item.operation}`),
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
  const operationKey = `${agentName}:${operation}`;
  const descriptor = byOperationAndContract.get(
    `${operationKey}:${contractName}`,
  );
  if (!descriptor && operationKeys.has(operationKey)) {
    throw new Error("agent_prompt_contract_mismatch");
  }
  if (!descriptor) throw new Error("agent_prompt_not_found");
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
