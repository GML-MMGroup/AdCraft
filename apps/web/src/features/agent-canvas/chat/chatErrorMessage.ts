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
