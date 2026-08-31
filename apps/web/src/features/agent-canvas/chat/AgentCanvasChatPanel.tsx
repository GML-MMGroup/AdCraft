import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { InlineLoader } from "generative-loaders";
import "generative-loaders/styles.css";

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
  AgentActionReceiptV2,
  CanvasRuntimeEventV2,
  CanvasRuntimeSnapshotV2,
  ChatActionReceiptCardV2,
  ChatCommandPlanCardV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
  CapabilityProposalOptionV2,
  GuidanceSessionActionV2,
  GuidedSessionStateV2,
  ProposalActionDescriptorV2,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import {
  resizeChatComposerTextarea,
  snapChatComposerScroll,
} from "./chatComposerTextarea.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";
import { StableMediaPreview } from "../../../workflow/StableMediaPreview.tsx";
import { useAgentCanvasChat } from "./useAgentCanvasChat.ts";
import { AgentCanvasStyleSelector } from "./AgentCanvasStyleSelector.tsx";
import {
  AgentCanvasDocumentBrowser,
  AgentCanvasDocumentReferenceCard,
} from "../documents/AgentCanvasDocuments.tsx";
import { AgentCanvasExecutionModeControl } from "../settings/AgentCanvasExecutionModeControl.tsx";
import { useChatTimelineScroll } from "./useChatTimelineScroll.ts";
import { ProposalMaterializationStatus } from "./ProposalMaterializationStatus.tsx";
import { DecisionBundleCard } from "./DecisionBundleCard.tsx";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";
import {
  guidedInteractionContentVersion,
  shouldRenderStandaloneInteraction,
} from "./guidedInteractionPlacement.ts";
import {
  guidedInteractionReferences,
} from "./guidedInteractionReferences.ts";
import { buildConceptChoiceSubmitRequest } from "./conceptChoiceSubmission.ts";
import { HistoricalProposalOptions } from "./HistoricalProposalOptions.tsx";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";
import { CapabilityActivityRow } from "./CapabilityActivitySection.tsx";
import { StageThread } from "./StageThread.tsx";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";
import { preloadAgentCapabilityIconLink } from "./AgentCapabilityIcon.tsx";
import { buildStageThreadTimeline } from "./stageThreadProjection.ts";
import { ConversationNodeLinks } from "./ConversationNodeLinks.tsx";
import { CurrentProductionStep } from "./CurrentProductionStep.tsx";
import {
  getAgentChatResizeBounds,
  resizeAgentChatWidth,
  type AgentChatResizeBounds,
} from "./chatPanelResize.ts";
import {
  buildConversationCanvasLinkIndex,
  type ConversationCanvasLocation,
} from "./conversationCanvasLinks.ts";
import { ConversationRecoverySurface } from "./ConversationRecoverySurface.tsx";
import { NaturalMessage } from "./NaturalMessage.tsx";
import { projectNaturalMessagePresentation } from "./naturalMessagePresentation.ts";
import { useComposerContext } from "./useComposerContext.ts";
import { projectProductionFocus } from "./productionFocusProjection.ts";
import { GuidedAnswerBubble } from "./GuidedAnswerBubble.tsx";
import {
  isPersistedGuidedAnswerMessage,
  type GuidedAnswerBubbleV1,
} from "./guidedAnswerPresentation.ts";
import type { PresentationStreamView as PresentationStreamRuntimeView } from "../runtime/useAgentCanvasPresentationStreams.ts";
import "./agent-canvas-chat.css";

type ChatPanelResizeSession = {
  pointerId: number;
  startX: number;
  startWidth: number;
  bounds: AgentChatResizeBounds;
};

type TimelineRenderOptions = {
  compactCapability?: boolean;
};

type TimelineEntry =
  | { entry_type: "timeline"; key: string; sequence: number; unit: ReturnType<typeof buildStageThreadTimeline>[number] }
  | { entry_type: "guided_answer"; key: string; sequence: number; answer: GuidedAnswerBubbleV1 };

export function TimelineHydrationSkeleton({
  itemType,
}: {
  itemType: "proposal" | "decision_bundle";
}) {
  const label = itemType === "proposal" ? "proposal" : "decision bundle";
  return (
    <div className="agent-chat__timeline-hydration" role="status" aria-label={`Loading ${label}`}>
      <span className="agent-chat__timeline-hydration-kicker">{itemType === "proposal" ? "Decision" : "Guidance"}</span>
      <span className="agent-chat__timeline-hydration-line agent-chat__timeline-hydration-line--wide" />
      <span className="agent-chat__timeline-hydration-line" />
      <small>Loading {label}…</small>
    </div>
  );
}

export { GuidanceSessionProgress } from "./GuidanceSessionProgress.tsx";
export { CapabilityActivityRow } from "./CapabilityActivitySection.tsx";

export function AgentCanvasChatPanel({
  workflow,
  chatRevision,
  chatEvents,
  settingsRevision = 0,
  documentEvents = [],
  onFocusNode,
  onActionReceipt,
  onWorkflowRefresh,
  onRuntimeRefresh,
  onProjectsRefresh,
  runtime = null,
  collapsed: controlledCollapsed,
  onCollapsedChange,
  onViewNodes,
}: {
  workflow: AgentCanvasWorkflowV2;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  settingsRevision?: number;
  documentEvents?: CanvasRuntimeEventV2[];
  onFocusNode: (nodeId: string) => void;
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
  onRuntimeRefresh?: () => Promise<void> | void;
  onProjectsRefresh?: () => Promise<boolean> | void;
  runtime?: CanvasRuntimeSnapshotV2 | null;
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  onViewNodes?: (nodeIds: string[]) => void;
}) {
  const chat = useAgentCanvasChat({
    workflow,
    chatRevision,
    chatEvents,
    onActionReceipt,
    onWorkflowRefresh,
    onRuntimeRefresh,
  });
  const [draft, setDraft] = useState("");
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const collapsed = controlledCollapsed ?? internalCollapsed;
  const [chatPanelWidth, setChatPanelWidth] = useState<number | null>(null);
  const [chatPanelResizing, setChatPanelResizing] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [selectedSkillTitle, setSelectedSkillTitle] = useState<string | null>(
    workflow.active_style_skill?.title ?? null,
  );
  const [selectedConceptOptionId, setSelectedConceptOptionId] = useState<string | null>(null);
  const [optimisticProposalSelections, setOptimisticProposalSelections] = useState<Record<string, string>>({});
  const [optimisticallyDismissedInteractionId, setOptimisticallyDismissedInteractionId] = useState<string | null>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const chatPanelRef = useRef<HTMLElement>(null);
  const resizeSessionRef = useRef<ChatPanelResizeSession | null>(null);
  const resizeMinimumWidthRef = useRef<number | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [pendingContextFiles, setPendingContextFiles] = useState<File[]>([]);
  const optimisticInteractionSubmitSeqRef = useRef<number | null>(null);
  const composerContext = useComposerContext({
    workflow,
    onWorkflowRefresh,
    assetsEnabled: mentionOpen,
  });
  const imageAssets = composerContext.availableImageAssets;

  useEffect(() => {
    setSelectedSkillTitle(workflow.active_style_skill?.title ?? null);
  }, [
    workflow.active_style_skill?.skill_run_id,
    workflow.active_style_skill?.title,
    workflow.workflow_id,
  ]);
  useEffect(() => {
    setPendingContextFiles([]);
  }, [workflow.workflow_id]);
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
  const activePresentationStreams = useMemo(
    () => Object.values(chat.state.presentationStreams ?? {})
      .filter((stream) => (
        stream.stream_kind === "assistant"
        && ["connecting", "open", "reconnecting"].includes(stream.status)
        && stream.text.trim().length > 0
      )),
    [chat.state.presentationStreams],
  );
  const standaloneGuidedInteraction = chat.state.guidedInteraction
    && shouldRenderStandaloneInteraction(chat.state.guidedInteraction)
    ? chat.state.guidedInteraction
    : null;
  const referenceOccurrenceLabel = useMemo(() => {
    const content = standaloneGuidedInteraction?.content;
    if (content?.content_kind !== "reference_source" || content.reference_kind !== "character_main") {
      return null;
    }
    const occurrence = chat.state.guidanceSession?.journey.decisions.find((decision) => (
      decision.element_kind === "character"
      && decision.occurrence_id === content.occurrence_id
    ));
    return occurrence ? `Character ${occurrence.occurrence_index}` : null;
  }, [chat.state.guidanceSession?.journey.decisions, standaloneGuidedInteraction]);
  const conceptInteraction = standaloneGuidedInteraction?.content.content_kind === "concept_choice"
    ? standaloneGuidedInteraction
    : null;
  const conceptContent = conceptInteraction?.content.content_kind === "concept_choice"
    ? conceptInteraction.content
    : null;
  const conceptInteractionPending = Boolean(
    conceptInteraction
    && (conceptInteraction.status === "submitted"
      || chat.state.actingInteractionId === conceptInteraction.interaction_id),
  );
  const currentInteractionOptimisticallyDismissed = Boolean(
    standaloneGuidedInteraction
    && standaloneGuidedInteraction.interaction_id === optimisticallyDismissedInteractionId,
  );
  const conceptCustomAllowed = Boolean(
    conceptContent?.allow_custom
    && conceptInteraction?.allowed_actions.includes("custom"),
  );
  const standaloneGuidedReferences = useMemo(() => (
    standaloneGuidedInteraction
      ? guidedInteractionReferences(standaloneGuidedInteraction, chat.state.items)
      : []
  ), [chat.state.items, standaloneGuidedInteraction]);
  const conceptSelectionReady = Boolean(
    !selectedConceptOptionId
    || !conceptContent?.proposal_id
    || standaloneGuidedReferences !== null,
  );

  function beginChatPanelResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    const panel = chatPanelRef.current;
    if (!panel) return;
    const startWidth = panel.getBoundingClientRect().width;
    const minWidth = resizeMinimumWidthRef.current ?? startWidth;
    const bounds = getAgentChatResizeBounds(minWidth, window.innerWidth);
    resizeMinimumWidthRef.current = minWidth;
    resizeSessionRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth,
      bounds,
    };
    setChatPanelWidth(startWidth);
    setChatPanelResizing(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function updateChatPanelResize(event: ReactPointerEvent<HTMLButtonElement>) {
    const session = resizeSessionRef.current;
    if (!session || session.pointerId !== event.pointerId) return;
    setChatPanelWidth(resizeAgentChatWidth({
      startX: session.startX,
      startWidth: session.startWidth,
      pointerX: event.clientX,
      bounds: session.bounds,
    }));
    event.preventDefault();
  }

  function finishChatPanelResize(event: ReactPointerEvent<HTMLButtonElement>) {
    const session = resizeSessionRef.current;
    if (!session || session.pointerId !== event.pointerId) return;
    resizeSessionRef.current = null;
    setChatPanelResizing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function nudgeChatPanelWidth(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (!(["ArrowLeft", "ArrowRight", "Home", "End"] as string[]).includes(event.key)) return;
    const panel = chatPanelRef.current;
    if (!panel) return;
    const currentWidth = panel.getBoundingClientRect().width;
    const minWidth = resizeMinimumWidthRef.current ?? currentWidth;
    const bounds = getAgentChatResizeBounds(minWidth, window.innerWidth);
    resizeMinimumWidthRef.current = minWidth;
    const nextWidth = event.key === "Home"
      ? bounds.minWidth
      : event.key === "End"
        ? bounds.maxWidth
        : resizeAgentChatWidth({
            startX: 0,
            startWidth: currentWidth,
            pointerX: event.key === "ArrowLeft" ? -24 : 24,
            bounds,
          });
    setChatPanelWidth(nextWidth);
    event.preventDefault();
  }

  useEffect(() => {
    setOptimisticProposalSelections((current) => {
      let changed = false;
      const next = { ...current };
      for (const [proposalId, optionId] of Object.entries(current)) {
        const proposalItem = chat.state.items.find((item) => (
          item.item_type === "proposal" && item.proposal.proposal_id === proposalId
        ));
        const authoritativeOptionId = proposalItem?.item_type === "proposal"
          ? proposalItem.proposal.latest_application?.option_id
          : null;
        if (authoritativeOptionId === optionId) {
          delete next[proposalId];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [chat.state.items]);
  const stageTimeline = useMemo(
    () => buildStageThreadTimeline(
      chat.state.items.filter((item) => !isPersistedGuidedAnswerMessage(item)),
      {
        showUnassociatedPlanning: chat.state.agentWorking,
      },
    ),
    [chat.state.agentWorking, chat.state.items],
  );
  const timelineEntries = useMemo<TimelineEntry[]>(() => [
    ...stageTimeline.map((unit) => ({
      entry_type: "timeline" as const,
      key: `timeline:${unit.key}`,
      sequence: unit.sequence,
      unit,
    })),
    ...chat.state.guidedAnswerBubbles.map((answer) => ({
      entry_type: "guided_answer" as const,
      key: answer.bubble_id,
      sequence: answer.sequence,
      answer,
    })),
  ].sort((left, right) => left.sequence - right.sequence), [
    chat.state.guidedAnswerBubbles,
    stageTimeline,
  ]);
  const currentStageCapabilityId = useMemo(() => {
    const stages = stageTimeline.filter((unit) => unit.unit_type === "stage_thread");
    const activeStage = [...stages].reverse().find((stage) => (
      stage.status === "working" || stage.status === "waiting_user"
    ));
    return activeStage?.capability_id ?? stages.at(-1)?.capability_id ?? null;
  }, [stageTimeline]);
  useEffect(() => {
    if (currentStageCapabilityId) preloadAgentCapabilityIconLink(currentStageCapabilityId);
  }, [currentStageCapabilityId]);
  const conversationLinkIndex = useMemo(
    () => buildConversationCanvasLinkIndex(stageTimeline, chat.state.guidanceAwaiting),
    [chat.state.guidanceAwaiting, stageTimeline],
  );
  const productionFocus = useMemo(() => projectProductionFocus({
    nodes: workflow.nodes,
    runtime,
    guidanceAwaiting: chat.state.guidanceAwaiting,
  }), [chat.state.guidanceAwaiting, runtime, workflow.nodes]);
  const viewNodes = onViewNodes ?? ((nodeIds: string[]) => {
    if (nodeIds[0]) onFocusNode(nodeIds[0]);
  });
  const naturalMessagePresentation = useMemo(
    () => projectNaturalMessagePresentation(chat.state.items),
    [chat.state.items],
  );
  const timelineContentVersion = useMemo(() => {
    const latestItem = chat.state.items[chat.state.items.length - 1];
    const sessionActions = chat.state.currentSessionActions
      .map((action) => `${action.action_id}:${action.state}`)
      .join(",");
    const interactionVersion = guidedInteractionContentVersion(chat.state.guidedInteraction);
    const presentationVersion = Object.values(chat.state.presentationStreams ?? {})
      .map((stream) => `${stream.stream_id}:${stream.last_sequence_no}:${stream.status}`)
      .join(",");
    const guidedAnswerVersion = chat.state.guidedAnswerBubbles
      .map((answer) => `${answer.bubble_id}:${answer.sequence}`)
      .join(",");
    return `${chat.state.items.length}:${latestItem?.sequence ?? ""}:${interactionVersion}:${sessionActions}:${presentationVersion}:${guidedAnswerVersion}:${chat.state.agentWorking}`;
  }, [
    chat.state.agentWorking,
    chat.state.currentSessionActions,
    chat.state.guidedAnswerBubbles,
    chat.state.guidedInteraction,
    chat.state.items,
    chat.state.presentationStreams,
  ]);
  const timelineScroll = useChatTimelineScroll({
    contentVersion: timelineContentVersion,
    resetKey: workflow.workflow_id,
  });
  useEffect(() => {
    setSelectedConceptOptionId(null);
  }, [conceptInteraction?.interaction_id]);

  useEffect(() => {
    if (!optimisticallyDismissedInteractionId) return;
    const interaction = chat.state.guidedInteraction;
    if (!interaction || interaction.interaction_id !== optimisticallyDismissedInteractionId) {
      optimisticInteractionSubmitSeqRef.current = null;
      setOptimisticallyDismissedInteractionId(null);
      return;
    }
    const materializationFailed = chatEvents.some((event) => (
      event.workflow_id === workflow.workflow_id
      && (event.event_type === "proposal_materialization_failed" || event.event_type === "guided_product_source_failed")
      && event.seq > (optimisticInteractionSubmitSeqRef.current ?? -1)
      && (event.action_id === optimisticallyDismissedInteractionId
        || event.payload?.interaction_id === optimisticallyDismissedInteractionId)
    ));
    if (materializationFailed) {
      optimisticInteractionSubmitSeqRef.current = null;
      setOptimisticallyDismissedInteractionId(null);
    }
  }, [chat.state.guidedInteraction, chatEvents, optimisticallyDismissedInteractionId, workflow.workflow_id]);

  async function submitGuidedInteraction(
    interaction: NonNullable<typeof standaloneGuidedInteraction>,
    request: Parameters<typeof chat.actions.submitGuidedInteraction>[1],
  ) {
    optimisticInteractionSubmitSeqRef.current = chatEvents.reduce(
      (latest, event) => Math.max(latest, event.seq),
      -1,
    );
    setOptimisticallyDismissedInteractionId(interaction.interaction_id);
    let accepted = false;
    try {
      accepted = await chat.actions.submitGuidedInteraction(interaction, request);
    } catch {
      accepted = false;
    }
    if (!accepted) {
      optimisticInteractionSubmitSeqRef.current = null;
      setOptimisticallyDismissedInteractionId((current) => (
        current === interaction.interaction_id ? null : current
      ));
    }
    return accepted;
  }

  useEffect(() => {
    if (conceptInteraction?.interaction_id) setMentionOpen(false);
  }, [conceptInteraction?.interaction_id]);

  useLayoutEffect(() => {
    if (composerTextareaRef.current) {
      resizeChatComposerTextarea(composerTextareaRef.current);
    }
  }, [draft]);

  async function send() {
    const submittedDraft = draft;
    const text = submittedDraft.trim();
    if (chat.state.sending || conceptInteractionPending) return;

    if (conceptInteraction) {
      const request = buildConceptChoiceSubmitRequest({
        interaction: conceptInteraction,
        selectedOptionId: selectedConceptOptionId,
        customText: text,
        proposalReferences: standaloneGuidedReferences,
      });
      if (!request) return;
      const optimisticProposalId = selectedConceptOptionId ? conceptContent?.proposal_id : null;
      const previousOptimisticOptionId = optimisticProposalId
        ? optimisticProposalSelections[optimisticProposalId]
        : undefined;
      if (optimisticProposalId && selectedConceptOptionId) {
        setOptimisticProposalSelections((current) => ({
          ...current,
          [optimisticProposalId]: selectedConceptOptionId,
        }));
      }
      const accepted = await submitGuidedInteraction(conceptInteraction, request);
      if (!accepted) {
        if (optimisticProposalId) {
          setOptimisticProposalSelections((current) => {
            const next = { ...current };
            if (previousOptimisticOptionId) next[optimisticProposalId] = previousOptimisticOptionId;
            else delete next[optimisticProposalId];
            return next;
          });
        }
        return;
      }
      setDraft((current) => current === submittedDraft ? "" : current);
      setSelectedConceptOptionId(null);
      setMentionOpen(false);
      return;
    }

    if (!text) return;
    timelineScroll.followLatest();
    const submittedNodeIds = [...composerContext.selectedNodeIds];
    const submittedAssetIds = [...composerContext.selectedAssetIds];
    const submittedSkillTitle = selectedSkillTitle?.trim() || null;
    const request = {
      text,
      mentionedNodeIds: submittedNodeIds,
      mentionedImageAssetIds: submittedAssetIds,
      skillTitle: submittedSkillTitle,
    };
    const accepted = await chat.actions.submit(request);
    if (!accepted) return;
    setDraft((current) => current === submittedDraft ? "" : current);
    setMentionOpen(false);
    composerContext.actions.consumeSubmittedContext({
      nodeIds: submittedNodeIds,
      assetIds: submittedAssetIds,
    });
  }

  function renderStandaloneGuidedInteractionCard() {
    if (!standaloneGuidedInteraction) return null;
    return currentInteractionOptimisticallyDismissed ? (
      <div className="agent-chat__optimistic-interaction-status" role="status" aria-label="Guided interaction submitted">
        <strong>Submitted</strong>
        <span>Generating nodes…</span>
      </div>
    ) : (
      <GuidedInteractionCard
        key={standaloneGuidedInteraction.interaction_id}
        interaction={standaloneGuidedInteraction}
        referenceOccurrenceLabel={referenceOccurrenceLabel}
        pending={
          standaloneGuidedInteraction.status === "submitted"
          || chat.state.actingInteractionId === standaloneGuidedInteraction.interaction_id
        }
        issue={chat.state.guidedInteractionIssue}
        pendingProductMainHandoff={composerContext.productMainHandoff}
        onClearProductMainHandoff={composerContext.actions.clearProductMainHandoff}
        onProjectsRefresh={onProjectsRefresh}
        selectedConceptOptionId={conceptInteraction ? selectedConceptOptionId : null}
        onSelectConceptOption={(optionId) => {
          setSelectedConceptOptionId(optionId);
          setDraft("");
        }}
        onSubmit={(request) => submitGuidedInteraction(standaloneGuidedInteraction, request)}
      />
    );
  }

  function renderTimelineItem(
    item: ChatTimelineItemV2,
    location: ConversationCanvasLocation | null = null,
    options: TimelineRenderOptions = {},
  ) {
    if (item.item_type === "message") {
      return <NaturalMessage
        key={`message-${item.message_id}`}
        message={item}
        skillTitle={chat.state.messageSkillTitles?.[item.message_id] ?? null}
        presentation={naturalMessagePresentation.get(item.message_id) ?? {
          messageId: item.message_id,
          showAgentIdentity: item.speaker === "adcraft_video_agent",
          startsSpeakerRun: true,
        }}
        related={location ? (
          <ConversationNodeLinks
            location={location}
            nodes={workflow.nodes}
            variant="related"
            onViewNodes={viewNodes}
          />
        ) : null}
      />;
    }
    if (item.item_type === "expert_activity") {
      return (
        <CapabilityActivityRow
          key={`activity-${item.activity_id}`}
          activity={item}
          compact={options.compactCapability}
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
          onClick={() => viewNodes([item.node_id])}
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
          nodeLinks={location ? (
            <ConversationNodeLinks
              location={location}
              nodes={workflow.nodes}
              variant="receipt"
              onViewNodes={viewNodes}
            />
          ) : null}
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
    if (item.item_type === "proposal_pointer") {
      return <TimelineHydrationSkeleton itemType="proposal" />;
    }
    if (item.item_type === "decision_bundle_pointer") {
      return <TimelineHydrationSkeleton itemType="decision_bundle" />;
    }
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
    return (
      <Fragment key={`proposal-${item.proposal.proposal_id}`}>
        <ProposalCard
          card={item}
          pending={false}
          compact={options.compactCapability}
          retryingMaterialization={Boolean(
            item.proposal.materialization
            && chat.state.retryingSourceTurnIds[item.proposal.materialization.turn_id]
          )}
          onRetryMaterialization={item.proposal.materialization
            ? () => chat.actions.retryProposalMaterialization(item.proposal.materialization!)
            : undefined}
          readOnly
          optimisticSelectedOptionId={optimisticProposalSelections[item.proposal.proposal_id] ?? null}
          issue={chat.state.proposalIssues[item.proposal.proposal_id]}
        />
        {location ? (
          <ConversationNodeLinks
            location={location}
            nodes={workflow.nodes}
            variant="result"
            onViewNodes={viewNodes}
          />
        ) : null}
      </Fragment>
    );
  }

  if (collapsed) {
    return (
      <button
        className="agent-chat__collapsed-trigger"
        type="button"
        aria-label="Open AdCraft Bot panel"
        title="Open AdCraft Bot"
        onClick={() => {
          setInternalCollapsed(false);
          onCollapsedChange?.(false);
        }}
      >
        <img src="/imgs/logo.png" alt="" />
        <span>AdCraft Bot</span>
      </button>
    );
  }

  return (
    <aside
      ref={chatPanelRef}
      className={`agent-chat${chatPanelResizing ? " is-resizing" : ""}`}
      style={chatPanelWidth === null ? undefined : { width: `${chatPanelWidth}px` }}
      aria-label="AdCraft Video Agent"
    >
      <button
        className="agent-chat__resize-handle"
        type="button"
        aria-label="Resize AdCraft Video Agent panel"
        aria-valuenow={chatPanelWidth ?? undefined}
        onPointerDown={beginChatPanelResize}
        onPointerMove={updateChatPanelResize}
        onPointerUp={finishChatPanelResize}
        onPointerCancel={finishChatPanelResize}
        onLostPointerCapture={finishChatPanelResize}
        onKeyDown={nudgeChatPanelWidth}
      />
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
              setInternalCollapsed(true);
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

      <CurrentProductionStep focus={productionFocus} onViewNodes={viewNodes} />

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
            {timelineEntries.map((entry) => {
              if (entry.entry_type === "guided_answer") {
                return <GuidedAnswerBubble key={entry.key} answer={entry.answer} />;
              }
              const unit = entry.unit;
              const location = conversationLinkIndex.locations.get(unit.key) ?? null;
              if (unit.unit_type === "item") {
                const content = renderTimelineItem(unit.item, location);
                if (!content) return null;
                return (
                  <div key={unit.key}>
                    {content}
                  </div>
                );
              }
              const failedReceipts = unit.receipts.filter(({ action_receipt }) => (
                action_receipt.status === "failed"
                || action_receipt.status === "rejected"
                || action_receipt.status === "not_applied"
                || action_receipt.status === "applied_with_run_error"
              ));
              return (
                <div key={unit.key}>
                  <StageThread
                    unit={unit}
                    result={location ? (
                      <ConversationNodeLinks
                        location={location}
                        nodes={workflow.nodes}
                        variant="result"
                        onViewNodes={viewNodes}
                      />
                    ) : null}
                  >
                    {unit.activities.map((activity) => renderTimelineItem(
                      activity,
                      null,
                      { compactCapability: true },
                    ))}
                    {unit.proposals.map((proposal) => renderTimelineItem(
                      proposal,
                      null,
                      { compactCapability: true },
                    ))}
                    {failedReceipts.map((receipt) => renderTimelineItem(
                      receipt,
                      null,
                      { compactCapability: true },
                    ))}
                  </StageThread>
                </div>
              );
            })}
            {chat.state.currentSessionActions.length ? (
              <GuidedActionsCard
                actions={chat.state.currentSessionActions}
                actingActionId={chat.state.actingGuidedActionId}
                onApply={chat.actions.applyGuidedAction}
              />
            ) : null}
            {activePresentationStreams.map((stream) => (
              <PresentationStreamRow key={stream.stream_id} stream={stream} />
            ))}
            {chat.state.agentWorking ? <AgentWorkingRow waitingForModel={chat.state.agentWaitingForModel} /> : null}
            {chat.state.timelineRecovery ? (
              <ConversationRecoverySurface
                recovery={chat.state.timelineRecovery}
                onAction={() => {
                  if (
                    chat.state.timelineRecovery?.action === "retry"
                    && chat.state.retryableFailedTurn
                  ) {
                    void chat.actions.retryTurn(chat.state.retryableFailedTurn);
                  } else {
                    void chat.actions.refresh();
                  }
                }}
                onDismiss={chat.actions.clearTimelineRecovery}
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
        {conceptInteraction ? (
          <div className="agent-chat__current-interaction agent-chat__current-interaction--overlay" aria-live="polite">
            {renderStandaloneGuidedInteractionCard()}
          </div>
        ) : null}
      </div>

      {standaloneGuidedInteraction && !conceptInteraction ? (
        <div className="agent-chat__current-interaction" aria-live="polite">
          {renderStandaloneGuidedInteractionCard()}
        </div>
      ) : null}

      {chat.state.composerRecovery ? (
        <ConversationRecoverySurface
          recovery={chat.state.composerRecovery}
          onAction={chat.state.failedDraft ? async () => {
            const failedDraft = chat.state.failedDraft!;
            const draftAtRetry = draft;
            const accepted = await chat.actions.submit(failedDraft);
            if (!accepted) return;
            if (draftAtRetry.trim() === failedDraft.text) {
              setDraft((current) => current === draftAtRetry ? "" : current);
            }
            setMentionOpen(false);
            composerContext.actions.consumeSubmittedContext({
              nodeIds: failedDraft.mentionedNodeIds,
              assetIds: failedDraft.mentionedImageAssetIds,
            });
          } : undefined}
          onDismiss={chat.actions.clearComposerRecovery}
        />
      ) : chat.state.workflowRecovery ? (
        <ConversationRecoverySurface
          recovery={chat.state.workflowRecovery}
          onAction={async () => {
            await Promise.all([
              chat.actions.refresh(),
              onWorkflowRefresh?.(),
              onRuntimeRefresh?.(),
            ]);
            chat.actions.clearWorkflowRecovery();
          }}
          onDismiss={chat.actions.clearWorkflowRecovery}
        />
      ) : null}

      {chat.state.notice ? (
        <div className="agent-chat__notice" role="status">
          <span>{chat.state.notice}</span>
          <button type="button" aria-label="Dismiss notice" onClick={chat.actions.clearNotice}>
            <CloseIcon />
          </button>
        </div>
      ) : null}

      {composerContext.view.uploadState === "uploading" ? (
        <div className="agent-chat__context-uploading" role="status">
          Uploading context asset…
        </div>
      ) : null}

      {composerContext.uploadIssue ? (
        <ConversationRecoverySurface
          recovery={composerContext.uploadIssue}
          onDismiss={composerContext.actions.clearUploadIssue}
        />
      ) : null}

      <div className="agent-chat__composer">
        {pendingContextFiles.length ? (
          <div className="agent-chat__product-upload-choice" role="status">
            <span>
              {pendingContextFiles.length === 1
                ? "Use this image as Product Main?"
                : "Use the first image as Product Main?"}
            </span>
            <div>
              <button
                type="button"
                onClick={() => {
                  const files = pendingContextFiles;
                  setPendingContextFiles([]);
                  void (async () => {
                    await composerContext.actions.upload(files.slice(0, 1), { semanticRole: "product_main" });
                    if (files.length > 1) {
                      await composerContext.actions.upload(files.slice(1), {
                        semanticRole: null,
                        preserveProductMainHandoff: true,
                      });
                    }
                  })();
                }}
                disabled={chat.state.sending || composerContext.view.uploadState === "uploading"}
              >
                Product Main
              </button>
              <button
                type="button"
                onClick={() => {
                  const files = pendingContextFiles;
                  setPendingContextFiles([]);
                  void composerContext.actions.upload(files, { semanticRole: null });
                }}
                disabled={chat.state.sending || composerContext.view.uploadState === "uploading"}
              >
                Keep unclassified
              </button>
              <button
                type="button"
                aria-label="Cancel image upload"
                onClick={() => setPendingContextFiles([])}
                disabled={chat.state.sending}
              >
                <CloseIcon />
              </button>
            </div>
          </div>
        ) : null}
        {composerContext.productMainHandoff ? (
          <div className="agent-chat__product-main-handoff" role="status">
            {composerContext.productMainHandoff.previewUrl ? (
              <StableMediaPreview
                src={mediaAssetContentPath({
                  asset_id: composerContext.productMainHandoff.assetId,
                  version_id: composerContext.productMainHandoff.versionId,
                  media_url: composerContext.productMainHandoff.previewUrl,
                })}
                alt=""
              />
            ) : null}
            <span>
              <strong>Product Main</strong>
              <small>{composerContext.productMainHandoff.displayName}</small>
            </span>
            <button
              type="button"
              aria-label="Clear Product Main handoff"
              onClick={composerContext.actions.clearProductMainHandoff}
            >
              <CloseIcon />
            </button>
          </div>
        ) : null}
        {conceptInteraction ? (
          <div className="agent-chat__guided-composer-hint" role="status">
            You can also describe your own direction below.
          </div>
        ) : null}
        {!conceptInteraction && selectedSkillTitle ? (
          <div className="agent-chat__selected-skill" role="status" aria-label={`Selected Skill: ${selectedSkillTitle}`}>
            <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" />
            <span>{selectedSkillTitle}</span>
          </div>
        ) : null}
        <textarea
          ref={composerTextareaRef}
          rows={3}
          value={draft}
          placeholder={conceptInteraction
            ? "Describe your own direction..."
            : "Ask AdCraft Video Agent..."}
          aria-label="Message AdCraft Video Agent"
          onChange={(event) => {
            const nextDraft = event.target.value;
            if (conceptInteraction && nextDraft.trim()) setSelectedConceptOptionId(null);
            setDraft(nextDraft);
          }}
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
              disabled={Boolean(conceptInteraction) || chat.state.sending}
              onClick={() => setMentionOpen((current) => !current)}
            >
              @
            </button>
            {!conceptInteraction ? (
              <>
                <button
                  type="button"
                  aria-label="Upload context images"
                  title="Upload context images"
                  disabled={chat.state.sending}
                  onClick={() => uploadInputRef.current?.click()}
                >
                  <AssetsIcon />
                </button>
                <input
                  ref={uploadInputRef}
                  className="agent-chat__context-file-input"
                  type="file"
                  accept="image/*"
                  multiple
                  disabled={chat.state.sending}
                  tabIndex={-1}
                  aria-hidden="true"
                  onChange={(event) => {
                    const files = event.currentTarget.files;
                    if (files?.length) setPendingContextFiles(Array.from(files));
                    event.currentTarget.value = "";
                  }}
                />
              </>
              ) : null}
            <AgentCanvasStyleSelector
              workflowId={workflow.workflow_id}
              activeStyle={workflow.active_style_skill}
              onWorkflowRefresh={() => onWorkflowRefresh?.()}
              onSkillSelected={setSelectedSkillTitle}
            />
          </div>
          <button
            type="button"
            className="agent-chat__send"
            aria-label={conceptInteraction ? "Submit guided direction" : "Send message"}
            title={conceptInteraction ? "Submit guided direction" : "Send message"}
            disabled={conceptInteraction
              ? ((!selectedConceptOptionId && (!draft.trim() || !conceptCustomAllowed))
                || !conceptSelectionReady
                || conceptInteractionPending)
              : (!draft.trim() || chat.state.sending)}
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
                  className={composerContext.selectedNodeIds.includes(node.node_id) ? "is-selected" : ""}
                  disabled={chat.state.sending}
                  onClick={() => composerContext.actions.toggleNode(node.node_id)}
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
                  className={composerContext.selectedAssetIds.includes(asset.asset_id) ? "is-selected" : ""}
                  disabled={chat.state.sending}
                  onClick={() => composerContext.actions.toggleAsset(asset.asset_id)}
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
      <InlineLoader
        variant="halo"
        size={20}
        className="agent-chat__working-loader"
      />
      <span>{label}</span>
    </div>
  );
}

export function PresentationStreamRow({
  stream,
}: {
  stream: PresentationStreamRuntimeView;
}) {
  return (
    <div
      className="agent-chat__presentation-stream"
      role="status"
      aria-label="AdCraft Video Agent is generating a response"
    >
      <p>{stream.text}</p>
      <span>Generating response</span>
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
  nodeLinks,
}: {
  card: ChatActionReceiptCardV2;
  nodeLinks?: ReactNode;
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
      {nodeLinks}
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
  onRetryMaterialization,
  retryingMaterialization = false,
  optimisticSelectedOptionId = null,
  issue,
  readOnly = false,
  compact = false,
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
  onRetryMaterialization?: (turnId: string) => Promise<boolean>;
  retryingMaterialization?: boolean;
  optimisticSelectedOptionId?: string | null;
  issue?: string;
  readOnly?: boolean;
  compact?: boolean;
}) {
  const proposal = card.proposal;
  const materialization = proposal.materialization;
  const appliedOptionId = optimisticSelectedOptionId
    ?? proposal.latest_application?.option_id
    ?? materialization?.option_id
    ?? null;
  const [selected, setSelected] = useState<CapabilityProposalOptionV2 | null>(() => (
    proposal.options.find((option) => option.option_id === appliedOptionId) ?? null
  ));
  const [revision, setRevision] = useState("");
  const [revising, setRevising] = useState(false);
  const referencesDirtyRef = useRef(false);
  const referencesRevisionRef = useRef(proposal.proposal_revision);
  const isOpen = proposal.availability === "open";
  const isSuperseded = proposal.availability === "superseded";
  const materializationBusy = materialization?.status === "queued" || materialization?.status === "working";
  const materializationLocked = materializationBusy || materialization?.status === "failed";
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
  const displayOptions = proposal.options;
  const canSelect = !readOnly && isOpen
    && Boolean(selectAction?.enabled)
    && !materializationLocked;
  const canRevise = !readOnly && Boolean(reviseAction?.enabled)
    && (isOpen || isSuperseded)
    && !materializationLocked;
  const availableReferences = proposal.proposed_references;
  const [acceptedReferences, setAcceptedReferences] = useState<ProposedDraftReferenceV2[]>(
    proposal.proposed_references,
  );

  useEffect(() => {
    if (!appliedOptionId) return;
    const appliedOption = proposal.options.find((option) => option.option_id === appliedOptionId);
    if (appliedOption) setSelected(appliedOption);
  }, [appliedOptionId, proposal.options]);

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
    <article className={`agent-chat__proposal${readOnly ? " is-read-only" : ""}${compact ? " is-compact" : ""}`}>
      <header>
        {compact ? (
          <div className="agent-chat__compact-capability-heading">
            <strong>{proposal.capability_display_name}</strong>
            {!readOnly ? <span>{proposal.availability}</span> : null}
          </div>
        ) : (
          <AgentCapabilityIdentity
            capabilityId={proposal.capability_id}
            displayName={proposal.capability_display_name}
            detail={!readOnly ? proposal.availability : null}
          />
        )}
      </header>
      {readOnly ? (
        <HistoricalProposalOptions
          options={displayOptions}
          selectedOptionId={appliedOptionId}
        />
      ) : (
        <div className="agent-chat__options" aria-label="Creative direction options">
          {displayOptions.map((option, index) => (
            <ProposalOptionRow
              key={option.option_id}
              index={index}
              optionId={option.option_id}
              title={option.title}
              summary={option.public_summary}
              selected={selected?.option_id === option.option_id}
              disabled={!canSelect || pending}
              onSelect={() => setSelected(option)}
            />
          ))}
        </div>
      )}
      {!readOnly && (acceptedReferences.length || selectAction) ? (
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
      {!readOnly && proposal.application_count > 0 ? (
        <p className="agent-chat__proposal-history">
          Applied {proposal.application_count} {proposal.application_count === 1 ? "time" : "times"}
          {proposal.latest_application
            ? ` · Last ${proposal.latest_application.action.replaceAll("_", " ")}`
            : ""}
        </p>
      ) : null}
      {materialization && (!readOnly || materialization.status === "failed") ? (
        <ProposalMaterializationStatus
          materialization={materialization}
          retrying={retryingMaterialization}
          onRetry={materialization.retryable ? onRetryMaterialization : undefined}
        />
      ) : null}
      {issue ? (
        <p className="agent-chat__proposal-issue" role="status">
          {issue}
        </p>
      ) : null}
      {!readOnly && (isOpen || isSuperseded) && (selectAction || reviseAction || directActions.length) ? (
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
              disabled={pending || materializationLocked || !action.enabled}
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
