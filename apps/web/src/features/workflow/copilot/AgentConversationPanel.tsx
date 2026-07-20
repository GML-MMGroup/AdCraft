import { PromptComposer, type PromptGenerateContext } from "../../../components/PromptComposer";
import {
  actionStatusFromEvents,
  agentConversationLabel,
  conversationActionFromEvent,
  isVisibleAgent,
} from "../../../workflow/agentConversations.ts";
import { PROMPT_TO_WORKFLOW_PRODUCT_UPLOAD_OPTIONS } from "../../../workflow/assetMentions.ts";
import { nodeMentionErrorMessage, type NodeMentionOption } from "../../../workflow/nodeMentions.ts";
import {
  conversationEventCandidateTargets,
  conversationEventCode,
  conversationEventDirectorContextVersion,
  conversationEventExecutionId,
  conversationEventMemorySummary,
  conversationEventRouteMetadata,
  conversationEventSpecialistResultSummary,
  conversationEventTargetItemId,
  conversationEventWarnings,
  isRevisionConversationEventType,
  revisionConversationEventStatusText,
} from "./agentConversationPanelModel.ts";
import type {
  AgentConversation,
  AgentConversationEvent,
  AgentConversationSuggestedAction,
  AgentConversationVisibleAgent,
  AssetLibraryReference,
  CanvasTargetReference,
  ChatNodeReference,
} from "../../../types";
import type { V2InputAssetUploadItem } from "../../../types-v2.ts";

export type ConversationActionTarget = {
  key: string;
  target_type: string;
  node_id?: string | null;
  item_id?: string | null;
  asset_id?: string | null;
  semantic_type?: string | null;
  label: string;
  meta: string;
};

function recordFromUnknown(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function recordArrayFromUnknown(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.flatMap((item): Record<string, unknown>[] => {
      const record = recordFromUnknown(item);
      return record ? [record] : [];
    })
    : [];
}

function stringFromUnknown(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberFromUnknown(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return undefined;
}

export type AgentConversationPanelProps = {
  conversations: AgentConversation[];
  activeConversationId: string | null;
  events: AgentConversationEvent[];
  workflowId?: string | null;
  focusNodeId?: string | null;
  loading: boolean;
  sending: boolean;
  error?: string | null;
  collapsed: boolean;
  actionBusyById: Record<string, "apply" | "reject" | undefined>;
  mentionReferences: AssetLibraryReference[];
  mentionNodeReferences: ChatNodeReference[];
  mentionTargetReferences: CanvasTargetReference[];
  nodeMentionOptions: NodeMentionOption[];
  onUploadInputAsset?: (file: File) => Promise<V2InputAssetUploadItem[]>;
  onMentionReferencesChange: (references: AssetLibraryReference[]) => void;
  onMentionNodeReferencesChange: (references: ChatNodeReference[]) => void;
  onMentionTargetReferencesChange: (references: CanvasTargetReference[]) => void;
  onToggleCollapsed: () => void;
  onSelectConversation: (conversationId: string) => void;
  onCreateConversation: () => void;
  onSendMessage: (prompt: string, context?: PromptGenerateContext) => void | Promise<void>;
  onApplyAction: (action: AgentConversationSuggestedAction) => void;
  onRejectAction: (action: AgentConversationSuggestedAction) => void;
  onSelectActionTarget: (target: ConversationActionTarget) => void;
};

export function AgentConversationPanel({
  conversations,
  activeConversationId,
  events,
  workflowId,
  focusNodeId,
  loading,
  sending,
  error,
  collapsed,
  actionBusyById,
  mentionReferences,
  mentionNodeReferences,
  mentionTargetReferences,
  nodeMentionOptions,
  onUploadInputAsset,
  onMentionReferencesChange,
  onMentionNodeReferencesChange,
  onMentionTargetReferencesChange,
  onToggleCollapsed,
  onSelectConversation,
  onCreateConversation,
  onSendMessage,
  onApplyAction,
  onRejectAction,
  onSelectActionTarget,
}: AgentConversationPanelProps) {
  const activeConversation = conversations.find((conversation) => conversation.conversation_id === activeConversationId);

  return (
    <>
      <div className="copilot-title">
        <div>
          <h2>Creative Director</h2>
          <span className="conversation-panel-subtitle">{activeConversation?.topic ?? (workflowId ? "Canvas control" : "Ad workflow planning")}</span>
        </div>
        <button className="small-action" type="button" onClick={onToggleCollapsed}>
          {collapsed ? "Open" : "Collapse"}
        </button>
      </div>

      <div className="conversation-panel-body">
        <div className="conversation-list" aria-label="Agent conversations">
          {conversations.map((conversation) => (
            <button
              key={conversation.conversation_id}
              className={conversation.conversation_id === activeConversationId ? "is-active" : ""}
              type="button"
              onClick={() => onSelectConversation(conversation.conversation_id)}
            >
              <strong>{conversation.topic}</strong>
              <span>{conversation.focus_node_id ? `node ${conversation.focus_node_id}` : "workflow"}</span>
            </button>
          ))}
          <button className="conversation-new-button" type="button" disabled={!workflowId || loading} onClick={onCreateConversation}>
            New
          </button>
        </div>

        <div className="chat-stream conversation-event-stream" role="log">
          {loading ? <div className="bubble">Loading conversations...</div> : null}
          {!loading && !events.length ? <div className="bubble">{workflowId ? "Agent team is ready." : "Describe an ad to start a workflow."}</div> : null}
          {events.map((event) => (
            <AgentConversationEventView
              key={event.event_id}
              event={event}
              events={events}
              busy={actionBusyById}
              onApplyAction={onApplyAction}
              onRejectAction={onRejectAction}
              onSelectActionTarget={onSelectActionTarget}
            />
          ))}
        </div>
      </div>

      <div className="copilot-input conversation-input">
        {error ? <div className="conversation-error" role="alert">{error}</div> : null}
        <PromptComposer
          placeholder="Ask the agent team..."
          onGenerate={onSendMessage}
          compact
          assetMentionContext={{ workflowId, nodeId: focusNodeId }}
          mentionReferences={mentionReferences}
          mentionNodeReferences={mentionNodeReferences}
          mentionTargetReferences={mentionTargetReferences}
          nodeMentionOptions={nodeMentionOptions}
          uploadOptions={workflowId ? undefined : PROMPT_TO_WORKFLOW_PRODUCT_UPLOAD_OPTIONS}
          onUploadInputAsset={workflowId ? undefined : onUploadInputAsset}
          onMentionReferencesChange={onMentionReferencesChange}
          onMentionNodeReferencesChange={onMentionNodeReferencesChange}
          onMentionTargetReferencesChange={onMentionTargetReferencesChange}
        />
        {sending ? <span className="conversation-send-state">Sending...</span> : null}
      </div>
    </>
  );
}

function AgentConversationEventView({
  event,
  events,
  busy,
  onApplyAction,
  onRejectAction,
  onSelectActionTarget,
}: {
  event: AgentConversationEvent;
  events: AgentConversationEvent[];
  busy: Record<string, "apply" | "reject" | undefined>;
  onApplyAction: (action: AgentConversationSuggestedAction) => void;
  onRejectAction: (action: AgentConversationSuggestedAction) => void;
  onSelectActionTarget: (target: ConversationActionTarget) => void;
}) {
  if (event.speaker_agent && !isVisibleAgent(event.speaker_agent)) return null;
  if (event.target_agent && !isVisibleAgent(event.target_agent)) return null;
  if (event.event_type === "suggested_action" || event.event_type === "chat_action_created") {
    const action = conversationActionForEvent(event);
    return action ? (
      <ActionCard
        action={action}
        events={events}
        busy={busy[action.action_id]}
        onApply={() => onApplyAction(action)}
        onReject={() => onRejectAction(action)}
        onSelectTarget={onSelectActionTarget}
      />
    ) : null;
  }
  if (event.event_type === "agent_handoff") {
    return (
      <div className="conversation-event handoff">
        <span>{agentConversationLabel(event.speaker_agent)} invited {agentConversationLabel(event.target_agent)}.</span>
      </div>
    );
  }
  if (event.event_type === "clarification_requested") {
    const candidateTargets = conversationEventCandidateTargets(event);
    return (
      <div className="conversation-event clarification-requested">
        <AgentSpeakerBadge agent={event.speaker_agent ?? "creative_director"} />
        <p>{event.text || "Which canvas target should I update?"}</p>
        {candidateTargets.length ? (
          <div className="conversation-candidate-targets">
            {candidateTargets.map((target) => (
              <span key={target.key} className="conversation-candidate-target">
                <strong>{target.label}</strong>
                {target.meta ? <em>{target.meta}</em> : null}
              </span>
            ))}
          </div>
        ) : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "director_context_updated") {
    return (
      <div className="conversation-event director-context-updated">
        <AgentSpeakerBadge agent={event.speaker_agent ?? "creative_director"} />
        <span>{event.text || "Director context updated."}</span>
        {conversationEventDirectorContextVersion(event) ? <em>v{conversationEventDirectorContextVersion(event)}</em> : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "specialist_result") {
    const summary = conversationEventSpecialistResultSummary(event);
    const warnings = conversationEventWarnings(event);
    const routeMetadata = conversationEventRouteMetadata(event);
    return (
      <div className="conversation-event specialist-result">
        <AgentSpeakerBadge agent={event.speaker_agent} />
        <span>{summary.message}</span>
        <div className="conversation-specialist-meta">
          {summary.targetLabel ? <em>{summary.targetLabel}</em> : null}
          {summary.resultType ? <em>{summary.resultType}</em> : null}
          {summary.qualityNotesCount ? <em>{summary.qualityNotesCount} quality note{summary.qualityNotesCount === 1 ? "" : "s"}</em> : null}
          {warnings.length ? <span className="conversation-warning-badge">{warnings.length} warning{warnings.length === 1 ? "" : "s"}</span> : null}
        </div>
        {routeMetadata.length ? (
          <div className="conversation-route-meta" aria-label="Backend route metadata">
            {routeMetadata.map(([label, value]) => (
              <em key={label}>{label}: {value}</em>
            ))}
          </div>
        ) : null}
        {summary.qualityNotes.length ? (
          <ul className="conversation-quality-notes">
            {summary.qualityNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "conversation_memory_updated") {
    const summary = conversationEventMemorySummary(event);
    return (
      <div className="conversation-event memory-updated">
        <AgentSpeakerBadge agent={event.speaker_agent ?? "creative_director"} />
        <span>{summary.message}</span>
        {summary.targetLabel ? <em>{summary.targetLabel}</em> : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "action_applied" || event.event_type === "action_rejected" || event.event_type === "chat_action_applied" || event.event_type === "chat_action_rejected" || event.event_type === "chat_action_failed") {
    return (
      <div className={`conversation-event action-state ${event.event_type}`}>
        <span>{event.text}</span>
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "node_prompt_updated") {
    return (
      <div className="conversation-event node-prompt-updated">
        <AgentSpeakerBadge agent={event.speaker_agent} />
        <span>{event.text || "Node prompt updated."}</span>
        {event.target_node_id ? <em>node {event.target_node_id}</em> : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "item_prompt_updated") {
    return (
      <div className="conversation-event node-prompt-updated">
        <AgentSpeakerBadge agent={event.speaker_agent} />
        <span>{event.text || "Item prompt updated."}</span>
        {conversationEventTargetItemId(event) ? <em>item {conversationEventTargetItemId(event)}</em> : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "execution_started") {
    return (
      <div className="conversation-event execution-started">
        <AgentSpeakerBadge agent={event.speaker_agent} />
        <span>{event.text || "Execution started."}</span>
        {conversationEventExecutionId(event) ? <em>{conversationEventExecutionId(event)}</em> : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (isRevisionConversationEventType(event.event_type)) {
    return (
      <div className="conversation-event execution-started">
        <AgentSpeakerBadge agent={event.speaker_agent} />
        <span>{event.text || revisionConversationEventStatusText(event.event_type)}</span>
        {conversationEventTargetItemId(event) ? <em>item {conversationEventTargetItemId(event)}</em> : null}
        <time>{formatConversationTime(event.created_at)}</time>
      </div>
    );
  }
  if (event.event_type === "error") {
    return (
      <div className="conversation-event error">
        <span>{nodeMentionErrorMessage(conversationEventCode(event), event.text)}</span>
      </div>
    );
  }

  const frontDeskRole = event.metadata?.role === "user" || event.metadata?.role === "assistant" ? event.metadata.role : null;
  return (
    <div className={`conversation-event agent-message ${frontDeskRole === "user" ? "is-user" : ""}`}>
      {frontDeskRole ? <span className="agent-speaker-badge">{frontDeskRole === "user" ? "You" : "Copilot"}</span> : <AgentSpeakerBadge agent={event.speaker_agent} />}
      <p>{event.text}</p>
      <time>{formatConversationTime(event.created_at)}</time>
    </div>
  );
}

function ActionCard({
  action,
  events,
  busy,
  onApply,
  onReject,
  onSelectTarget,
}: {
  action: AgentConversationSuggestedAction;
  events: AgentConversationEvent[];
  busy?: "apply" | "reject";
  onApply: () => void;
  onReject: () => void;
  onSelectTarget: (target: ConversationActionTarget) => void;
}) {
  const status = actionStatusFromEvents(events, action);
  const disabled = Boolean(busy) || status !== "pending";
  const targets = conversationActionTargets(action);
  const plannedChanges = conversationActionPlannedChanges(action);
  const candidatePolicy = conversationActionCandidatePolicy(action);
  const requiresConfirmation = conversationActionRequiresConfirmation(action);
  return (
    <div className={`conversation-event conversation-action-card is-${status}`}>
      <div className="conversation-action-card-header">
        <AgentSpeakerBadge agent={action.speaker_agent} />
        <span className="conversation-action-status">{status}</span>
      </div>
      <strong>{action.title}</strong>
      <p>{action.summary}</p>
      <div className="conversation-action-meta">
        <span>{formatConversationActionType(action.action_type)}</span>
        {action.target_node_id ? <span>node {action.target_node_id}</span> : null}
        {action.target_node_type ? <span>type {action.target_node_type}</span> : null}
        {action.metadata.target_item_id ? <span>item {String(action.metadata.target_item_id)}</span> : null}
        {action.metadata.target_asset_id ? <span>asset {String(action.metadata.target_asset_id)}</span> : null}
        <span>requires_confirmation: {requiresConfirmation ? "true" : "false"}</span>
      </div>
      {targets.length ? (
        <div className="conversation-action-targets">
          {targets.map((target) => (
            <button key={target.key} className="conversation-action-target" type="button" onClick={() => onSelectTarget(target)}>
              <strong>{target.label}</strong>
              {target.meta ? <em>{target.meta}</em> : null}
            </button>
          ))}
        </div>
      ) : null}
      {plannedChanges.length ? (
        <ul className="conversation-action-planned-changes" aria-label="planned_changes">
          {plannedChanges.map((change) => (
            <li key={change}>{change}</li>
          ))}
        </ul>
      ) : null}
      {candidatePolicy ? <span className="conversation-action-policy">candidate_policy: {candidatePolicy}</span> : null}
      {requiresConfirmation ? (
        <div className="conversation-action-controls">
          <button className="small-action" type="button" disabled={disabled} onClick={onApply}>
            {busy === "apply" ? "Applying" : "Apply"}
          </button>
          <button className="small-action muted" type="button" disabled={disabled} onClick={onReject}>
            {busy === "reject" ? "Rejecting" : "Reject"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function AgentSpeakerBadge({ agent }: { agent?: AgentConversationVisibleAgent | null }) {
  return <span className="agent-speaker-badge">{agentConversationLabel(agent)}</span>;
}

function conversationActionTargets(action: AgentConversationSuggestedAction): ConversationActionTarget[] {
  const metadata = action.metadata ?? {};
  const payload = action.payload ?? {};
  const targetCandidates = [
    recordFromUnknown(metadata.target),
    recordFromUnknown(payload.target),
    recordFromUnknown(metadata.target_reference),
    recordFromUnknown(payload.target_reference),
    ...recordArrayFromUnknown(metadata.target_references),
    ...recordArrayFromUnknown(payload.target_references),
  ].filter((target): target is Record<string, unknown> => Boolean(target));
  const directTarget: Record<string, unknown> = {
    target_type: metadata.target_type ?? payload.target_type,
    node_id: action.target_node_id ?? metadata.target_node_id ?? payload.target_node_id,
    item_id: metadata.target_item_id ?? metadata.item_id ?? metadata.target_entity_id ?? payload.target_item_id ?? payload.item_id ?? payload.target_entity_id,
    asset_id: metadata.target_asset_id ?? metadata.asset_id ?? payload.target_asset_id ?? payload.asset_id,
    semantic_type: metadata.semantic_type ?? payload.semantic_type,
    display_name: metadata.target_label ?? metadata.display_name ?? payload.target_label ?? payload.display_name,
  };
  const allTargets = [directTarget, ...targetCandidates];
  const seen = new Set<string>();
  return allTargets.flatMap((target, index) => {
    const nodeId = stringFromUnknown(target.node_id) || (index === 0 ? action.target_node_id ?? "" : "");
    const itemId = stringFromUnknown(target.item_id) || stringFromUnknown(target.target_item_id) || stringFromUnknown(target.target_entity_id);
    const assetId = stringFromUnknown(target.asset_id) || stringFromUnknown(target.target_asset_id);
    const semanticType = stringFromUnknown(target.semantic_type);
    const targetType = stringFromUnknown(target.target_type) || (assetId ? "asset" : itemId ? "item" : nodeId ? "node" : "target");
    if (!nodeId && !itemId && !assetId) return [];
    const key = [targetType, nodeId, itemId, assetId, semanticType].filter(Boolean).join(":");
    if (seen.has(key)) return [];
    seen.add(key);
    const label =
      stringFromUnknown(target.mention_text) ||
      stringFromUnknown(target.display_name) ||
      stringFromUnknown(target.name) ||
      itemId ||
      assetId ||
      nodeId ||
      `Target ${index + 1}`;
    const meta = [targetType, nodeId ? `node ${nodeId}` : "", itemId ? `item ${itemId}` : "", assetId ? `asset ${assetId}` : "", semanticType].filter(Boolean).join(" · ");
    return [{ key, target_type: targetType, node_id: nodeId || null, item_id: itemId || null, asset_id: assetId || null, semantic_type: semanticType || null, label, meta }];
  });
}

function conversationActionPlannedChanges(action: AgentConversationSuggestedAction) {
  const value = action.metadata?.planned_changes ?? action.payload?.planned_changes;
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item.trim();
        const record = recordFromUnknown(item);
        return stringFromUnknown(record?.summary) || stringFromUnknown(record?.text) || stringFromUnknown(record?.field) || "";
      })
      .filter(Boolean);
  }
  const text = stringFromUnknown(value);
  return text ? [text] : [];
}

function conversationActionCandidatePolicy(action: AgentConversationSuggestedAction) {
  const value = action.metadata?.candidate_policy ?? action.payload?.candidate_policy ?? action.metadata?.generation_policy ?? action.payload?.generation_policy;
  if (typeof value === "string") return value;
  const record = recordFromUnknown(value);
  if (!record) return "";
  return Object.entries(record)
    .flatMap(([key, entry]) => (typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean" ? [`${key}=${String(entry)}`] : []))
    .join(" · ");
}

function conversationActionRequiresConfirmation(action: AgentConversationSuggestedAction) {
  const value = action.metadata?.requires_confirmation ?? action.payload?.requires_confirmation;
  if (typeof value === "boolean") return value;
  if (action.metadata?.auto_executed === true || action.payload?.auto_executed === true) return false;
  return action.status === "pending";
}

function conversationActionForEvent(event: AgentConversationEvent): AgentConversationSuggestedAction | null {
  const existingAction = conversationActionFromEvent(event);
  if (existingAction) return existingAction;
  const metadata = event.metadata ?? {};
  const actionId = typeof metadata.action_id === "string" ? metadata.action_id : "";
  if (!actionId) return null;
  const actionType = isConversationActionType(metadata.action_type) ? metadata.action_type : "update_director_context";
  const status = isConversationActionStatus(metadata.action_status)
    ? metadata.action_status
    : isConversationActionStatus(metadata.status)
      ? metadata.status
      : conversationActionStatusFromEventType(event.event_type);
  const speakerAgent = isVisibleAgent(event.speaker_agent) ? event.speaker_agent : "creative_director";
  return {
    action_id: actionId,
    conversation_id: event.conversation_id,
    action_type: actionType,
    status,
    speaker_agent: speakerAgent,
    workflow_id: event.workflow_id,
    target_node_id: event.target_node_id,
    target_node_type: event.target_node_type,
    title: typeof metadata.title === "string" ? metadata.title : formatConversationActionType(actionType),
    summary: typeof metadata.summary === "string" ? metadata.summary : event.text,
    payload: {},
    created_at: event.created_at,
    updated_at: event.created_at,
    metadata,
  };
}

function isConversationActionType(value: unknown): value is AgentConversationSuggestedAction["action_type"] {
  return typeof value === "string" && Boolean(value.trim());
}

function isConversationActionStatus(value: unknown): value is AgentConversationSuggestedAction["status"] {
  return value === "pending" || value === "running" || value === "applied" || value === "rejected" || value === "failed";
}

function conversationActionStatusFromEventType(eventType: AgentConversationEvent["event_type"]): AgentConversationSuggestedAction["status"] {
  if (eventType === "chat_action_applied" || eventType === "action_applied") return "applied";
  if (eventType === "chat_action_rejected" || eventType === "action_rejected") return "rejected";
  if (eventType === "chat_action_failed" || eventType === "error") return "failed";
  return "pending";
}

function formatConversationActionType(value: AgentConversationSuggestedAction["action_type"]) {
  return value.replace(/_/g, " ");
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
