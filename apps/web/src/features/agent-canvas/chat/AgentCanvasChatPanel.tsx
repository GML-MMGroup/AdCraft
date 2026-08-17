import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  AssetsIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  CloseIcon,
  DocumentIcon,
  EditIcon,
  SendIcon,
} from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  AgentCanvasContinuationV2,
  AgentCanvasChatTurnV2,
  AgentActionReceiptV2,
  CanvasRuntimeEventV2,
  ChatActionReceiptCardV2,
  ChatCommandPlanCardV2,
  ChatCapabilityActivityV2,
  ChatProposalCardV2,
  CapabilityProposalOptionV2,
  GuidedInteractionSubmitRequestV1,
  GuidedInteractionV1,
  GuidanceSessionActionV2,
  GuidedSessionStateV2,
  ProposalActionDescriptorV2,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import {
  resizeChatComposerTextarea,
  snapChatComposerScroll,
} from "./chatComposerTextarea.ts";
import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";
import { AgentCanvasStyleSelector } from "./AgentCanvasStyleSelector.tsx";
import {
  AgentCanvasDocumentBrowser,
  AgentCanvasDocumentReferenceCard,
} from "../documents/AgentCanvasDocuments.tsx";
import { isLikelyMarkdown, renderMarkdownAwareText } from "../canvas/AgentCanvasMarkdown.tsx";
import { AgentCanvasExecutionModeControl } from "../settings/AgentCanvasExecutionModeControl.tsx";
import { useChatTimelineScroll } from "./useChatTimelineScroll.ts";
import { ProposalMaterializationStatus } from "./ProposalMaterializationStatus.tsx";
import { DecisionBundleCard } from "./DecisionBundleCard.tsx";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";
import {
  interactionForTimelineProposal,
  shouldRenderStandaloneInteraction,
} from "./guidedInteractionPlacement.ts";
import { TimelineProposalInteractionActions } from "./TimelineProposalInteractionActions.tsx";
import "./agent-canvas-chat.css";

export function AgentCanvasChatPanel({
  workflow,
  chatRevision,
  chatEvents,
  settingsRevision = 0,
  documentEvents = [],
  onFocusNode,
  onActionReceipt,
  onWorkflowRefresh,
  onCollapsedChange,
}: {
  workflow: AgentCanvasWorkflowV2;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  settingsRevision?: number;
  documentEvents?: CanvasRuntimeEventV2[];
  onFocusNode: (nodeId: string) => void;
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
  onCollapsedChange?: (collapsed: boolean) => void;
}) {
  const chat = useAgentCanvasChat({
    workflow,
    chatRevision,
    chatEvents,
    onActionReceipt,
    onWorkflowRefresh,
  });
  const [draft, setDraft] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionedNodeIds, setMentionedNodeIds] = useState<string[]>([]);
  const [mentionedAssetIds, setMentionedAssetIds] = useState<string[]>([]);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const imageAssets = useMemo(
    () => workflow.assets.filter((asset) => asset.media_type === "image"),
    [workflow.assets],
  );
  const currentTopic = useMemo(() => {
    const session = chat.state.guidanceSession;
    return session?.topics.find((topic) => topic.topic_id === session.current_topic_id) ?? null;
  }, [chat.state.guidanceSession]);
  const activeContinuation = useMemo(
    () => chat.state.continuations.find((continuation) => (
      continuation.delivery_status === "queued"
      || continuation.delivery_status === "leased"
      || continuation.delivery_status === "retry_wait"
    )) ?? null,
    [chat.state.continuations],
  );
  const standaloneGuidedInteraction = chat.state.guidedInteraction
    && shouldRenderStandaloneInteraction(chat.state.guidedInteraction, chat.state.items)
    ? chat.state.guidedInteraction
    : null;
  const timelineContentVersion = useMemo(() => {
    const latestItem = chat.state.items[chat.state.items.length - 1];
    const sessionActions = chat.state.currentSessionActions
      .map((action) => `${action.action_id}:${action.state}`)
      .join(",");
    return `${chat.state.items.length}:${latestItem?.sequence ?? ""}:${sessionActions}:${chat.state.agentWorking}`;
  }, [chat.state.agentWorking, chat.state.currentSessionActions, chat.state.items]);
  const timelineScroll = useChatTimelineScroll({
    contentVersion: timelineContentVersion,
    resetKey: workflow.workflow_id,
  });
  useLayoutEffect(() => {
    if (composerTextareaRef.current) {
      resizeChatComposerTextarea(composerTextareaRef.current);
    }
  }, [draft]);

  async function send() {
    const text = draft.trim();
    if (!text || chat.state.sending) return;
    timelineScroll.followLatest();
    const request = {
      text,
      mentionedNodeIds,
      mentionedImageAssetIds: mentionedAssetIds,
    };
    setDraft("");
    setMentionOpen(false);
    setMentionedNodeIds([]);
    setMentionedAssetIds([]);
    await chat.actions.submit(request);
  }

  function toggleValue(value: string, selected: string[], setSelected: (next: string[]) => void) {
    setSelected(selected.includes(value)
      ? selected.filter((item) => item !== value)
      : [...selected, value]);
  }

  if (collapsed) {
    return (
      <button
        className="agent-chat__collapsed-trigger"
        type="button"
        aria-label="Open AdCraft Bot panel"
        title="Open AdCraft Bot"
        onClick={() => {
          setCollapsed(false);
          onCollapsedChange?.(false);
        }}
      >
        <img src="/imgs/logo.png" alt="" />
        <span>AdCraft Bot</span>
      </button>
    );
  }

  return (
    <aside className="agent-chat" aria-label="AdCraft Video Agent">
      <header className="agent-chat__header">
        <div className="agent-chat__identity">
          <strong>AdCraft Video Agent</strong>
          <span>
            {chat.state.agentWorking
              ? chat.state.agentWaitingForModel
                ? "Waiting for model"
                : "Working"
              : activeContinuation
                ? continuationLabel(activeContinuation)
                : currentTopic
                ? `${currentTopic.title} · ${currentTopic.status.replaceAll("_", " ")}`
                : chat.state.guidanceSession
                  ? chat.state.guidanceSession.status.replaceAll("_", " ")
                : "Ready"}
          </span>
        </div>
        <div className="agent-chat__header-actions">
          <AgentCanvasDocumentBrowser
            workflowId={workflow.workflow_id}
            documentEvents={documentEvents}
            onFocusNode={onFocusNode}
          />
          <button
            className="agent-chat__collapse"
            type="button"
            aria-label="Collapse AdCraft Bot panel"
            title="Collapse AdCraft Bot"
            onClick={() => {
              setCollapsed(true);
              onCollapsedChange?.(true);
            }}
          >
            <ChevronRightIcon />
          </button>
        </div>
        <AgentCanvasExecutionModeControl
          workflowId={workflow.workflow_id}
          eventRevision={settingsRevision}
        />
      </header>

      <div className="agent-chat__timeline-shell">
        <div
          className="agent-chat__timeline"
          ref={timelineScroll.timelineRef}
          aria-live="polite"
          onScroll={timelineScroll.onTimelineScroll}
        >
          <div className="agent-chat__timeline-content" ref={timelineScroll.timelineContentRef}>
            {chat.state.loading && !chat.state.items.length ? (
              <div className="agent-chat__empty">Loading conversation...</div>
            ) : null}
            {!chat.state.loading
              && !chat.state.items.length
              && !chat.state.currentSessionActions.length ? (
              <div className="agent-chat__empty">Describe the ad you want to build.</div>
            ) : null}
            {chat.state.continuations
              .filter((continuation) => ["queued", "leased", "retry_wait"].includes(continuation.delivery_status))
              .map((continuation) => (
                <ContinuationActivityRow key={continuation.continuation_id} continuation={continuation} />
              ))}
            {chat.state.guidanceSession ? (
              <GuidanceSessionProgress session={chat.state.guidanceSession} />
            ) : null}
            {standaloneGuidedInteraction ? (
              <GuidedInteractionCard
                interaction={standaloneGuidedInteraction}
                pending={chat.state.actingInteractionId === standaloneGuidedInteraction.interaction_id}
                onSubmit={(request) => chat.actions.submitGuidedInteraction(standaloneGuidedInteraction, request)}
              />
            ) : !chat.state.guidedInteraction && chat.state.guidanceAwaiting ? (
              <GuidanceAwaitingRow awaiting={chat.state.guidanceAwaiting} />
            ) : null}
            {chat.state.items.map((item) => {
              if (item.item_type === "message") {
                return (
                  <div
                    className={`agent-chat__message agent-chat__message--${item.speaker === "user" ? "user" : "agent"}`}
                    key={`message-${item.message_id}`}
                  >
                    <span>{item.speaker === "user" ? "You" : "AdCraft Video Agent"}</span>
                    {isLikelyMarkdown(item.text)
                      ? (
                        <div className="agent-chat__markdown">
                          {renderMarkdownAwareText(item.text)}
                        </div>
                      )
                      : <p>{item.text}</p>}
                  </div>
                );
              }
              if (item.item_type === "expert_activity") {
                return (
                  <CapabilityActivityRow
                    key={`activity-${item.activity_id}`}
                    activity={item}
                    turn={chat.state.turnsById[item.turn_id] ?? null}
                    retrying={Boolean(chat.state.retryingSourceTurnIds[item.turn_id])}
                    onRetry={() => void chat.actions.retryCapabilityActivity(item)}
                    onReviseRequest={() => {
                      setDraft(`Revise the ${item.capability_display_name} request: `);
                      window.requestAnimationFrame(() => composerTextareaRef.current?.focus());
                    }}
                  />
                );
              }
              if (item.item_type === "artifact") {
                return (
                  <button
                    className="agent-chat__artifact"
                    key={`artifact-${item.artifact_id}`}
                    type="button"
                    onClick={() => onFocusNode(item.node_id)}
                  >
                    <DocumentIcon />
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.summary}</small>
                    </span>
                    <b>View Script</b>
                  </button>
                );
              }
              if (item.item_type === "command_plan") {
                return (
                  <CommandPlanCard
                    key={`command-${item.command_plan.plan_id}`}
                    card={item}
                    pending={chat.state.actingCommandPlanId === item.command_plan.plan_id}
                    onAction={chat.actions.actOnCommandPlan}
                  />
                );
              }
              if (item.item_type === "action_receipt") {
                return (
                  <ActionReceiptCard
                    key={`receipt-${item.action_receipt.receipt_id}`}
                    card={item}
                  />
                );
              }
              if (item.item_type === "agent_document") {
                return (
                  <AgentCanvasDocumentReferenceCard
                    key={`document-${item.document_id}:${item.revision}`}
                    workflowId={workflow.workflow_id}
                    reference={item}
                    documentEvents={documentEvents}
                    onFocusNode={onFocusNode}
                  />
                );
              }
              if (item.item_type === "proposal_pointer") return null;
              if (item.item_type === "decision_bundle_pointer") return null;
              if (item.item_type === "decision_bundle") {
                return (
                  <DecisionBundleCard
                    key={`decision-bundle-${item.decision_bundle.bundle_id}`}
                    bundle={item.decision_bundle}
                    pending={chat.state.actingDecisionBundleId === item.decision_bundle.bundle_id}
                    onApply={chat.actions.actOnDecisionBundle}
                  />
                );
              }
              const interaction = interactionForTimelineProposal(
                chat.state.guidedInteraction,
                item,
              );
              return (
                <ProposalCard
                  key={`proposal-${item.proposal.proposal_id}`}
                  card={item}
                  pending={Boolean(
                    interaction
                    && chat.state.actingInteractionId === interaction.interaction_id
                  )}
                  interaction={interaction}
                  onSubmitInteraction={interaction
                    ? (request) => chat.actions.submitGuidedInteraction(interaction, request)
                    : undefined}
                  readOnly={!interaction}
                  issue={chat.state.proposalIssues[item.proposal.proposal_id]}
                />
              );
            })}
            {chat.state.currentSessionActions.length ? (
              <GuidedActionsCard
                actions={chat.state.currentSessionActions}
                actingActionId={chat.state.actingGuidedActionId}
                onApply={chat.actions.applyGuidedAction}
              />
            ) : null}
            {chat.state.agentWorking ? <AgentWorkingRow waitingForModel={chat.state.agentWaitingForModel} /> : null}
          </div>
        </div>
        {timelineScroll.hasUnseenContent ? (
          <button
            className="agent-chat__jump-to-latest"
            type="button"
            aria-label="Jump to latest message"
            title="Jump to latest message"
            onClick={timelineScroll.followLatest}
          >
            <ChevronDownIcon />
          </button>
        ) : null}
      </div>

      {chat.state.error ? (
        <div className="agent-chat__error" role="alert">
          <span>{chat.state.error}</span>
          {chat.state.failedDraft ? (
            <button type="button" onClick={() => void chat.actions.submit(chat.state.failedDraft!)}>
              Retry
            </button>
          ) : chat.state.retryableFailedTurn ? (
            <button
              type="button"
              onClick={() => void chat.actions.retryTurn(chat.state.retryableFailedTurn!)}
              disabled={Boolean(chat.state.retryingSourceTurnIds[chat.state.retryableFailedTurn.turn_id])}
            >
              {chat.state.retryingSourceTurnIds[chat.state.retryableFailedTurn.turn_id]
                ? "Retrying"
                : "Retry"}
            </button>
          ) : null}
        </div>
      ) : null}
      {chat.state.notice ? (
        <div className="agent-chat__notice" role="status">
          <span>{chat.state.notice}</span>
          <button type="button" aria-label="Dismiss notice" onClick={chat.actions.clearNotice}>
            <CloseIcon />
          </button>
        </div>
      ) : null}

      <div className="agent-chat__composer">
        {(mentionedNodeIds.length || mentionedAssetIds.length) ? (
          <div className="agent-chat__mentions">
            {mentionedNodeIds.map((nodeId) => {
              const node = workflow.nodes.find((item) => item.node_id === nodeId);
              return (
                <button
                  type="button"
                  key={nodeId}
                  onClick={() => setMentionedNodeIds((current) => current.filter((item) => item !== nodeId))}
                >
                  @{node?.title ?? nodeId}<CloseIcon />
                </button>
              );
            })}
            {mentionedAssetIds.map((assetId) => {
              const asset = imageAssets.find((item) => item.asset_id === assetId);
              return (
                <button
                  type="button"
                  key={assetId}
                  onClick={() => setMentionedAssetIds((current) => current.filter((item) => item !== assetId))}
                >
                  @{asset?.display_name ?? assetId}<CloseIcon />
                </button>
              );
            })}
          </div>
        ) : null}
        <textarea
          ref={composerTextareaRef}
          rows={3}
          value={draft}
          placeholder="Ask AdCraft Video Agent..."
          aria-label="Message AdCraft Video Agent"
          onChange={(event) => setDraft(event.target.value)}
          onScroll={(event) => snapChatComposerScroll(event.currentTarget)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="agent-chat__composer-actions">
          <div className="agent-chat__composer-tools">
            <button
              type="button"
              className={mentionOpen ? "is-active" : ""}
              aria-label="Mention node or image asset"
              title="Mention node or image asset"
              onClick={() => setMentionOpen((current) => !current)}
            >
              @
            </button>
            <AgentCanvasStyleSelector
              workflowId={workflow.workflow_id}
              activeStyle={workflow.active_style_skill}
              onWorkflowRefresh={() => onWorkflowRefresh?.()}
            />
          </div>
          <button
            type="button"
            className="agent-chat__send"
            aria-label="Send message"
            title="Send message"
            disabled={!draft.trim() || chat.state.sending}
            onClick={() => void send()}
          >
            <SendIcon />
          </button>
        </div>
        {mentionOpen ? (
          <div className="agent-chat__mention-menu">
            <section>
              <h4>Nodes</h4>
              {workflow.nodes.map((node) => (
                <button
                  type="button"
                  key={node.node_id}
                  className={mentionedNodeIds.includes(node.node_id) ? "is-selected" : ""}
                  onClick={() => toggleValue(node.node_id, mentionedNodeIds, setMentionedNodeIds)}
                >
                  <DocumentIcon />
                  <span>{node.title}</span>
                  <small>{node.node_type}</small>
                </button>
              ))}
            </section>
            <section>
              <h4>Image assets</h4>
              {imageAssets.map((asset) => (
                <button
                  type="button"
                  key={asset.asset_id}
                  className={mentionedAssetIds.includes(asset.asset_id) ? "is-selected" : ""}
                  onClick={() => toggleValue(asset.asset_id, mentionedAssetIds, setMentionedAssetIds)}
                >
                  <AssetsIcon />
                  <span>{asset.display_name}</span>
                  <small>image</small>
                </button>
              ))}
            </section>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

export function AgentWorkingRow({ waitingForModel = false }: { waitingForModel?: boolean }) {
  const label = waitingForModel ? "Waiting for model" : "Working";
  return (
    <div
      className="agent-chat__working"
      role="status"
      aria-label={waitingForModel
        ? "AdCraft Video Agent is waiting for the model"
        : "AdCraft Video Agent is working"}
    >
      <span>{label}</span>
      <i className="agent-chat__working-spinner" aria-hidden="true" />
    </div>
  );
}

export function CapabilityActivityRow({
  activity,
  turn,
  retrying = false,
  onRetry,
  onReviseRequest,
}: {
  activity: ChatCapabilityActivityV2;
  turn?: AgentCanvasChatTurnV2 | null;
  retrying?: boolean;
  onRetry?: () => void;
  onReviseRequest?: () => void;
}) {
  const retryable = turn?.retryable ?? activity.retryable;
  const operationStage = recoveryStageLabel(turn?.operation_stage);
  const errorCode = turn?.operation_failure?.code ?? activity.error_code;
  const errorMessage = turn?.operation_failure?.message ?? activity.message;
  const fallbackLabel = retrying
    ? `${activity.capability_display_name} recovery is working`
    : activity.status === "working"
    ? `${activity.capability_display_name} is ${operationStage ?? "working"}`
    : activity.status === "completed"
      ? `${activity.capability_display_name} finished`
      : `${activity.capability_display_name} failed`;
  const label = activity.presentation_text ?? fallbackLabel;
  return (
    <div className={`agent-chat__activity is-${activity.status}`}>
      <i aria-hidden="true" />
      <div>
        <span>{label}</span>
        {activity.status === "failed" ? (
          <>
            {errorCode ? <code>{errorCode}</code> : null}
            {errorMessage ? <small>{errorMessage}</small> : null}
            <div className="agent-chat__activity-actions">
              {retryable && onRetry ? (
                <button
                  type="button"
                  aria-label={`Retry ${activity.capability_display_name} activity`}
                  onClick={onRetry}
                  disabled={retrying}
                >
                  {retrying ? "Retrying" : "Retry"}
                </button>
              ) : null}
              {activity.suggested_actions.includes("revise_request") && onReviseRequest ? (
                <button
                  type="button"
                  aria-label={`Revise ${activity.capability_display_name} request`}
                  onClick={onReviseRequest}
                >
                  Revise request
                </button>
              ) : null}
            </div>
          </>
        ) : null}
        {activity.completion_mode === "deterministic_fallback"
          && activity.warning_code === "specialist_materialization_fallback" ? (
            <small className="agent-chat__activity-warning">
              Draft created with a simplified fallback.
            </small>
          ) : null}
      </div>
    </div>
  );
}

function recoveryStageLabel(stage: string | null | undefined): string | null {
  if (stage === "waiting" || stage === "waiting_provider_response") return "waiting";
  if (stage === "retrying") return "retrying";
  if (stage === "validating") return "validating";
  if (stage === "publishing") return "publishing";
  if (stage === "queued") return "queued";
  if (stage === "running") return "working";
  return null;
}

function continuationLabel(continuation: AgentCanvasContinuationV2): string {
  if (continuation.delivery_status === "retry_wait") {
    return `Retrying${continuation.next_attempt_at ? " shortly" : ""}`;
  }
  return continuation.delivery_status === "leased" ? "Working" : "Queued";
}

export function ContinuationActivityRow({
  continuation,
}: {
  continuation: AgentCanvasContinuationV2;
}) {
  return (
    <div className={`agent-chat__activity agent-chat__continuation is-${continuation.delivery_status}`}>
      <i aria-hidden="true" />
      <span>
        AdCraft Video Agent is {continuationLabel(continuation).toLowerCase()}
        {continuation.attempt_count > 0 ? ` · attempt ${continuation.attempt_count}` : ""}
      </span>
    </div>
  );
}

export function GuidanceAwaitingRow({
  awaiting,
}: {
  awaiting: NonNullable<GuidedSessionStateV2["awaiting"]>;
}) {
  const label = awaiting.kind === "manual_node_run"
    ? "Waiting for a draft node to be run"
    : awaiting.kind === "milestone_idle"
      ? "This production milestone is complete"
      : "Waiting for your guided choice";
  return <div className="agent-chat__activity agent-chat__awaiting" role="status"><i aria-hidden="true" /><span>{label}</span></div>;
}

export function GuidanceSessionProgress({
  session,
}: {
  session: GuidedSessionStateV2;
}) {
  const journey = session.journey;
  const activeFoundationItem = journey.foundation_cursor === null
    ? null
    : journey.foundation_queue[journey.foundation_cursor] ?? null;
  return (
    <section className="agent-chat__recipe" aria-label="Guidance progress">
      <header>
        <strong>{session.goal.summary}</strong>
        <span>Stage revision {journey.stage_revision}</span>
      </header>
      {session.topics.length ? (
        <ol>
          {session.topics.map((topic) => (
            <li
              key={topic.topic_id}
              className={`is-${topic.status}${topic.topic_id === session.current_topic_id ? " is-current" : ""}`}
            >
              <i aria-hidden="true" />
              <span>{topic.title}</span>
              <small>{topic.status.replaceAll("_", " ")}</small>
            </li>
          ))}
        </ol>
      ) : (
        <p>The agent is preparing the next creative decision.</p>
      )}
      <div className="agent-chat__completion" aria-label="Guidance completion">
        <span>
          Stage: {journey.stage.replaceAll("_", " ")} · {journey.stage_status.replaceAll("_", " ")}
        </span>
        {activeFoundationItem ? (
          <span>Foundation item: {activeFoundationItem.kind} {activeFoundationItem.occurrence_index}</span>
        ) : null}
        {session.creative_authority ? (
          <span>Direction: {session.creative_authority.authority === "user" ? "You" : "Director"}</span>
        ) : null}
        {session.current_checkpoint ? (
          <span>
            Checkpoint: {session.current_checkpoint.stage_kind?.replaceAll("_", " ") ?? "planning"}
            {` · ${session.current_checkpoint.status.replaceAll("_", " ")}`}
          </span>
        ) : null}
        <span>Authoring: {session.completion.authoring.replaceAll("_", " ")}</span>
        <span>Delivery: {session.completion.delivery.replaceAll("_", " ")}</span>
      </div>
    </section>
  );
}

export function CommandPlanCard({
  card,
  pending,
  onAction,
}: {
  card: ChatCommandPlanCardV2;
  pending: boolean;
  onAction: (planId: string, action: "confirm" | "reject") => Promise<void>;
}) {
  const plan = card.command_plan;
  const canDecide = plan.confirmation_required && plan.status === "pending_confirmation";
  return (
    <article className={`agent-chat__command is-${plan.status}`}>
      <header>
        <strong>Proposed canvas change</strong>
        <span>{plan.status.replaceAll("_", " ")}</span>
      </header>
      <p>{plan.target_summary || "Review the proposed canvas changes."}</p>
      <small>
        {plan.operations.length} canvas {plan.operations.length === 1 ? "change" : "changes"} will be applied.
      </small>
      {canDecide ? (
        <div className="agent-chat__command-actions">
          <button
            type="button"
            className="is-confirm"
            aria-label="Confirm command"
            disabled={pending}
            onClick={() => void onAction(plan.plan_id, "confirm")}
          >
            Confirm
          </button>
          <button
            type="button"
            className="is-reject"
            aria-label="Reject command"
            disabled={pending}
            onClick={() => void onAction(plan.plan_id, "reject")}
          >
            Reject
          </button>
        </div>
      ) : null}
    </article>
  );
}

export function ActionReceiptCard({
  card,
}: {
  card: ChatActionReceiptCardV2;
}) {
  const receipt = card.action_receipt;
  const isNoop = receipt.status === "not_applied";
  const isSuperseded = receipt.status === "superseded";
  return (
    <article className={`agent-chat__receipt is-${receipt.status}`}>
      <header>
        <strong>{isNoop ? "No canvas change" : isSuperseded ? "Action superseded" : "Canvas updated"}</strong>
        <span>{receipt.status.replaceAll("_", " ")}</span>
      </header>
      <p>{receipt.summary}</p>
      {receipt.run_queue_errors.length ? (
        <ul>
          {receipt.run_queue_errors.map((error) => <li key={error}>{error}</li>)}
        </ul>
      ) : null}
      {receipt.error_message ? <small>{receipt.error_message}</small> : null}
      {receipt.continuation_turn_id ? (
        <small>Planning continues automatically</small>
      ) : null}
    </article>
  );
}

export function ProposalCard({
  card,
  pending,
  onSelect,
  onRevise,
  onApplyAction,
  interaction = null,
  onSubmitInteraction,
  issue,
  readOnly = false,
}: {
  card: ChatProposalCardV2;
  pending: boolean;
  onSelect?: (
    proposalId: string,
    action: ProposalActionDescriptorV2,
    optionId: string,
    acceptedReferences: ProposedDraftReferenceV2[],
  ) => Promise<void>;
  onRevise?: (
    proposalId: string,
    action: ProposalActionDescriptorV2,
    instruction: string,
  ) => Promise<void>;
  onApplyAction?: (proposalId: string, action: ProposalActionDescriptorV2) => Promise<void>;
  interaction?: GuidedInteractionV1 | null;
  onSubmitInteraction?: (request: GuidedInteractionSubmitRequestV1) => Promise<boolean>;
  issue?: string;
  readOnly?: boolean;
}) {
  const proposal = card.proposal;
  const materialization = proposal.materialization;
  const [selected, setSelected] = useState<CapabilityProposalOptionV2 | null>(() => (
    proposal.options.find((option) => option.option_id === materialization?.option_id) ?? null
  ));
  const [revision, setRevision] = useState("");
  const [revising, setRevising] = useState(false);
  const referencesDirtyRef = useRef(false);
  const referencesRevisionRef = useRef(proposal.proposal_revision);
  const isOpen = proposal.availability === "open";
  const isSuperseded = proposal.availability === "superseded";
  const materializationBusy = materialization?.status === "queued" || materialization?.status === "working";
  const retryBlocked = materialization?.status === "failed" && !materialization.retryable;
  const selectAction = proposal.actions.find((action) => action.action === "select_option") ?? null;
  const reviseAction = proposal.actions.find((action) => (
    action.action === "revise_options" || action.action === "revise_direction"
  )) ?? null;
  const directActions = proposal.actions.filter((action) => (
    action.action === "defer_topic"
    || action.action === "exclude_element"
    || action.action === "delegate_choice"
    || action.action === "reuse_direction"
  ));
  const activeInteraction = interaction?.status === "open"
    && interaction.content.content_kind === "concept_choice"
    && interaction.content.proposal_id === proposal.proposal_id
    ? interaction
    : null;
  const interactionOptionIds = new Set(
    activeInteraction?.content.content_kind === "concept_choice"
      ? activeInteraction.content.options.map((option) => option.option_id)
      : [],
  );
  const canSelect = activeInteraction
    ? activeInteraction.allowed_actions.includes("select")
      && !materializationBusy
      && !retryBlocked
    : !readOnly && isOpen
    && Boolean(selectAction?.enabled)
    && !materializationBusy
    && !retryBlocked;
  const canRevise = activeInteraction
    ? activeInteraction.allowed_actions.includes("revise") && !materializationBusy
    : !readOnly && Boolean(reviseAction?.enabled)
    && (isOpen || isSuperseded)
    && !materializationBusy;
  const availableReferences = proposal.proposed_references;
  const [acceptedReferences, setAcceptedReferences] = useState<ProposedDraftReferenceV2[]>(
    proposal.proposed_references,
  );

  useEffect(() => {
    if (!materialization?.option_id) return;
    const materializedOption = proposal.options.find((option) => option.option_id === materialization.option_id);
    if (materializedOption) setSelected(materializedOption);
  }, [materialization?.option_id, proposal.options]);

  useEffect(() => {
    const revisionChanged = referencesRevisionRef.current !== proposal.proposal_revision;
    referencesRevisionRef.current = proposal.proposal_revision;
    if (materialization) return;
    if (revisionChanged) referencesDirtyRef.current = false;
    if (!referencesDirtyRef.current) setAcceptedReferences(proposal.proposed_references);
  }, [materialization, proposal.proposal_revision, proposal.proposed_references]);

  function updateAcceptedReferences(
    update: (current: ProposedDraftReferenceV2[]) => ProposedDraftReferenceV2[],
  ) {
    referencesDirtyRef.current = true;
    setAcceptedReferences(update);
  }

  function withOrders(references: ProposedDraftReferenceV2[]) {
    return references.map((reference, index) => ({ ...reference, display_order: index }));
  }

  function moveReference(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= acceptedReferences.length) return;
    const next = [...acceptedReferences];
    [next[index], next[target]] = [next[target]!, next[index]!];
    updateAcceptedReferences(() => withOrders(next));
  }

  return (
    <article className="agent-chat__proposal">
      <header>
        <strong>{proposal.capability_display_name}</strong>
        <span>{proposal.availability}</span>
      </header>
      <div className="agent-chat__options">
        {proposal.options.map((option) => (
          <button
            type="button"
            key={option.option_id}
            className={selected?.option_id === option.option_id ? "is-selected" : ""}
            disabled={!canSelect || pending || Boolean(
              activeInteraction && !interactionOptionIds.has(option.option_id)
            )}
            onClick={() => setSelected(option)}
          >
            <strong>{option.title}</strong>
            <span>{option.public_summary}</span>
            <ul>
              {option.key_decisions.map((decision, index) => (
                <li key={`${option.option_id}:${index}`}>{decision}</li>
              ))}
            </ul>
          </button>
        ))}
      </div>
      {acceptedReferences.length || selectAction || activeInteraction?.allowed_actions.includes("select") ? (
        <section className="agent-chat__proposal-references" aria-label="Accepted references">
          <header>
            <strong>References</strong>
            <span>{acceptedReferences.length}</span>
          </header>
          {acceptedReferences.map((reference, index) => (
            <div key={`${reference.source_kind}:${reference.source_id}`}>
              <span>
                <strong>{reference.display_name}</strong>
                <small>{reference.media_type} · {reference.input_role.replaceAll("_", " ")}</small>
              </span>
              <label>
                <input
                  type="checkbox"
                  checked={reference.required}
                  disabled={pending || !canSelect}
                  onChange={(event) => updateAcceptedReferences((current) => current.map((item, itemIndex) => (
                    itemIndex === index ? { ...item, required: event.currentTarget.checked } : item
                  )))}
                />
                Required
              </label>
              <button
                type="button"
                aria-label={`Move ${reference.display_name} earlier`}
                disabled={pending || !canSelect || index === 0}
                onClick={() => moveReference(index, -1)}
              >
                <ChevronUpIcon />
              </button>
              <button
                type="button"
                aria-label={`Move ${reference.display_name} later`}
                disabled={pending || !canSelect || index === acceptedReferences.length - 1}
                onClick={() => moveReference(index, 1)}
              >
                <ChevronDownIcon />
              </button>
              <button
                type="button"
                aria-label={`Remove ${reference.display_name}`}
                disabled={pending || !canSelect}
                onClick={() => updateAcceptedReferences((current) => withOrders(
                  current.filter((_item, itemIndex) => itemIndex !== index),
                ))}
              >
                <CloseIcon />
              </button>
            </div>
          ))}
          {canSelect ? (
            <select
              value=""
              aria-label="Add proposal reference"
              disabled={pending}
              onChange={(event) => {
                const reference = availableReferences.find((candidate) => (
                  `${candidate.source_kind}:${candidate.source_id}` === event.currentTarget.value
                ));
                if (!reference || acceptedReferences.some((candidate) => (
                  candidate.source_kind === reference.source_kind
                  && candidate.source_id === reference.source_id
                ))) return;
                updateAcceptedReferences((current) => withOrders([...current, reference]));
              }}
            >
              <option value="">Add reference...</option>
              {availableReferences
                .filter((reference) => !acceptedReferences.some((candidate) => (
                  candidate.source_kind === reference.source_kind
                  && candidate.source_id === reference.source_id
                )))
                .map((reference) => (
                  <option
                    key={`${reference.source_kind}:${reference.source_id}`}
                    value={`${reference.source_kind}:${reference.source_id}`}
                  >
                    {reference.display_name}
                  </option>
                ))}
            </select>
          ) : null}
        </section>
      ) : null}
      {proposal.application_count > 0 ? (
        <p className="agent-chat__proposal-history">
          Applied {proposal.application_count} {proposal.application_count === 1 ? "time" : "times"}
          {proposal.latest_application
            ? ` · Last ${proposal.latest_application.action.replaceAll("_", " ")}`
            : ""}
        </p>
      ) : null}
      {materialization ? (
        <ProposalMaterializationStatus materialization={materialization} />
      ) : null}
      {issue ? (
        <p className="agent-chat__proposal-issue" role="status">
          {issue}
        </p>
      ) : null}
      {activeInteraction && onSubmitInteraction ? (
        <TimelineProposalInteractionActions
          acceptedReferences={acceptedReferences}
          interaction={activeInteraction}
          materializationBusy={materializationBusy}
          onSubmit={onSubmitInteraction}
          pending={pending}
          selectedOptionId={canSelect ? selected?.option_id ?? null : null}
        />
      ) : !readOnly && (isOpen || isSuperseded) && (selectAction || reviseAction || directActions.length) ? (
        <div className="agent-chat__proposal-actions">
          {isOpen && selected && selectAction ? (
            <button
              type="button"
              disabled={pending || !canSelect}
              title={selectAction.disabled_reason ?? selectAction.reason}
              onClick={() => void onSelect?.(
                proposal.proposal_id,
                selectAction,
                selected.option_id,
                acceptedReferences,
              )}
            >
              {selectAction.label}
            </button>
          ) : null}
          {(isOpen || isSuperseded) && reviseAction ? (
            <button
              type="button"
              disabled={pending || !canRevise}
              title={reviseAction.disabled_reason ?? reviseAction.reason}
              onClick={() => setRevising((current) => !current)}
            >
              <EditIcon />{reviseAction.label}
            </button>
          ) : null}
          {directActions.map((action) => (
            <button
              type="button"
              key={action.action_id}
              disabled={pending || materializationBusy || !action.enabled}
              title={action.disabled_reason ?? action.reason}
            onClick={() => void onApplyAction?.(proposal.proposal_id, action)}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
      {revising && canRevise && reviseAction ? (
        <form
          className="agent-chat__revision"
          onSubmit={(event) => {
            event.preventDefault();
            void onRevise?.(proposal.proposal_id, reviseAction, revision);
            setRevision("");
            setRevising(false);
          }}
        >
          <input
            value={revision}
            onChange={(event) => setRevision(event.target.value)}
            placeholder="Describe the change"
            aria-label="Proposal revision"
          />
          <button
            type="submit"
            aria-label="Submit proposal revision"
            disabled={!revision.trim() || pending}
          >
            <SendIcon />
          </button>
        </form>
      ) : null}
    </article>
  );
}

export function GuidedActionsCard({
  actions,
  actingActionId,
  onApply,
}: {
  actions: GuidanceSessionActionV2[];
  actingActionId: string | null;
  onApply: (action: GuidanceSessionActionV2) => Promise<void>;
}) {
  const visibleActions = actions.filter((action) => action.state !== "superseded");
  if (!visibleActions.length) return null;
  return (
    <div className="agent-chat__guided-actions" aria-label="Suggested next actions">
      {visibleActions.map((action) => (
        <button
          type="button"
          key={action.action_id}
          disabled={action.state !== "pending" || Boolean(actingActionId)}
          title={action.reason}
          onClick={() => void onApply(action)}
        >
          <span>{action.label}</span>
          {action.state !== "pending" ? <small>{action.state}</small> : null}
        </button>
      ))}
    </div>
  );
}
