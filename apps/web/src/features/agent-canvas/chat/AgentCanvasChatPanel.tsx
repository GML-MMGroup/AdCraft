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
  AgentCanvasCreationModeV2,
  AgentActionReceiptV2,
  AdaptiveProductionRecipeV2,
  AdaptiveProductionStageV2,
  CanvasPositionV2,
  CanvasRuntimeEventV2,
  ChatActionReceiptCardV2,
  ChatCommandPlanCardV2,
  ChatExpertActivityV2,
  ChatProposalCardV2,
  ConceptOptionV2,
  GuidedDeliveryActionV2,
  ProductionReadinessProjectionV2,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import {
  resizeChatComposerTextarea,
  snapChatComposerScroll,
} from "./chatComposerTextarea.ts";
import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";
import { useChatTimelineScroll } from "./useChatTimelineScroll.ts";
import "./agent-canvas-chat.css";

export function AgentCanvasChatPanel({
  workflow,
  chatRevision,
  chatEvents,
  proposalPosition,
  onFocusNode,
  onActionReceipt,
  onWorkflowRefresh,
}: {
  workflow: AgentCanvasWorkflowV2;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  proposalPosition: CanvasPositionV2;
  onFocusNode: (nodeId: string) => void;
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  const chat = useAgentCanvasChat({
    workflow,
    chatRevision,
    chatEvents,
    proposalPosition,
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
    const session = chat.state.creativeSession;
    return session?.topics.find((topic) => topic.topic_id === session.current_topic_id) ?? null;
  }, [chat.state.creativeSession]);
  const currentRecipeStage = useMemo(() => {
    const recipe = chat.state.recipe;
    if (!recipe?.current_topic_id) return null;
    return recipe.stages.find((stage) => stage.topic_id === recipe.current_topic_id) ?? null;
  }, [chat.state.recipe]);
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
    return `${chat.state.items.length}:${latestItem?.sequence ?? ""}:${sessionActions}`;
  }, [chat.state.currentSessionActions, chat.state.items]);
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
            {chat.state.sending
              ? "Thinking"
              : activeContinuation
                ? continuationLabel(activeContinuation)
                : currentRecipeStage
                  ? `${currentRecipeStage.title} · ${currentRecipeStage.status.replaceAll("_", " ")}`
                : currentTopic
                ? `${currentTopic.topic_kind.replaceAll("_", " ")} · ${currentTopic.status.replaceAll("_", " ")}`
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
            {chat.state.creationMode || chat.state.recipe ? (
              <ProductionRecipeProgress
                creationMode={chat.state.creationMode}
                recipe={chat.state.recipe}
                readiness={chat.state.creativeSession?.readiness ?? null}
              />
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
                  onSetAvailability={chat.actions.setProposalAvailability}
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
          <button
            type="button"
            className={mentionOpen ? "is-active" : ""}
            aria-label="Mention node or image asset"
            title="Mention node or image asset"
            onClick={() => setMentionOpen((current) => !current)}
          >
            @
          </button>
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

function creationModeLabel(mode: AgentCanvasCreationModeV2 | null): string {
  if (!mode) return "Production plan";
  return mode
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function stageStatusLabel(stage: AdaptiveProductionStageV2): string {
  if (stage.status === "working") return "Working";
  if (stage.status === "completed") return "Complete";
  if (stage.status === "skipped") return "Skipped";
  if (stage.status === "reopened") return "Reopened";
  return "Pending";
}

export function ProductionRecipeProgress({
  creationMode,
  recipe,
  readiness,
}: {
  creationMode: AgentCanvasCreationModeV2 | null;
  recipe: AdaptiveProductionRecipeV2 | null;
  readiness: ProductionReadinessProjectionV2 | null;
}) {
  const visibleStages = recipe?.stages.filter((stage) => stage.applicability !== "not_required") ?? [];
  return (
    <section className="agent-chat__recipe" aria-label="Production plan">
      <header>
        <strong>{creationModeLabel(creationMode ?? recipe?.creation_mode ?? null)}</strong>
        {recipe ? <span>Revision {recipe.revision}</span> : null}
      </header>
      {visibleStages.length ? (
        <ol>
          {visibleStages.map((stage) => (
            <li
              key={stage.topic_id}
              className={`is-${stage.status}${stage.topic_id === recipe?.current_topic_id ? " is-current" : ""}`}
              title={stage.objective}
            >
              <i aria-hidden="true" />
              <span>{stage.title}</span>
              <small>{stageStatusLabel(stage)}</small>
            </li>
          ))}
        </ol>
      ) : (
        <p>The agent is preparing a production plan.</p>
      )}
      {readiness ? (
        <div className="agent-chat__completion" aria-label="Production completion">
          <span>Planning: {readiness.completion.planning.replaceAll("_", " ")}</span>
          <span>Generation: {readiness.completion.generation.replaceAll("_", " ")}</span>
          <span>Delivery: {readiness.completion.delivery.replaceAll("_", " ")}</span>
        </div>
      ) : null}
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
      {receipt.error ? <small>{receipt.error.message}</small> : null}
      {receipt.continuation_turn_id || receipt.continuation_id ? (
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
  onSetAvailability,
  issue,
}: {
  card: ChatProposalCardV2;
  pending: boolean;
  onSelect: (
    proposalId: string,
    optionId: string,
    generationAction: "draft_only" | "generate_now",
    acceptedReferences: ProposedDraftReferenceV2[],
  ) => Promise<void>;
  onRevise: (proposalId: string, instruction: string) => Promise<void>;
  onSetAvailability: (proposalId: string, action: "archive" | "reopen") => Promise<void>;
  issue?: string;
}) {
  const [selected, setSelected] = useState<ConceptOptionV2 | null>(null);
  const [selectionConfirmed, setSelectionConfirmed] = useState(false);
  const [revision, setRevision] = useState("");
  const [revising, setRevising] = useState(false);
  const proposal = card.proposal;
  const canSelect = proposal.availability === "open" && proposal.available_actions.includes("select");
  const canRevise = proposal.availability === "open" && proposal.available_actions.includes("revise");
  const canArchive = proposal.available_actions.includes("archive");
  const canReopen = proposal.available_actions.includes("reopen");
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
            onClick={() => {
              setSelected(option);
              setSelectionConfirmed(false);
            }}
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
            ? ` · Last ${proposal.latest_application.generation_action === "generate_now" ? "generated" : "drafted"}`
            : ""}
        </p>
      ) : null}
      {issue || proposal.availability === "unavailable" ? (
        <p className="agent-chat__proposal-issue" role="status">
          {issue ?? "This proposal is currently unavailable."}
        </p>
      ) : null}
      {canSelect || canRevise || canArchive || canReopen ? (
        <div className="agent-chat__proposal-actions">
          {canSelect && selected && !selectionConfirmed ? (
            <button type="button" disabled={pending} onClick={() => setSelectionConfirmed(true)}>
              Select
            </button>
          ) : canSelect && selected ? (
            <>
              <button type="button" disabled={pending} onClick={() => void onSelect(proposal.proposal_id, selected.option_id, "draft_only", acceptedReferences)}>
                Create draft
              </button>
              <button type="button" disabled={pending} onClick={() => void onSelect(proposal.proposal_id, selected.option_id, "generate_now", acceptedReferences)}>
                Generate now
              </button>
            </>
          ) : null}
          {canRevise ? (
            <button type="button" disabled={pending} title="Revise options" onClick={() => setRevising((current) => !current)}>
              <EditIcon />Revise
            </button>
          ) : null}
          {canArchive ? (
            <button
              type="button"
              aria-label="Archive proposal"
              disabled={pending}
              onClick={() => void onSetAvailability(proposal.proposal_id, "archive")}
            >
              Archive
            </button>
          ) : null}
          {canReopen ? (
            <button
              type="button"
              aria-label="Reopen proposal"
              disabled={pending}
              onClick={() => void onSetAvailability(proposal.proposal_id, "reopen")}
            >
              Reopen
            </button>
          ) : null}
        </div>
      ) : null}
      {revising && canRevise ? (
        <form
          className="agent-chat__revision"
          onSubmit={(event) => {
            event.preventDefault();
            void onRevise(proposal.proposal_id, revision);
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
          <button type="submit" disabled={!revision.trim() || pending}><SendIcon /></button>
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
  actions: GuidedDeliveryActionV2[];
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
