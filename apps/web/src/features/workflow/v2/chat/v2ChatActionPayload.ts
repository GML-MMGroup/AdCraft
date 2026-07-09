import type { FrontDeskMessage } from "../../../../types.ts";
import type { V2ChatActionMode, V2ChatActionRequest, WorkflowV2ChatTarget } from "../../../../types-v2.ts";
import type { V2StructuredChatTarget } from "../operations/v2SlotOperationTypes.ts";

export type V2ChatActionPayloadMode = "auto" | "revise_prompt" | "revise_and_generate" | "select_version" | "discard_working";

type BuildV2ChatActionPayloadInput = {
  message: string;
  actionMode?: V2ChatActionPayloadMode | V2ChatActionMode;
  selectedTarget?: WorkflowV2ChatTarget | V2StructuredChatTarget | null;
  explicitTargets?: Array<WorkflowV2ChatTarget | V2StructuredChatTarget>;
  assetLocators?: string[];
  attachments?: V2ChatActionRequest["attachments"];
  history?: FrontDeskMessage[];
  context?: Record<string, unknown>;
};

export function inferV2ChatActionMode(message: string): V2ChatActionMode {
  return /生成|重生|重新出|再来一版|generate|regenerate/i.test(message) ? "revise_and_generate" : "revise_prompt";
}

export function buildV2ChatActionPayload(input: BuildV2ChatActionPayloadInput): V2ChatActionRequest {
  const explicitTargets = dedupeTargets(input.explicitTargets ?? []);
  const target = input.selectedTarget ? toWorkflowV2ChatTarget(input.selectedTarget) : explicitTargets[0] ?? null;
  const targetReferences = explicitTargets.length ? explicitTargets : target ? [target] : [];
  const actionMode = input.actionMode === "auto" || !input.actionMode ? inferV2ChatActionMode(input.message) : input.actionMode;
  return {
    message: input.message,
    action_mode: actionMode,
    target,
    target_references: targetReferences,
    asset_locators: input.assetLocators ?? [],
    history: input.history,
    attachments: input.attachments ?? [],
    context: input.context,
  };
}

function dedupeTargets(targets: Array<WorkflowV2ChatTarget | V2StructuredChatTarget>) {
  const byKey = new Map<string, WorkflowV2ChatTarget>();
  for (const target of targets) {
    const normalized = toWorkflowV2ChatTarget(target);
    byKey.set(targetKey(normalized), normalized);
  }
  return Array.from(byKey.values());
}

function toWorkflowV2ChatTarget(target: WorkflowV2ChatTarget | V2StructuredChatTarget): WorkflowV2ChatTarget {
  return {
    target_type: target.target_type,
    node_id: target.node_id ?? null,
    item_id: target.item_id ?? null,
    slot_id: target.slot_id ?? null,
    asset_id: target.asset_id ?? null,
    version_id: target.version_id ?? null,
  };
}

function targetKey(target: WorkflowV2ChatTarget) {
  return [
    target.target_type,
    target.node_id ?? "",
    target.item_id ?? "",
    target.slot_id ?? "",
    target.asset_id ?? "",
    target.version_id ?? "",
  ].join(":");
}
