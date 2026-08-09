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
      `Return exactly the ${operation.result_contract_name} contract by calling submit_structured_result.`,
      "If Python rejects the first submission, repair only the reported structured violations and submit once more. A second rejection is terminal.",
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
      "Return only creative intent, explicit element presence, explicit constraints, and an optional bounded assistant message.",
      "Do not choose an Agent identity, Node type, candidate count, revision, or provider action.",
    ].join(" ");
  }
  if (operation === "decide_next_action") {
    return [
      "Choose exactly one next action from ask_user, invoke_capability, reply, or finish.",
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
  if (operation.startsWith("propose_") && operation.endsWith("_options")) {
    return [
      "Return concise creative options with title, public_summary, one to six key_decisions, and one matching private_draft_seed per option.",
      "The private_draft_seed contains only the capability-specific creative facts required by the typed result contract.",
      "Do not place platform identity, identifiers, Node state, Bindings, references, provider parameters, paths, or credentials in the Seed.",
    ].join(" ");
  }
  if (operation.startsWith("revise_") && operation.endsWith("_options")) {
    return [
      "Revise only the supplied capability options and return replacement typed options with one matching private_draft_seed per option.",
      "Keep each Seed limited to capability-specific creative facts; exclude platform identity, identifiers, Node state, Bindings, references, provider parameters, paths, and credentials.",
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
