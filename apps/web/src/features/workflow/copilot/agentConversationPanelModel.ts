import { agentConversationLabel } from "../../../workflow/agentConversations.ts";
import type { NodeMentionOption } from "../../../workflow/nodeMentions.ts";
import type {
  AgentConversation,
  AgentConversationEvent,
  AgentConversationSuggestedAction,
  FrontDeskMessage,
  UploadedAsset,
} from "../../../types";

export function createUserConversationEvent(conversationId: string, message: string, workflowId?: string | null, nodeId?: string | null): AgentConversationEvent {
  return {
    event_id: `local_user_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    conversation_id: conversationId,
    event_type: "agent_message",
    workflow_id: workflowId ?? undefined,
    target_node_id: nodeId ?? undefined,
    text: message,
    created_at: new Date().toISOString(),
    metadata: {
      role: "user",
      local_optimistic: true,
    },
  };
}

export function createClientConversationErrorEvent(
  conversationId: string,
  message: string,
  action?: AgentConversationSuggestedAction,
): AgentConversationEvent {
  return {
    event_id: `client_error_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    conversation_id: conversationId,
    event_type: "error",
    speaker_agent: "creative_director",
    workflow_id: action?.workflow_id,
    target_node_id: action?.target_node_id,
    target_node_type: action?.target_node_type,
    text: message,
    created_at: new Date().toISOString(),
    metadata: {
      code: "frontend_request_failed",
      action_id: action?.action_id,
      action_type: action?.action_type,
    },
  };
}

export function frontDeskConversationId(workflowId: string) {
  return `front_desk:${workflowId}`;
}

export function isFrontDeskBridgeConversationId(conversationId?: string | null) {
  return Boolean(conversationId?.startsWith("front_desk:"));
}

export function createFrontDeskBridgeConversation(workflowId: string, conversationId = frontDeskConversationId(workflowId)): AgentConversation {
  const now = new Date().toISOString();
  return {
    conversation_id: conversationId,
    workflow_id: workflowId,
    focus_node_id: null,
    topic: "Initial brief",
    status: "active",
    created_at: now,
    updated_at: now,
    events: [],
    suggested_actions: [],
  };
}

export function frontDeskMessagesAsConversationEvents(
  messages: FrontDeskMessage[],
  options: { conversationId?: string; workflowId?: string | null; bridge?: boolean } = {},
): AgentConversationEvent[] {
  const conversationId = options.conversationId ?? "front_desk";
  return messages.map((message, index) => ({
    event_id: `${conversationId}_${message.role}_${index}`,
    conversation_id: conversationId,
    event_type: "agent_message",
    speaker_agent: message.role === "assistant" ? "creative_director" : undefined,
    workflow_id: options.workflowId ?? undefined,
    text: message.content,
    created_at: new Date(index).toISOString(),
    metadata: {
      role: message.role,
      ...(options.bridge ? { source: "front_desk_bridge" } : {}),
    },
  }));
}

export function prioritizeNodeMentionOptions(options: NodeMentionOption[], selectedNodeId?: string | null) {
  if (!selectedNodeId) return options;
  return [...options].sort((a, b) => Number(b.node_id === selectedNodeId) - Number(a.node_id === selectedNodeId));
}

export function conversationEventMetadata(event: AgentConversationEvent) {
  return recordFromUnknown(event.metadata) ?? {};
}

export function conversationEventCode(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  return stringFromUnknown(metadata.code) || stringFromUnknown(metadata.error_code);
}

export function conversationEventTargetNodeId(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const nodeReference = recordFromUnknown(metadata.node_reference);
  const target = recordFromUnknown(metadata.target);
  const revision = recordFromUnknown(metadata.revision);
  return (
    stringFromUnknown(event.target_node_id) ||
    stringFromUnknown(metadata.target_node_id) ||
    stringFromUnknown(target?.node_id) ||
    stringFromUnknown(revision?.node_id) ||
    stringFromUnknown(nodeReference?.node_id)
  );
}

export function conversationEventTargetItemId(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const eventRecord = event as AgentConversationEvent & Record<string, unknown>;
  const target = recordFromUnknown(metadata.target);
  const revision = recordFromUnknown(metadata.revision);
  const itemReference = recordFromUnknown(metadata.item_reference);
  return (
    stringFromUnknown(eventRecord.target_item_id) ||
    stringFromUnknown(metadata.target_item_id) ||
    stringFromUnknown(metadata.item_id) ||
    stringFromUnknown(metadata.target_entity_id) ||
    stringFromUnknown(target?.item_id) ||
    stringFromUnknown(target?.target_item_id) ||
    stringFromUnknown(target?.target_entity_id) ||
    stringFromUnknown(itemReference?.item_id) ||
    stringFromUnknown(revision?.target_entity_id)
  );
}

export function conversationEventSemanticType(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const target = recordFromUnknown(metadata.target);
  const revision = recordFromUnknown(metadata.revision);
  return (
    stringFromUnknown(metadata.semantic_type) ||
    stringFromUnknown(target?.semantic_type) ||
    stringFromUnknown(revision?.semantic_type)
  );
}

export function conversationEventPromptText(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const item = recordFromUnknown(metadata.item);
  const target = recordFromUnknown(metadata.target);
  return (
    stringFromUnknown(metadata.prompt) ||
    stringFromUnknown(metadata.item_prompt) ||
    stringFromUnknown(item?.prompt) ||
    stringFromUnknown(item?.item_prompt) ||
    stringFromUnknown(target?.prompt) ||
    stringFromUnknown(target?.item_prompt)
  );
}

export function conversationEventRevisionId(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const revision = recordFromUnknown(metadata.revision);
  return (
    stringFromUnknown(metadata.revision_id) ||
    stringFromUnknown(revision?.revision_id) ||
    stringFromUnknown(revision?.id)
  );
}

export function conversationEventRevisionStatus(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const revision = recordFromUnknown(metadata.revision);
  const explicitStatus = stringFromUnknown(metadata.status) || stringFromUnknown(revision?.status) || stringFromUnknown(revision?.generation_status);
  if (explicitStatus) return explicitStatus;
  if (event.event_type === "revision_waiting") return "waiting";
  if (event.event_type === "revision_completed") return "completed";
  if (event.event_type === "revision_failed") return "failed";
  return "running";
}

export function isRevisionConversationEventType(eventType: AgentConversationEvent["event_type"]) {
  return eventType === "revision_started" || eventType === "revision_waiting" || eventType === "revision_completed" || eventType === "revision_failed";
}

export function revisionConversationEventStatusText(eventType: AgentConversationEvent["event_type"]) {
  if (eventType === "revision_waiting") return "Item regeneration is waiting for media results";
  if (eventType === "revision_completed") return "Item regeneration completed";
  if (eventType === "revision_failed") return "Item regeneration failed";
  return "Item regeneration started";
}

export function assetTypeForRevisionSemanticType(semanticType: string): UploadedAsset["asset_type"] {
  const normalized = semanticType.toLowerCase();
  if (normalized.includes("video")) return "video";
  if (normalized === "bgm" || normalized.includes("audio") || normalized.includes("music")) return "audio";
  return "image";
}

export function conversationEventExecutionId(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  return stringFromUnknown(metadata.execution_id) || stringFromUnknown(metadata.active_execution_id);
}

export function conversationEventStringArray(event: AgentConversationEvent, key: string) {
  const value = conversationEventMetadata(event)[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

export function conversationEventDirectorContextVersion(event: AgentConversationEvent) {
  const value = conversationEventMetadata(event).director_context_version;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return stringFromUnknown(value);
}

export function conversationEventCandidateTargets(event: AgentConversationEvent) {
  const value = conversationEventMetadata(event).candidate_targets;
  if (!Array.isArray(value)) return [];
  return value
    .map((candidate, index) => {
      const record = recordFromUnknown(candidate);
      if (!record) return null;
      const targetType = stringFromUnknown(record.target_type);
      const nodeId = stringFromUnknown(record.node_id);
      const itemId = stringFromUnknown(record.item_id) || stringFromUnknown(record.target_item_id) || stringFromUnknown(record.target_entity_id);
      const assetId = stringFromUnknown(record.asset_id);
      const semanticType = stringFromUnknown(record.semantic_type);
      const label =
        stringFromUnknown(record.mention_text) ||
        stringFromUnknown(record.display_name) ||
        stringFromUnknown(record.name) ||
        itemId ||
        assetId ||
        nodeId ||
        `Target ${index + 1}`;
      const meta = [targetType, nodeId, itemId, assetId, semanticType].filter(Boolean).join(" · ");
      return {
        key: [targetType, nodeId, itemId, assetId, index].filter(Boolean).join(":"),
        label,
        meta,
      };
    })
    .filter((candidate): candidate is { key: string; label: string; meta: string } => Boolean(candidate));
}

export function conversationEventMemorySummary(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const focusTarget = recordFromUnknown(metadata.focus_target);
  const targetLabel =
    stringFromUnknown(metadata.target_label) ||
    stringFromUnknown(metadata.display_name) ||
    stringFromUnknown(focusTarget?.display_name) ||
    stringFromUnknown(focusTarget?.item_id) ||
    stringFromUnknown(focusTarget?.asset_id) ||
    stringFromUnknown(focusTarget?.node_id) ||
    stringFromUnknown(focusTarget?.target_type);
  const fallbackMessage = targetLabel
    ? `Conversation memory noted ${targetLabel}.`
    : "Conversation memory updated.";
  return {
    message: event.text || fallbackMessage,
    statusText: event.text || fallbackMessage,
    targetLabel,
  };
}

export function conversationEventSpecialistResultSummary(event: AgentConversationEvent) {
  const metadata = conversationEventMetadata(event);
  const target = recordFromUnknown(metadata.target);
  const resultType = stringFromUnknown(metadata.result_type);
  const targetLabel =
    stringFromUnknown(metadata.target_label) ||
    stringFromUnknown(metadata.display_name) ||
    stringFromUnknown(target?.display_name) ||
    stringFromUnknown(target?.item_id) ||
    stringFromUnknown(target?.asset_id) ||
    stringFromUnknown(target?.node_id) ||
    stringFromUnknown(event.target_node_id);
  const qualityNotes = conversationEventQualityNotes(event);
  const qualityNotesCount = numberFromUnknown(metadata.quality_notes_count) ?? qualityNotes.length;
  const specialistLabel = agentConversationLabel(event.speaker_agent);
  const fallbackMessage = resultType
    ? `${specialistLabel} returned ${resultType.replace(/_/g, " ")}.`
    : `${specialistLabel} shared a specialist result.`;
  return {
    message: event.text || fallbackMessage,
    statusText: event.text || fallbackMessage,
    targetLabel,
    resultType: resultType ? resultType.replace(/_/g, " ") : "",
    qualityNotesCount,
    qualityNotes,
  };
}

export function conversationEventQualityNotes(event: AgentConversationEvent) {
  const value = conversationEventMetadata(event).quality_notes;
  if (typeof value === "string" && value.trim()) return [value.trim()].slice(0, 2);
  if (!Array.isArray(value)) return [];
  return value
    .map((note) => {
      if (typeof note === "string") return note.trim();
      const record = recordFromUnknown(note);
      return stringFromUnknown(record?.message) || stringFromUnknown(record?.summary) || stringFromUnknown(record?.note);
    })
    .filter(Boolean)
    .slice(0, 2);
}

export function conversationEventWarnings(event: AgentConversationEvent) {
  const value = conversationEventMetadata(event).warnings;
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (!Array.isArray(value)) return [];
  return value
    .map((warning) => {
      if (typeof warning === "string") return warning.trim();
      const record = recordFromUnknown(warning);
      return stringFromUnknown(record?.code) || stringFromUnknown(record?.message) || stringFromUnknown(record?.warning);
    })
    .filter(Boolean);
}

export function conversationEventRouteMetadata(event: AgentConversationEvent): Array<[string, string]> {
  const metadata = conversationEventMetadata(event);
  const route = recordFromUnknown(metadata.agent_route_snapshot);
  const values: Array<[string, string | null]> = [
    ["specialist", stringFromUnknown(metadata.specialist) || stringFromUnknown(route?.specialist)],
    ["action_mode", stringFromUnknown(metadata.action_mode)],
    ["updated_prompt_scope", stringFromUnknown(metadata.updated_prompt_scope)],
    ["owner_node_id", stringFromUnknown(route?.owner_node_id)],
    ["owner_item_id", stringFromUnknown(route?.owner_item_id)],
    ["owner_slot_id", stringFromUnknown(route?.owner_slot_id)],
    ["generation_mode", stringFromUnknown(route?.generation_mode)],
    ["materializer_version", stringFromUnknown(route?.materializer_version)],
  ];
  const counts: Array<[string, unknown]> = [
    ["executed_slot_ids", metadata.executed_slot_ids],
    ["asset_ids", metadata.asset_ids],
    ["version_ids", metadata.version_ids],
    ["provider_calls", metadata.provider_calls],
  ];
  for (const [label, value] of counts) {
    if (Array.isArray(value) && value.length) values.push([label, String(value.length)]);
  }
  return values.filter((entry): entry is [string, string] => Boolean(entry[1]));
}

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberFromUnknown(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return undefined;
}
