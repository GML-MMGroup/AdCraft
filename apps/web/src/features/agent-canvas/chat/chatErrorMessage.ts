const ERROR_COPY: Readonly<Record<string, string>> = {
  agent_runtime_unavailable:
    "The agent runtime is temporarily unavailable. Your input is preserved; try again shortly.",
  agent_deadline_exceeded:
    "The agent took too long to respond. Your input is preserved; retry when ready.",
  guidance_completion_invalid:
    "The guidance session is not ready to finish yet.",
  journey_transition_invalid:
    "This action is not valid in the current production stage.",
  journey_revision_conflict:
    "The production stage changed. The latest session was loaded; review it and try again.",
  journey_foundation_queue_invalid:
    "The production requirements changed. Review the latest decisions and try again.",
  journey_action_in_progress:
    "The current production step is still in progress.",
  journey_policy_unsupported:
    "This project uses an unsupported production journey. Create a new project with the current workflow contract.",
  journey_stage_action_mismatch:
    "This action no longer belongs to the current production stage. The latest state has been loaded.",
  journey_stage_exclusion_not_allowed:
    "This required production stage cannot be excluded.",
  journey_custom_input_invalid:
    "The custom direction is incomplete or too long. Revise it and submit again.",
  guidance_orphaned_stall:
    "The guided step lost its active operation. Refresh the conversation before retrying.",
  parent_materialization_missing:
    "The required parent draft is not available yet.",
  parent_materialization_revision_stale:
    "The parent draft changed while its derived draft was being prepared. Refresh and retry.",
  derived_materialization_conflict:
    "The derived draft conflicts with the latest parent state. Refresh and retry.",
  required_binding_missing:
    "A required upstream reference is missing. Reconnect or replace it before running this node.",
  role_reference_mismatch:
    "One of the connected references is not valid for this node role.",
  node_prompt_preparation_incomplete:
    "The generation prompt is still being prepared. Wait for it to become Ready before running the node.",
  journey_evidence_invalid:
    "The production state could not be verified. Refresh and try again.",
  requirement_ledger_not_found:
    "This older project is missing its Requirement Ledger. Its conversation cannot be restored until the project data is repaired.",
  requirement_persistence_failed:
    "This project's Requirement Ledger does not match its saved snapshot. Backend data repair is required before the conversation can be restored.",
};

export function agentCanvasChatErrorMessage(
  code: string,
  backendMessage: string | null,
): string {
  const message = backendMessage?.trim() || ERROR_COPY[code] || "The agent could not complete this request.";
  return `${code}: ${message}`;
}
