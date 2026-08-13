import { createHash } from "node:crypto";

import { videoAgentBasePolicy } from "./agents.js";
import { listOperationDescriptors } from "../registry.js";

export interface PromptDescriptor {
  readonly prompt_id: string;
  readonly prompt_version: string;
  readonly prompt_digest: string;
  readonly agent_name: "video_agent";
  readonly operation: string;
  readonly contract_name: string;
  readonly system_prompt: string;
}

const descriptors = Object.freeze(
  listOperationDescriptors().map((operation) => {
    const systemPrompt = [
      videoAgentBasePolicy,
      instructionForOperation(operation.operation),
      "Render every model-owned user-visible or audible field in the supplied response_locale. Keep field names, enum values, IDs, diagnostics, provider controls, and hidden constraints in canonical English. Style guidance never overrides response_locale.",
      `Return exactly the ${operation.result_contract_name} contract through the configured structured transport.`,
      "If Python rejects the first result, repair only the reported structured violations once. A second rejection is terminal.",
    ].join("\n\n");
    return Object.freeze({
      prompt_id: `adcraft.video_agent.${operation.operation}.v1`,
      prompt_version: "1",
      prompt_digest: createHash("sha256").update(systemPrompt, "utf8").digest("hex"),
      agent_name: "video_agent",
      operation: operation.operation,
      contract_name: operation.result_contract_name,
      system_prompt: systemPrompt,
    }) satisfies PromptDescriptor;
  }),
);
const byOperation = new Map(descriptors.map((item) => [item.operation, item]));
const concreteContractFamilies = new Map<string, ReadonlySet<string>>([
  [
    "product_prompt",
    new Set(["V2ProductMainPromptPlan", "V2ProductMultiViewPromptPlan"]),
  ],
  [
    "character_prompt",
    new Set(["V2CharacterMainPromptPlan", "V2CharacterThreeViewPromptPlan"]),
  ],
  [
    "scene_prompt",
    new Set(["V2SceneMainPromptPlan", "V2SceneMultiViewPromptPlan"]),
  ],
]);

export function listPromptDescriptors(): ReadonlyArray<PromptDescriptor> {
  return descriptors;
}

export function isPlanningOperation(operation: string): boolean {
  return byOperation.has(operation);
}

export function getPromptDescriptor(
  operation: string,
  contractName: string,
): PromptDescriptor {
  const descriptor = byOperation.get(operation);
  if (!descriptor) throw new Error("agent_prompt_not_found");
  if (descriptor.contract_name === contractName) return descriptor;
  if (!concreteContractFamilies.get(operation)?.has(contractName)) {
    throw new Error("agent_prompt_contract_mismatch");
  }
  const systemPrompt = descriptor.system_prompt.replace(
    `Return exactly the ${descriptor.contract_name} contract`,
    `Return exactly the ${contractName} contract`,
  );
  return Object.freeze({
    ...descriptor,
    contract_name: contractName,
    prompt_digest: createHash("sha256").update(systemPrompt, "utf8").digest("hex"),
    system_prompt: systemPrompt,
  });
}

function instructionForOperation(operation: string): string {
  if (operation === "decide_turn_intent") {
    return [
      "Classify one user turn into ordinary_conversation, guided_production, targeted_authoring, or quick_media.",
      "Return only creative intent, exact-evidence explicit element presence, an optional bounded requirement_patch, and an optional bounded assistant message.",
      "Represent explicit_elements as one strict object with only the optional product, prop, character, scene, world_setting, script, storyboard, video, and audio keys. Every present key must contain presence and an exact source_quote.",
      "Represent requirement controls as a controls_to_set object keyed by canonical control name. Every present control must contain its correctly typed value and exact source_quote; audio_mode is exactly none, bgm_only, or full.",
      "Represent each directive as either scope_kind global without capability_id or scope_kind capability with exactly one registered capability_id.",
      "Every control, directive, element decision, and conflict must quote an exact substring from context.user_input; never translate or paraphrase source_quote.",
      "Do not author directive IDs, conflict identities, revisions, provenance, defaults, workflow state, or provider actions. Approximate values are preference directives, not hard controls.",
      "Use requirement_patch only for durable creative or output facts supported by exact current-message quotes. Never emit continue, pause, skip, defer, resume, hold, reuse-existing-Drafts, stage-ordering, execution-timing, retry, or export mechanics as Requirement directives; express transient intent through routing or objective, or leave it to the supplied typed action.",
      "Do not choose an Agent identity, Node type, candidate count, revision, or provider action.",
    ].join(" ");
  }
  if (operation === "decide_next_action") {
    return [
      "Choose exactly one next action from ask_user, author_decision_bundle, invoke_capability, reply, or finish.",
      "Use author_decision_bundle with one bounded objective when several independent creative decisions should be answered together.",
      "When invoking, copy one capability_id from context.policy.allowed_capabilities and provide one bounded objective.",
      "Treat recommended_capabilities as advice and do not invent an unavailable capability.",
    ].join(" ");
  }
  if (operation === "compile_video_parameters") {
    return [
      "Extract only explicit technical video controls from the supplied target prompt and direct Text or Script Binding sources.",
      "Allowed fields are duration_seconds, resolution, aspect_ratio, and generate_audio, limited by the supplied capability contract.",
      "Copy source identity exactly. Return no_explicit_controls when no supplied source explicitly states a control.",
      "Do not infer controls from creative wording, defaults, sibling nodes, or transitive nodes.",
    ].join(" ");
  }
  if (operation === "command_replan") {
    return "Repair one stale command plan from the supplied original intent, bounded plan summary, target summaries, and conflict metadata without changing targets implicitly.";
  }
  if (operation === "workflow_conversation") {
    return "Answer the current workflow conversation turn using only the bounded current context. Do not silently create or modify Canvas state.";
  }
  if (operation === "conversation_summary") {
    return "Summarize only durable facts and unresolved objectives needed by a later turn. Exclude private reasoning and unrelated history.";
  }
  if (operation === "author_decision_bundle") {
    return [
      "Author one adaptive Decision Bundle containing one to five independent questions and two to six options per question.",
      "Use only creative_directive, set_control, or set_element_presence effects and only canonical values available in the supplied context.",
      "Return wording and bounded effects only. Never author Bundle, question, option, Node, Binding, persistence, provider, path, credential, revision, or platform identities.",
    ].join(" ");
  }
  if (operation === "plan_storyboard_sequence_outline") {
    return "Return only compact ordered segment timing, narrative states, and continuity facts. Do not author panel rows, provider prompts, or platform identifiers.";
  }
  if (operation === "materialize_storyboard_segment") {
    return "Materialize only the supplied storyboard segment as exactly nine ordered rows and one segment-local generation prompt. Preserve the supplied prior end state and terminal policy; do not author platform identifiers.";
  }
  if (operation.startsWith("propose_") && operation.endsWith("_options")) {
    return [
      "Return only concise creative options with title, public_summary, and one to six key_decisions.",
      "Do not return provider prompts, Draft seeds, detailed storyboard panels, or output for another production stage.",
    ].join(" ");
  }
  if (operation.startsWith("revise_") && operation.endsWith("_options")) {
    return [
      "Revise only the supplied capability options and return concise replacement typed options.",
      "Do not publish, select, or mutate platform state.",
    ].join(" ");
  }
  if (operation.startsWith("free_")) {
    return "Return one bounded prompt plan for the requested single-output media kind using only approved references and supplied deterministic constraints. Do not submit media generation.";
  }
  if (operation === "materialize_quick_media") {
    return [
      "Expand only the selected option into the requested capability Materialization result.",
      "Use only the bounded capability context and accepted reference summaries.",
      "Return creative content only; never emit Node identity, status, model selection, execution parameters, Bindings, reference IDs, paths, or provider payloads.",
    ].join(" ");
  }
  if (operation === "execute_canvas_text") {
    return "Return the bounded Text Node result requested by the current instruction without selecting another capability or modifying other Nodes.";
  }
  if (operation === "execute_canvas_script") {
    return "Return one complete editable Script Node result under the supplied contract and deterministic timing constraints.";
  }
  return `Perform only the ${operation} operation using its typed context, trusted internal Skill when declared, approved references, and exact result schema.`;
}
