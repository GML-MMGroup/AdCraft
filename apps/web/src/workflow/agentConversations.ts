import type {
  AgentConversationActionResponse,
  AgentConversationEvent,
  AgentConversationEventsResponse,
  AgentConversationSuggestedAction,
  AgentConversationVisibleAgent,
} from "../types";

export const VISIBLE_AGENT_LABELS: Record<AgentConversationVisibleAgent, string> = {
  creative_director: "Creative Director",
  script_writer: "Script Writer",
  character_designer: "Character Designer",
  scene_designer: "Scene Designer",
  storyboard_artist: "Storyboard Artist",
  video_director: "Video Director",
  sound_director: "Sound Director",
  final_composition_assistant: "Final Composition Assistant",
};

export const VISIBLE_AGENT_IDS = Object.keys(VISIBLE_AGENT_LABELS) as AgentConversationVisibleAgent[];

export function isVisibleAgent(agent: unknown): agent is AgentConversationVisibleAgent {
  return typeof agent === "string" && agent in VISIBLE_AGENT_LABELS;
}

export function agentConversationLabel(agent: unknown) {
  return isVisibleAgent(agent) ? VISIBLE_AGENT_LABELS[agent] : "Agent";
}

export function appendConversationEvent(events: AgentConversationEvent[], event: AgentConversationEvent) {
  const key = conversationEventKey(event);
  if (events.some((item) => conversationEventKey(item) === key)) return events;
  return [...events, event];
}

export function appendConversationEvents(events: AgentConversationEvent[], nextEvents: AgentConversationEvent[]) {
  return nextEvents.reduce((current, event) => appendConversationEvent(current, event), events);
}

export function conversationEventsFromResponse(response: AgentConversationEventsResponse) {
  const actionsById = new Map(response.suggested_actions.map((action) => [action.action_id, action]));
  const hydratedEvents = response.events.map((event) => hydrateEventAction(event, actionsById));
  const eventActionIds = new Set(hydratedEvents.map(conversationActionIdFromEvent).filter((actionId): actionId is string => Boolean(actionId)));
  const suggestedActionEvents = response.suggested_actions
    .filter((action) => !eventActionIds.has(action.action_id))
    .map((action) => suggestedActionToEvent(response.conversation_id, action));
  return appendConversationEvents(hydratedEvents, suggestedActionEvents);
}

export function conversationEventsFromActionResponse(response: AgentConversationActionResponse) {
  const actionsById = new Map([[response.action.action_id, response.action]]);
  return response.events.map((event) => hydrateEventAction(event, actionsById));
}

export function conversationActionFromEvent(event: AgentConversationEvent): AgentConversationSuggestedAction | null {
  const action = event.metadata?.action;
  if (!action || typeof action !== "object") return null;
  const actionRecord = action as Partial<AgentConversationSuggestedAction>;
  return actionRecord.action_id ? (actionRecord as AgentConversationSuggestedAction) : null;
}

export function actionStatusFromEvents(events: AgentConversationEvent[], action: AgentConversationSuggestedAction) {
  const explicitStatus = events
    .map(conversationActionFromEvent)
    .find((eventAction) => eventAction?.action_id === action.action_id)?.status;
  if (explicitStatus && explicitStatus !== "pending") return explicitStatus;
  const actionEvents = events.filter((event) => conversationActionIdFromEvent(event) === action.action_id);
  if (actionEvents.some((event) => event.event_type === "action_applied" || event.event_type === "chat_action_applied")) return "applied";
  if (actionEvents.some((event) => event.event_type === "action_rejected" || event.event_type === "chat_action_rejected")) return "rejected";
  if (actionEvents.some((event) => event.event_type === "chat_action_failed" || event.event_type === "error")) return "failed";
  return action.status;
}

export function suggestedActionToEvent(conversationId: string, action: AgentConversationSuggestedAction): AgentConversationEvent {
  return {
    event_id: `suggested_${conversationId}_${action.action_id}`,
    conversation_id: conversationId,
    event_type: "suggested_action",
    speaker_agent: action.speaker_agent,
    workflow_id: action.workflow_id,
    target_node_id: action.target_node_id,
    target_node_type: action.target_node_type,
    text: action.summary || action.title,
    created_at: action.created_at,
    metadata: {
      action,
    },
  };
}

export function conversationEventKey(event: AgentConversationEvent) {
  return event.event_id || `${event.conversation_id}:${event.event_type}:${event.created_at}:${event.text}`;
}

function hydrateEventAction(event: AgentConversationEvent, actionsById: Map<string, AgentConversationSuggestedAction>) {
  const actionId = conversationActionIdFromEvent(event);
  const action = actionId ? actionsById.get(actionId) : null;
  if (!action) return event;
  return {
    ...event,
    metadata: {
      ...event.metadata,
      action,
    },
  };
}

function conversationActionIdFromEvent(event: AgentConversationEvent) {
  const action = conversationActionFromEvent(event);
  if (action?.action_id) return action.action_id;
  const actionId = event.metadata?.action_id;
  return typeof actionId === "string" && actionId.trim() ? actionId.trim() : null;
}
