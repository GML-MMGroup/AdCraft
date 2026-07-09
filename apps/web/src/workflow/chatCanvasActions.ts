import type { AgentConversationEvent } from "../types";

export type ChatCanvasActionKind = "prompt_only" | "update_and_run" | "run_only" | "error" | "none";

export function chatCanvasActionKind(events: AgentConversationEvent[]): ChatCanvasActionKind {
  const hasPromptUpdate = events.some((event) => event.event_type === "node_prompt_updated");
  const hasExecutionStarted = events.some((event) => event.event_type === "execution_started");
  if (hasPromptUpdate && hasExecutionStarted) return "update_and_run";
  if (hasPromptUpdate) return "prompt_only";
  if (hasExecutionStarted) return "run_only";
  if (events.some((event) => event.event_type === "error")) return "error";
  return "none";
}

export function chatCanvasExecutionId(event: AgentConversationEvent) {
  const metadata = metadataRecord(event);
  const execution = recordFromUnknown(metadata.execution);
  return (
    stringFromUnknown(metadata.execution_id) ||
    stringFromUnknown(metadata.workflow_execution_id) ||
    stringFromUnknown(execution?.execution_id) ||
    stringFromUnknown(execution?.id)
  );
}

export function chatCanvasActiveExecutionId(event: AgentConversationEvent) {
  const metadata = metadataRecord(event);
  const activeExecution = recordFromUnknown(metadata.active_execution);
  return (
    stringFromUnknown(metadata.active_execution_id) ||
    chatCanvasExecutionId(event) ||
    stringFromUnknown(activeExecution?.execution_id) ||
    stringFromUnknown(activeExecution?.id)
  );
}

export function chatCanvasErrorCode(event: AgentConversationEvent) {
  const metadata = metadataRecord(event);
  return stringFromUnknown(metadata.code) || stringFromUnknown(metadata.error_code);
}

export function chatCanvasRefreshHints(event: AgentConversationEvent) {
  const refresh = metadataRecord(event).refresh;
  return Array.isArray(refresh)
    ? refresh.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

export function isChatCanvasExecutionConflictCode(code?: string | null) {
  return code === "execution_already_running" || code === "workflow_execution_already_running";
}

export function isChatCanvasActionRuntimeEvent(type: string) {
  return type === "chat_action_created" || type === "chat_action_applied" || type === "chat_action_rejected" || type === "chat_action_failed";
}

export function isChatCanvasPromptRuntimeEvent(type: string) {
  return type === "node_prompt_updated" || type === "item_prompt_updated";
}

export function isChatCanvasRevisionRuntimeEvent(type: string) {
  return type === "revision_started" || type === "revision_waiting" || type === "revision_completed" || type === "revision_failed";
}

function metadataRecord(event: AgentConversationEvent) {
  return recordFromUnknown(event.metadata) ?? {};
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
