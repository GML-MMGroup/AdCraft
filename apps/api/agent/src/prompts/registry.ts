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
  ["script_writer", "Script Writer", "script", "ScriptSpecialistDraftV2"],
  [
    "product_designer",
    "Product Designer",
    "product",
    "ProductImageSpecialistDraftV2",
  ],
  ["prop_designer", "Prop Designer", "prop", "PropImageSpecialistDraftV2"],
  [
    "character_designer",
    "Character Designer",
    "character",
    "CharacterImageSpecialistDraftV2",
  ],
  ["scene_designer", "Scene Designer", "scene", "SceneImageSpecialistDraftV2"],
  [
    "storyboard_artist",
    "Storyboard Artist",
    "storyboard",
    "StoryboardImageSpecialistDraftV2",
  ],
  ["video_director", "Video Director", "video", "VideoSpecialistDraftV2"],
  ["bgm_director", "BGM Director", "bgm", "BgmAudioSpecialistDraftV2"],
  ["quick_media_agent", "Quick Media Agent", "general media", "SpecialistDraftV2"],
] as const satisfies ReadonlyArray<
  readonly [AgentName, string, string, string]
>;

const registrations: ReadonlyArray<PromptRegistration> = [
  registration(
    "adcraft.video_director.compile_video_parameters.v1",
    "video_director",
    "compile_video_parameters",
    "VideoParameterIntentV2",
    "Video Director",
    [
      "Extract only explicit technical video controls from the supplied target prompt and direct Text or Script Binding sources.",
      "Allowed fields are duration_seconds, resolution, aspect_ratio, and generate_audio, limited by the supplied capability contract.",
      "Copy source_kind and immutable source identity exactly from the source that explicitly states each value.",
      "Do not infer controls from creative wording, defaults, sibling or transitive nodes, and do not return creative prompt content or provider payloads.",
      "Return no_explicit_controls with no candidates when no supplied source explicitly states a technical control.",
    ].join(" "),
  ),
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
    "adcraft.director.decide_next_guidance_step.v1",
    "director",
    "decide_next_guidance_step",
    "NextGuidanceDecisionV2",
    "Video Agent Director",
    [
      "Decide one next interaction only, never a preplanned future sequence.",
      "For a new guided session, set creative_authority_resolution to resolved when the user clearly provides or delegates the creative direction; otherwise set it to ask so the UI can offer I have a direction and Take the lead.",
      "Creative authority controls creative choices only and must never change media_execution_mode or authorize provider execution.",
      "Choose only a stage present in context.stage_policy.allowed_stage_kinds, prefer context.stage_policy.recommended_stage_kinds, and never invent a fixed future stage queue.",
      "Honor explicit include, exclude, and deferred element decisions from the typed Guidance Session.",
      "You may reply, ask one material clarification, propose at most one topic for exactly one owning Specialist, or finish guidance with a canonical completion_claim.",
      "Use context.topic_ownership as the sole authority for specialist_name. Select the semantic topic first, then copy that topic's exact owning Specialist from the typed context. Never infer, rename, or substitute an owner from prose.",
      "Direct Text, Script, Image, Video, or Audio work is allowed when it best matches the Creative Goal; do not synthesize prerequisite topics.",
      "Return all user-visible language through the Video Agent Director identity.",
      "Do not create Canvas topology, run Nodes, call providers, expose Skill text, or include private reasoning.",
    ].join(" "),
  ),
  registration(
    "adcraft.director.proposal_action.v1",
    "director",
    "proposal_action",
    "DelegatedProposalChoiceV2",
    "Video Agent Director",
    "Choose exactly one existing option_id from the single supplied Proposal and give one bounded reason. Do not delegate, invent options, create provider work, or authorize future Proposals.",
  ),
  registration(
    "adcraft.director.resolve_creation_mode.v1",
    "director",
    "resolve_creation_mode",
    "CreationModeDecisionV2",
    "Video Agent Director",
    [
      "Resolve exactly one mode: ordinary_conversation, targeted_authoring, quick_media, or guided_production.",
      "Use quick_media only for one narrow requested media outcome with one explicit source or target.",
      "Use guided_production for a complete advertisement or multi-stage creative request even when its final delivery is video.",
      "Use targeted_authoring only when the typed context identifies one explicit editable node or supported asset target.",
    ].join(" "),
  ),
  registration(
    "adcraft.scene_designer.propose_world_setting.v1",
    "scene_designer",
    "propose_world_setting",
    "WorldSettingProposalDraftV1",
    "Scene Designer",
    [
      "Propose exactly context.candidate_count distinct World Setting directions; candidate_count must be two or three.",
      "Each direction must contain a title, premise, era and place, core world rules, visual continuity rules, and concise user-facing summary.",
      "Use the World Setting development Skill and the typed creative goal only.",
      "Do not create a screenplay, dialogue, shot list, provider prompt, provider payload, Canvas topology, or media provider call.",
    ].join(" "),
  ),
  registration(
    "adcraft.scene_designer.revise_world_setting_options.v1",
    "scene_designer",
    "revise_world_setting_options",
    "WorldSettingProposalDraftV1",
    "Scene Designer",
    [
      "Revise only the supplied two or three World Setting directions using the explicit revision instruction and preserved anchors.",
      "Return the complete replacement direction set with stable bounded fields.",
      "Do not create a screenplay, dialogue, shot list, provider prompt, provider payload, Canvas topology, or media provider call.",
    ].join(" "),
  ),
  registration(
    "adcraft.scene_designer.materialize_world_setting.v1",
    "scene_designer",
    "materialize_world_setting",
    "WorldSettingMaterializationDraftV2",
    "Scene Designer",
    [
      "Materialize exactly one persisted selected World Setting direction into canonical user-facing prose using the compact structured title and document_content contract.",
      "Use only the selected direction, explicit revision instruction, and preserved authoring context.",
      "Do not create a screenplay, dialogue, shot list, provider prompt, provider payload, Canvas topology, or media provider call.",
    ].join(" "),
  ),
  ...specialistProfiles.flatMap(
    ([agentName, role, subject, materializationContract]) => [
    registration(
      `adcraft.${agentName}.propose_concepts.v1`,
      agentName,
      "propose_concepts",
      "ConceptProposalDraftV2",
      role,
      specialistScope(agentName, "propose_concepts", subject),
    ),
    registration(
      `adcraft.${agentName}.revise_concepts.v1`,
      agentName,
      "revise_concepts",
      "ConceptProposalDraftV2",
      role,
      specialistScope(agentName, "revise_concepts", subject),
    ),
    registration(
      `adcraft.${agentName}.materialize_draft.v1`,
      agentName,
      "materialize_draft",
      materializationContract,
      role,
      [
        specialistScope(agentName, "materialize_draft", subject),
        ...(subject === "script"
          ? [
              'Set creative_role exactly to "script". Populate structured_content.content with the complete editable script as a top-level non-empty string. structured_content must be exactly {"content":"<complete editable script>"}. Do not use a nested concept object, return multiple concepts, or put the script only in generation_prompt.',
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
    ],
  ),
];

function specialistScope(
  agentName: AgentName,
  operation: "propose_concepts" | "revise_concepts" | "materialize_draft",
  subject: string,
): string {
  if (agentName !== "product_designer") {
    if (operation === "propose_concepts") {
      return `Return exactly the requested candidate_count of text-only ${subject} concepts using only the local handoff context. For single_plan return exactly one option; for choice_set return exactly the declared two-to-four options.`;
    }
    if (operation === "revise_concepts") {
      return `Revise the pending ${subject} concepts using only the explicit revision instruction.`;
    }
    return `Materialize one complete editable ${subject} draft from the selected concept without calling a provider.`;
  }
  const action =
    operation === "materialize_draft"
      ? "Materialize one complete editable Draft for"
      : operation === "revise_concepts"
        ? "Revise the pending concepts for"
        : "Return exactly the requested candidate_count of text-only concepts for";
  return [
    `${action} one reusable Product Image using only the local handoff context.`,
    "Define product identity, silhouette and form, materials, color, visible features, composition, background, lighting, and visual style.",
    "Do not author shot lists, timelines, cuts, transitions, dialogue, voice, BGM, editing, a complete commercial, or replacement campaign duration.",
    ...(operation === "propose_concepts"
      ? ["For single_plan return exactly one option; for choice_set return exactly the declared two-to-four options."]
      : []),
    ...(operation === "materialize_draft"
      ? ["Do not call a provider."]
      : []),
  ].join(" ");
}

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
    "Apply instruction precedence in this order: explicit user instructions and technical settings, trusted internal Skill and role contracts, advisory style_guidance, then platform defaults.",
    `Return exactly the ${item.contract_name} contract by calling submit_structured_result. Do not emit JSON in Markdown or prose.`,
    "If Python rejects the first submission, repair only the reported structured violations and submit once more. A second rejection is terminal.",
  ].join("\n\n");
}
