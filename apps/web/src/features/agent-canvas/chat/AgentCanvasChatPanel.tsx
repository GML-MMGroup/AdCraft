import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  AssetsIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CloseIcon,
  DocumentIcon,
  EditIcon,
  SendIcon,
} from "../../../icons.tsx";
import type {
  AgentCanvasWorkflowV2,
  AgentCanvasContinuationV2,
  AgentActionReceiptV2,
  CanvasRuntimeEventV2,
  ChatActionReceiptCardV2,
  ChatCommandPlanCardV2,
  ChatExpertActivityV2,
  ChatProposalCardV2,
  ConceptOptionV2,
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
import { useChatTimelineScroll } from "./useChatTimelineScroll.ts";
import "./agent-canvas-chat.css";

export function AgentCanvasChatPanel({
  workflow,
  chatRevision,
  chatEvents,
  onFocusNode,
  onActionReceipt,
  onWorkflowRefresh,
}: {
  workflow: AgentCanvasWorkflowV2;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  onFocusNode: (nodeId: string) => void;
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  const chat = useAgentCanvasChat({
    workflow,
    chatRevision,
    chatEvents,
    onActionReceipt,
    onWorkflowRefresh,
  });
  const [draft, setDraft] = useState("");
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

  return (
    <aside className="agent-chat" aria-label="AdCraft Video Agent">
      <header className="agent-chat__header">
        <div>
          <strong>AdCraft Video Agent</strong>
          <span>
            {chat.state.agentWorking
              ? "Working"
              : activeContinuation
                ? continuationLabel(activeContinuation)
                : currentTopic
                ? `${currentTopic.title} · ${currentTopic.status.replaceAll("_", " ")}`
                : chat.state.guidanceSession
                  ? chat.state.guidanceSession.status.replaceAll("_", " ")
                : "Ready"}
          </span>
        </div>
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
            {chat.state.items.map((item) => {
              if (item.item_type === "message") {
                return (
                  <div
                    className={`agent-chat__message agent-chat__message--${item.speaker === "user" ? "user" : "agent"}`}
                    key={`message-${item.message_id}`}
                  >
                    <span>{item.speaker === "user" ? "You" : "AdCraft Video Agent"}</span>
                    <p>{item.text}</p>
                  </div>
                );
              }
              if (item.item_type === "expert_activity") {
                return <SpecialistActivityRow key={`activity-${item.activity_id}`} activity={item} />;
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
              if (item.item_type === "proposal_pointer") return null;
              return (
                <ProposalCard
                  key={`proposal-${item.proposal.proposal_id}`}
                  card={item}
                  pending={chat.state.actingProposalId === item.proposal.proposal_id}
                  onSelect={chat.actions.selectProposal}
                  onRevise={chat.actions.reviseProposal}
                  onApplyAction={chat.actions.applyProposalAction}
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
            {chat.state.agentWorking ? <AgentWorkingRow /> : null}
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

export function AgentWorkingRow() {
  return (
    <div
      className="agent-chat__working"
      role="status"
      aria-label="AdCraft Video Agent is working"
    >
      <span>Working</span>
      <i className="agent-chat__working-spinner" aria-hidden="true" />
    </div>
  );
}

export function SpecialistActivityRow({
  activity,
}: {
  activity: ChatExpertActivityV2;
}) {
  const label = activity.status === "working"
    ? `${activity.display_name} is working`
    : activity.status === "completed"
      ? `${activity.display_name} finished`
      : `${activity.display_name} failed`;
  return (
    <div className={`agent-chat__activity is-${activity.status}`}>
      <i aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
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

export function GuidanceSessionProgress({
  session,
}: {
  session: GuidedSessionStateV2;
}) {
  return (
    <section className="agent-chat__recipe" aria-label="Guidance progress">
      <header>
        <strong>{session.goal.summary}</strong>
        <span>Revision {session.revision}</span>
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
        <span>Authoring: {session.completion.authoring.replaceAll("_", " ")}</span>
        <span>Delivery: {session.completion.delivery.replaceAll("_", " ")}</span>
      </div>
    </section>
  );
}

function commandOperationLabel(operationType: string): string {
  return operationType
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
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
      <ul>
        {plan.operations.map((operation) => (
          <li key={operation.operation_id}>
            {commandOperationLabel(operation.operation_type)}
          </li>
        ))}
      </ul>
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
  issue,
}: {
  card: ChatProposalCardV2;
  pending: boolean;
  onSelect: (
    proposalId: string,
    action: ProposalActionDescriptorV2,
    optionId: string,
    acceptedReferences: ProposedDraftReferenceV2[],
  ) => Promise<void>;
  onRevise: (
    proposalId: string,
    action: ProposalActionDescriptorV2,
    instruction: string,
  ) => Promise<void>;
  onApplyAction: (proposalId: string, action: ProposalActionDescriptorV2) => Promise<void>;
  issue?: string;
}) {
  const [selected, setSelected] = useState<ConceptOptionV2 | null>(null);
  const [revision, setRevision] = useState("");
  const [revising, setRevising] = useState(false);
  const proposal = card.proposal;
  const isOpen = proposal.availability === "open";
  const selectAction = proposal.actions.find((action) => action.action === "select_option") ?? null;
  const reviseAction = proposal.actions.find((action) => action.action === "revise_options") ?? null;
  const directActions = proposal.actions.filter((action) => (
    action.action === "defer_topic"
    || action.action === "exclude_element"
    || action.action === "delegate_choice"
  ));
  const canSelect = isOpen && Boolean(selectAction);
  const canRevise = isOpen && Boolean(reviseAction);
  const availableReferences = proposal.proposed_references;
  const [acceptedReferences, setAcceptedReferences] = useState<ProposedDraftReferenceV2[]>(
    proposal.proposed_references,
  );
  useEffect(() => {
    setAcceptedReferences(proposal.proposed_references);
  }, [proposal.proposal_id, proposal.proposal_revision, proposal.proposed_references]);

  function withOrders(references: ProposedDraftReferenceV2[]) {
    return references.map((reference, index) => ({ ...reference, display_order: index }));
  }

  function moveReference(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= acceptedReferences.length) return;
    const next = [...acceptedReferences];
    [next[index], next[target]] = [next[target]!, next[index]!];
    setAcceptedReferences(withOrders(next));
  }

  return (
    <article className="agent-chat__proposal">
      <header>
        <strong>{proposal.specialist_name
          .split("_")
          .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
          .join(" ")}</strong>
        <span>{proposal.availability}</span>
      </header>
      <div className="agent-chat__options">
        {proposal.options.map((option) => (
          <button
            type="button"
            key={option.option_id}
            className={selected?.option_id === option.option_id ? "is-selected" : ""}
            disabled={!canSelect || pending}
            onClick={() => setSelected(option)}
          >
            <strong>{option.title}</strong>
            <span>{option.summary_prompt}</span>
          </button>
        ))}
      </div>
      {acceptedReferences.length || canSelect ? (
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
                  onChange={(event) => setAcceptedReferences((current) => current.map((item, itemIndex) => (
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
                onClick={() => setAcceptedReferences((current) => withOrders(
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
                setAcceptedReferences((current) => withOrders([...current, reference]));
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
      {issue ? (
        <p className="agent-chat__proposal-issue" role="status">
          {issue}
        </p>
      ) : null}
      {isOpen && (selectAction || reviseAction || directActions.length) ? (
        <div className="agent-chat__proposal-actions">
          {canSelect && selected && selectAction ? (
            <button
              type="button"
              disabled={pending}
              title={selectAction.reason}
              onClick={() => void onSelect(
                proposal.proposal_id,
                selectAction,
                selected.option_id,
                acceptedReferences,
              )}
            >
              {selectAction.label}
            </button>
          ) : null}
          {canRevise && reviseAction ? (
            <button
              type="button"
              disabled={pending}
              title={reviseAction.reason}
              onClick={() => setRevising((current) => !current)}
            >
              <EditIcon />{reviseAction.label}
            </button>
          ) : null}
          {isOpen ? directActions.map((action) => (
            <button
              type="button"
              key={action.action_id}
              disabled={pending}
              title={action.reason}
              onClick={() => void onApplyAction(proposal.proposal_id, action)}
            >
              {action.label}
            </button>
          )) : null}
        </div>
      ) : null}
      {revising && canRevise && reviseAction ? (
        <form
          className="agent-chat__revision"
          onSubmit={(event) => {
            event.preventDefault();
            void onRevise(proposal.proposal_id, reviseAction, revision);
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
  onApply: (actionId: string) => Promise<void>;
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
          onClick={() => void onApply(action.action_id)}
        >
          <span>{action.label}</span>
          {action.state !== "pending" ? <small>{action.state}</small> : null}
        </button>
      ))}
    </div>
  );
}
