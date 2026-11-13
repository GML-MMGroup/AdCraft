import { useUiLocale } from "../../../i18n/locale.tsx";
import { skillDisplayTitle } from "../skills/skillDisplayCopy.ts";
import { conceptProposalQuestion } from "../model/conceptProposalQuestion.ts";
import { useTranslation } from "../../../i18n/useTranslation";
import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
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
  AgentCanvasChatTurnV2,
  AgentCanvasContinuationV2,
  AgentActionReceiptV2,
  CanvasRuntimeEventV2,
  CanvasRuntimeSnapshotV2,
  ChatActionReceiptCardV2,
  ChatCommandPlanCardV2,
  ChatCapabilityActivityV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
  CapabilityProposalOptionV2,
  GuidanceSessionActionV2,
  GuidedSessionStateV2,
  GuidedInteractionV1,
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
import { useChatTimelineScroll } from "./useChatTimelineScroll.ts";
import { ProposalMaterializationStatus } from "./ProposalMaterializationStatus.tsx";
import { DecisionBundleCard } from "./DecisionBundleCard.tsx";
import { GuidedInteractionCard } from "./GuidedInteractionCard.tsx";
import type { BrandFormAnswers } from "./BrandFormInteraction.tsx";
import { BrandFormConfirmationToast } from "./BrandFormConfirmationToast.tsx";
import { productSourceCopy } from "./productSourceCopy.ts";
import { isBrandCustomInputCard } from "../model/brandCustomInput.ts";
import {
  guidedInteractionContentVersion,
  shouldRenderStandaloneInteraction,
} from "./guidedInteractionPlacement.ts";
import {
  guidedInteractionReferences,
} from "./guidedInteractionReferences.ts";
import { buildConceptChoiceSubmitRequest } from "./conceptChoiceSubmission.ts";
import { BrandCardRecoveryNotice } from "./BrandCardRecoveryNotice";
import { BrandTreatmentConfirmation } from "./BrandTreatmentConfirmation.tsx";
import { HistoricalProposalOptions } from "./HistoricalProposalOptions.tsx";
import { ProposalOptionRow } from "./ProposalOptionRow.tsx";
import { CapabilityActivityRow } from "./CapabilityActivitySection.tsx";
import { projectCharacterDesignerNumbers } from "./characterOccurrenceProjection.ts";
import { StageThread } from "./StageThread.tsx";
import { AgentCapabilityIdentity } from "./AgentCapabilityIdentity.tsx";
import { prepareRoleVisual } from "./agent-role-animation/agentRoleVisualResource.ts";
import { roleVisualMode } from "./agent-role-animation/useAgentRoleVisual.ts";
import { useTimelineRoleLifecycles } from "./agent-role-animation/roleLifecycleProjection.ts";
import { buildStageThreadTimeline } from "./stageThreadProjection.ts";
import { ConversationNodeLinks } from "./ConversationNodeLinks.tsx";
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
import { agentWorkingMessage } from "./agentWorkingMessage.ts";
import type { UiMessageKey } from "../../../i18n/uiMessages.ts";
import { EMPTY_RENDERED_CANVAS_NODE_IDS, isRenderedNodeCreation, isSuccessfulNodeCreation, useCanvasReceiptVisibility } from "./useCanvasReceiptVisibility.ts";
import { useComposerContext } from "./useComposerContext.ts";
import { GuidedAnswerBubble } from "./GuidedAnswerBubble.tsx";
import { GuidedQuestionBubble } from "./GuidedQuestionBubble.tsx";
import { AgentThinkingBlock } from "./AgentThinkingBlock.tsx";
import { LiveAssistantTurn } from "./LiveAssistantTurn.tsx";
import { brandThinkingAnchor, thinkingAnchorForItem, streamHasTimelineTarget } from "./thinkingAnchors.ts";
import type { PresentationStreamView } from "../runtime/useAgentCanvasPresentationStreams.ts";
import type { BrandDecisionPanelV1, BrandStageV2 } from "../brand/brandDecisions.ts";
import { BrandSkillPicker } from "../brand/BrandSkillPicker.tsx";
import { failureUserAction } from "./actionableFailure.ts";
import { VirtualizedTimeline } from "./VirtualizedTimeline.tsx";
import { FailedTurnBubble } from "./FailedTurnBubble.tsx";
import { projectFailedMessageTurns } from "./failedTurnPresentation.ts";
import {
  isPersistedGuidedAnswerMessage,
  projectPendingGuidedQuestions,
  type GuidedAnswerBubbleV1,
} from "./guidedAnswerPresentation.ts";
import { proposalReply } from "./conversationExchange.ts";
import { localizePromptPreparation, reducePlanningNoise } from "./planningNoise.ts";
import { projectBrandSummaries, type BrandSummaryExchange } from "./brandFormSummary.ts";
import { BrandSummaryBubbles, ProposalReplyBubble } from "./ConversationExchange.tsx";
import "./agent-canvas-chat.css";

type ChatPanelResizeSession = {
  pointerId: number;
  startX: number;
  startWidth: number;
  bounds: AgentChatResizeBounds;
};

type TimelineRenderOptions = {
  compactCapability?: boolean;
  proposalActivity?: ChatCapabilityActivityV2;
};

type TimelineEntry =
  | { entry_type: "timeline"; key: string; sequence: number; unit: ReturnType<typeof buildStageThreadTimeline>[number] }
  | { entry_type: "brand_summary"; key: string; sequence: number; summary: BrandSummaryExchange }
  | { entry_type: "guided_answer"; key: string; sequence: number; answer: GuidedAnswerBubbleV1 }
  | { entry_type: "guided_question"; key: string; sequence: number; label: string }
  | { entry_type: "failed_turn"; key: string; sequence: number; turn: AgentCanvasChatTurnV2 };

function timelineEntryKey(entry: TimelineEntry) {
  return entry.key;
}

export function TimelineHydrationSkeleton({
  itemType,
}: {
  itemType: "proposal" | "decision_bundle";
}) {
  const t = useTranslation();
  const label = itemType === "proposal" ? "proposal" : "decision bundle";
  return (
    <div className="agent-chat__timeline-hydration" role="status" aria-label={`Loading ${label}`}>
      <span className="agent-chat__timeline-hydration-kicker">{itemType === "proposal" ? t("Decision") : t("Guidance")}</span>
      <span className="agent-chat__timeline-hydration-line agent-chat__timeline-hydration-line--wide" />
      <span className="agent-chat__timeline-hydration-line" />
      <small>Loading {label}…</small>
    </div>
  );
}

export { GuidanceSessionProgress } from "./GuidanceSessionProgress.tsx";
export { CapabilityActivityRow } from "./CapabilityActivitySection.tsx";

function interactionRevisionKey(interaction: GuidedInteractionV1): string {
  return JSON.stringify([interaction.workflow_id, interaction.interaction_id, interaction.revision]);
}

export function AgentCanvasChatPanel({
  workflow,
  chatRevision,
  chatEvents,
  documentEvents = [],
  onFocusNode,
  onActionReceipt,
  onWorkflowRefresh,
  onRuntimeRefresh,
  onAssetsRefresh,
  brandMode = false,
  brandStage = null,
  brandContextReady = true,
  brandTreatmentReady = false,
  brandDecisions = null,
  brandSkillPickerOpen = false,
  onBrandSkillPickerOpen,
  onBrandSkillPickerClose,
  onBrandDecisionsUpdated,
  onBrandDecisionsRefresh,
  onProjectsRefresh,
  onPresentationStreamsChange,
  collapsed: controlledCollapsed,
  onCollapsedChange,
  onViewNodes,
  renderedCanvasNodeIds = EMPTY_RENDERED_CANVAS_NODE_IDS,
}: {
  workflow: AgentCanvasWorkflowV2;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  documentEvents?: CanvasRuntimeEventV2[];
  onFocusNode: (nodeId: string) => void;
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
  onRuntimeRefresh?: () => Promise<void> | void;
  onAssetsRefresh?: () => Promise<void> | void;
  brandMode?: boolean;
  brandStage?: BrandStageV2 | null;
  brandContextReady?: boolean;
  brandTreatmentReady?: boolean;
  brandDecisions?: BrandDecisionPanelV1 | null;
  brandSkillPickerOpen?: boolean;
  onBrandSkillPickerOpen?: () => void;
  onBrandSkillPickerClose?: () => void;
  onBrandDecisionsUpdated?: (panel: BrandDecisionPanelV1) => void;
  onBrandDecisionsRefresh?: () => Promise<BrandStageV2 | null> | BrandStageV2 | null;
  onProjectsRefresh?: () => Promise<boolean> | void;
  onPresentationStreamsChange?: (streams: Record<string, PresentationStreamView>) => void;
  runtime?: CanvasRuntimeSnapshotV2 | null;
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  onViewNodes?: (nodeIds: string[]) => void;
  renderedCanvasNodeIds?: ReadonlySet<string>;
}) {
  const t = useTranslation();
  const chat = useAgentCanvasChat({
    workflow,
    chatRevision,
    chatEvents,
    onActionReceipt,
    onWorkflowRefresh,
    onRuntimeRefresh,
    onAssetsRefresh,
    brandMode,
    brandStage,
    brandContextReady,
    onBrandDecisionsRefresh,
    onBrandDecisionsUpdated,
  });
  useEffect(() => {
    onPresentationStreamsChange?.(chat.state.presentationStreams ?? {});
  }, [chat.state.presentationStreams, onPresentationStreamsChange]);
  const [draft, setDraft] = useState("");
  const [internalCollapsed, setInternalCollapsed] = useState(false);
  const collapsed = controlledCollapsed ?? internalCollapsed;
  const [chatPanelWidth, setChatPanelWidth] = useState<number | null>(null);
  const [chatPanelResizing, setChatPanelResizing] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const skillLocale = useUiLocale(chat.state.guidanceSession?.response_locale ?? "en-US");
  const activeSkillTitle = workflow.active_style_skill ? skillDisplayTitle(workflow.active_style_skill, skillLocale) : null;
  const [selectedSkillTitle, setSelectedSkillTitle] = useState<string | null>(activeSkillTitle);
  const [selectedConceptOptionId, setSelectedConceptOptionId] = useState<string | null>(null);
  const [optimisticProposalSelections, setOptimisticProposalSelections] = useState<Record<string, string>>({});
  const [submittedInteractionKey, setSubmittedInteractionKey] = useState<string | null>(null);
  const [interactionDockCollapsed, setInteractionDockCollapsed] = useState(false);
  const [brandConfirmation, setBrandConfirmation] = useState<{
    workflowId: string; sequence: number; kind: "information" | "skills";
  } | null>(null);
  const brandConfirmationSequenceRef = useRef(0);
  const [brandFormDraft, setBrandFormDraft] = useState<{
    stage: "brand-memory" | "campaign";
    answers: BrandFormAnswers;
  } | null>(null);
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
    setSelectedSkillTitle(activeSkillTitle);
  }, [
    activeSkillTitle,
    workflow.active_style_skill?.skill_run_id,
    workflow.workflow_id,
  ]);
  useEffect(() => {
    setPendingContextFiles([]);
    setBrandFormDraft(null);
    setBrandConfirmation(null);
  }, [workflow.workflow_id]);
  const standaloneGuidedInteraction = chat.state.guidedInteraction
    && shouldRenderStandaloneInteraction(chat.state.guidedInteraction)
    ? chat.state.guidedInteraction
    : null;
  const shownInteractionKey = standaloneGuidedInteraction ? interactionRevisionKey(standaloneGuidedInteraction) : null;
  const shownInteractionKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (shownInteractionKey === shownInteractionKeyRef.current) return;
    shownInteractionKeyRef.current = shownInteractionKey;
    if (shownInteractionKey !== null && standaloneGuidedInteraction?.status === "open") {
      setInteractionDockCollapsed(false);
    }
  }, [shownInteractionKey, standaloneGuidedInteraction?.status]);
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
  const characterDesignerNumbers = useMemo(() => projectCharacterDesignerNumbers(
    chat.state.items.flatMap(item => item.item_type === "proposal" ? [item.proposal] : []),
    chat.state.guidanceSession?.journey,
    chat.state.turnsById,
  ), [chat.state.items, chat.state.guidanceSession?.journey, chat.state.turnsById]);
  const conceptInteraction = standaloneGuidedInteraction?.content.content_kind === "concept_choice"
    ? standaloneGuidedInteraction
    : null;
  const conceptContent = conceptInteraction?.content.content_kind === "concept_choice"
    ? conceptInteraction.content
    : null;
  const conceptActionId = conceptContent?.action_id ?? null;
  const currentInteractionSubmitted = Boolean(shownInteractionKey && shownInteractionKey === submittedInteractionKey);
  const conceptInteractionPending = Boolean(
    conceptInteraction
    && (currentInteractionSubmitted || conceptInteraction.status === "submitted"
      || chat.state.actingInteractionId === conceptInteraction.interaction_id
      || chat.state.brandCardLocked),
  );
  const currentInteractionOptimisticallyDismissed = currentInteractionSubmitted && !conceptInteraction
    && standaloneGuidedInteraction?.content.content_kind !== "brand_form";
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
  const [presentedInteractionKey, setPresentedInteractionKey] = useState<string | null>(null);
  // New cards wait for their action state and proposal detail. Later background
  // refreshes must not unmount a card the user is already filling in.
  const waitingForInteraction = Boolean(
    standaloneGuidedInteraction?.status === "open"
    && !currentInteractionSubmitted
    && shownInteractionKey !== presentedInteractionKey
    && (chat.state.loading || chat.state.sending || chat.state.agentWorking
      || !brandContextReady || standaloneGuidedReferences === null),
  );
  const workingMessage = useMemo(() => agentWorkingMessage({
    workflowId: workflow.workflow_id,
    items: chat.state.items,
    turnsById: chat.state.turnsById,
    journey: chat.state.guidanceSession?.journey,
    interaction: standaloneGuidedInteraction,
    waitingForInteraction,
    brandStage: brandMode ? brandStage : null,
  }), [workflow.workflow_id, chat.state.items, chat.state.turnsById, chat.state.guidanceSession?.journey,
    standaloneGuidedInteraction, waitingForInteraction, brandMode, brandStage]);
  useEffect(() => {
    if (shownInteractionKey && !waitingForInteraction) setPresentedInteractionKey(shownInteractionKey);
  }, [shownInteractionKey, waitingForInteraction]);

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
  const visibleChatItems = useCanvasReceiptVisibility(workflow.workflow_id, chat.state.items, renderedCanvasNodeIds);
  const stageTimeline = useMemo(
    () => buildStageThreadTimeline(
      reducePlanningNoise(
        visibleChatItems.filter((item) => !isPersistedGuidedAnswerMessage(item)),
        { agentWorking: chat.state.agentWorking },
      ).map((item) => (
        item.item_type === "message" ? localizePromptPreparation(item, t) : item
      )),
      {
        showUnassociatedPlanning: chat.state.agentWorking,
        showAllUnassociatedPlanning: brandMode,
      },
    ),
    [brandMode, chat.state.agentWorking, visibleChatItems, t],
  );
  const failedTurnsByMessageId = useMemo(
    () => projectFailedMessageTurns(chat.state.items, chat.state.turnsById),
    [chat.state.items, chat.state.turnsById],
  );
  const brandSummaries = useMemo(
    () => projectBrandSummaries(brandDecisions, chat.state.items, chat.state.guidedAnswerBubbles),
    [brandDecisions, chat.state.items, chat.state.guidedAnswerBubbles],
  );
  const proposalQuestions = useMemo(() => new Map(chat.state.items.flatMap((item) => {
    if (item.item_type !== "proposal" && item.item_type !== "proposal_pointer") return [];
    const proposalId = item.item_type === "proposal" ? item.proposal.proposal_id : item.proposal_id;
    const interaction = standaloneGuidedInteraction;
    const currentQuestion = interaction?.content.content_kind === "concept_choice"
      && interaction.content.proposal_id === proposalId ? interaction.title : null;
    const answer = chat.state.guidedAnswerBubbles.find(answer => answer.proposal_id === proposalId);
    const label = currentQuestion || answer?.label || (item.item_type === "proposal"
      ? conceptProposalQuestion(item.proposal.options) : item.question);
    return label ? [[proposalId, label] as const] : [];
  })), [chat.state.items, chat.state.guidedAnswerBubbles, standaloneGuidedInteraction]);
  const currentProposalOwnsQuestion = standaloneGuidedInteraction?.content.content_kind === "concept_choice"
    && Boolean(standaloneGuidedInteraction.content.proposal_id
      && proposalQuestions.has(standaloneGuidedInteraction.content.proposal_id));
  const timelineEntries = useMemo<TimelineEntry[]>(() => [
    ...stageTimeline.flatMap((unit): TimelineEntry[] => {
      const timelineEntry: TimelineEntry = {
        entry_type: "timeline",
        key: `timeline:${unit.key}`,
        sequence: unit.sequence,
        unit,
      };
      if (unit.unit_type !== "item" || unit.item.item_type !== "message") {
        return [timelineEntry];
      }
      const failedTurn = failedTurnsByMessageId.get(unit.item.message_id);
      return failedTurn ? [
        timelineEntry,
        {
          entry_type: "failed_turn",
          key: `failed-turn:${failedTurn.turn_id}`,
          sequence: unit.sequence,
          turn: failedTurn,
        },
      ] : [timelineEntry];
    }),
    // A summary replaces only its own exchange; earlier choices remain in history.
    ...chat.state.guidedAnswerBubbles.filter((answer) => (
      !brandSummaries.some((summary) => summary.answer?.bubble_id === answer.bubble_id)
    )).map((answer): TimelineEntry => ({
      entry_type: "guided_answer",
      key: answer.bubble_id,
      sequence: answer.sequence,
      answer,
    })),
    ...projectPendingGuidedQuestions(currentProposalOwnsQuestion ? null : standaloneGuidedInteraction, chat.state.guidedAnswerBubbles)
      .map((question, index): TimelineEntry => ({
        entry_type: "guided_question",
        key: question.bubble_id,
        sequence: Math.max(0,
          ...chat.state.items.map((item) => item.sequence),
          ...chat.state.guidedAnswerBubbles.map((answer) => answer.sequence),
        ) + (index + 1) / 100,
        label: question.label,
      })),
    ...brandSummaries
      .map((summary): TimelineEntry => ({
        entry_type: "brand_summary",
        key: summary.key,
        sequence: summary.sequence,
        summary,
      })),
  ].sort((left, right) => left.sequence - right.sequence), [
    brandSummaries,
    chat.state.guidedAnswerBubbles,
    chat.state.items,
    failedTurnsByMessageId,
    currentProposalOwnsQuestion,
    stageTimeline,
    standaloneGuidedInteraction,
  ]);
  const answeredProposalIds = useMemo(() => new Set(chat.state.guidedAnswerBubbles.flatMap((answer) => (
    answer.proposal_id ? [answer.proposal_id] : []
  ))), [chat.state.guidedAnswerBubbles]);
  const roleThreads = useMemo(
    () => stageTimeline.filter((unit) => unit.unit_type === "stage_thread"), [stageTimeline],
  );
  const stageRoleLifecycles = useTimelineRoleLifecycles({
    threads: roleThreads,
    workflowId: workflow.workflow_id,
    turnsById: chat.state.turnsById,
    conversationWorking: chat.state.agentWorking,
  });
  const stageRoleMotionStates = useMemo(() => new Map(
    [...stageRoleLifecycles].map(([key, lifecycle]) => [key, lifecycle.motionState]),
  ), [stageRoleLifecycles]);
  useLayoutEffect(() => {
    for (const unit of stageTimeline) {
      if (unit.unit_type !== "stage_thread") continue;
      prepareRoleVisual(unit.capability_id, roleVisualMode(stageRoleMotionStates.get(unit.key) ?? "idle"));
    }
  }, [stageTimeline, stageRoleMotionStates]);
  const conversationLinkIndex = useMemo(
    () => buildConversationCanvasLinkIndex(stageTimeline, chat.state.guidanceAwaiting),
    [chat.state.guidanceAwaiting, stageTimeline],
  );
  const viewNodes = onViewNodes ?? ((nodeIds: string[]) => {
    if (nodeIds[0]) onFocusNode(nodeIds[0]);
  });
  const naturalMessagePresentation = useMemo(
    () => projectNaturalMessagePresentation(chat.state.items),
    [chat.state.items],
  );
  const typewriterPlayback = useMemo(() => ({
    workflowId: workflow.workflow_id,
    cache: new Map<string, string>(),
  }), [workflow.workflow_id]);
  const assistantStreams = useMemo(
    () => Object.values(chat.state.presentationStreams ?? {}).filter(view => view.stream_kind === "assistant"),
    [chat.state.presentationStreams],
  );
  const liveAssistantStreams = useMemo(
    () => assistantStreams.filter((view) => (
      !streamHasTimelineTarget(view, chat.state.items)
      && (["connecting", "open", "reconnecting"].includes(view.status)
        // Keep the answer visible while its committed timeline item is loading.
        || (view.status === "completed" && Boolean(view.text) && view.authoritative_id !== null
          && !view.generation_id?.startsWith("brand-gen:")))
      && (Boolean(view.reasoning_text) || Boolean(view.text))
    )),
    [assistantStreams, chat.state.items],
  );
  const timelineContentVersion = useMemo(() => {
    const latestItem = chat.state.items[chat.state.items.length - 1];
    const sessionActions = chat.state.currentSessionActions
      .map((action) => `${action.action_id}:${action.state}`)
      .join(",");
    const interactionVersion = guidedInteractionContentVersion(chat.state.guidedInteraction);
    const guidedAnswerVersion = chat.state.guidedAnswerBubbles
      .map((answer) => `${answer.bubble_id}:${answer.sequence}`)
      .join(",");
    const failedTurnVersion = [...failedTurnsByMessageId.entries()]
      .map(([messageId, turn]) => `${messageId}:${turn.turn_id}:${turn.updated_at}`)
      .join(",");
    return `${chat.state.items.length}:${latestItem?.sequence ?? ""}:${interactionVersion}:${sessionActions}:${guidedAnswerVersion}:${failedTurnVersion}:${chat.state.agentWorking}`;
  }, [
    chat.state.agentWorking,
    chat.state.currentSessionActions,
    chat.state.guidedAnswerBubbles,
    chat.state.guidedInteraction,
    chat.state.items,
    failedTurnsByMessageId,
  ]);
  const timelineScroll = useChatTimelineScroll({
    contentVersion: timelineContentVersion,
    resetKey: workflow.workflow_id,
  });
  useEffect(() => {
    setSelectedConceptOptionId(null);
  }, [
    chat.state.brandCardLocked,
    conceptActionId,
    conceptInteraction?.interaction_id,
    conceptInteraction?.revision,
  ]);

  useEffect(() => {
    if (!submittedInteractionKey) return;
    const interaction = chat.state.guidedInteraction;
    if (!interaction || interactionRevisionKey(interaction) !== submittedInteractionKey) {
      optimisticInteractionSubmitSeqRef.current = null;
      setSubmittedInteractionKey(null);
      return;
    }
    const materializationFailed = chatEvents.some((event) => (
      event.workflow_id === workflow.workflow_id
      && (event.event_type === "proposal_materialization_failed" || event.event_type === "guided_product_source_failed")
      && event.seq > (optimisticInteractionSubmitSeqRef.current ?? -1)
      && (event.action_id === interaction.interaction_id
        || event.payload?.interaction_id === interaction.interaction_id)
    ));
    if (materializationFailed) {
      optimisticInteractionSubmitSeqRef.current = null;
      setSubmittedInteractionKey(null);
      setInteractionDockCollapsed(false);
    }
  }, [chat.state.guidedInteraction, chatEvents, submittedInteractionKey, workflow.workflow_id]);

  async function submitGuidedInteraction(
    interaction: NonNullable<typeof standaloneGuidedInteraction>,
    request: Parameters<typeof chat.actions.submitGuidedInteraction>[1],
  ) {
    const submissionKey = interactionRevisionKey(interaction);
    if (submittedInteractionKey === submissionKey) return false;
    if (interaction.content.content_kind === "concept_choice"
      && ["brand_skill-stack", "brand_skill-stack-early"].includes(interaction.content.capability_id)
      && request.submission_kind === "concept_choice"
      && (request.option_id === "adjust" || Boolean(request.custom_text))) {
      onBrandSkillPickerOpen?.();
      return false;
    }
    optimisticInteractionSubmitSeqRef.current = chatEvents.reduce(
      (latest, event) => Math.max(latest, event.seq),
      -1,
    );
    setSubmittedInteractionKey(submissionKey);
    const isBrandForm = interaction.content.content_kind === "brand_form";
    if (interaction.content.content_kind === "concept_choice" || isBrandForm) {
      setInteractionDockCollapsed(true);
    }
    // Acknowledge the click immediately, independently of the request and refreshes.
    const confirmation = isBrandForm ? {
      workflowId: interaction.workflow_id,
      sequence: ++brandConfirmationSequenceRef.current,
      kind: "information" as const,
    } : null;
    if (confirmation) setBrandConfirmation(confirmation);
    let accepted = false;
    try {
      accepted = await chat.actions.submitGuidedInteraction(interaction, request);
    } catch {
      accepted = false;
    }
    if (!accepted) {
      if (confirmation) setBrandConfirmation((current) => current === confirmation ? null : current);
      setSubmittedInteractionKey((current) => (
        current === submissionKey ? null : current
      ));
      if (shownInteractionKeyRef.current === submissionKey) {
        optimisticInteractionSubmitSeqRef.current = null;
        setInteractionDockCollapsed(false);
      }
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

  async function send(conceptOptionId: string | null = null) {
    const submittedDraft = draft;
    const text = submittedDraft.trim();
    if (chat.state.sending || conceptInteractionPending) return;

    if (conceptInteraction) {
      if (!conceptOptionId && !text) return;
      const request = buildConceptChoiceSubmitRequest({
        interaction: conceptInteraction,
        selectedOptionId: conceptOptionId,
        customText: text,
        proposalReferences: standaloneGuidedReferences,
      });
      if (!request) return;
      const optimisticProposalId = conceptOptionId ? conceptContent?.proposal_id : null;
      const previousOptimisticOptionId = optimisticProposalId
        ? optimisticProposalSelections[optimisticProposalId]
        : undefined;
      if (optimisticProposalId && conceptOptionId) {
        setOptimisticProposalSelections((current) => ({
          ...current,
          [optimisticProposalId]: conceptOptionId,
        }));
      }
      setDraft("");
      setMentionOpen(false);
      const accepted = await submitGuidedInteraction(conceptInteraction, request);
      if (!accepted) {
        if (shownInteractionKeyRef.current === interactionRevisionKey(conceptInteraction)) {
          setDraft((current) => current || submittedDraft);
        }
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
      if (shownInteractionKeyRef.current !== interactionRevisionKey(conceptInteraction)) return;
      setSelectedConceptOptionId(null);
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
    // Clear with the optimistic message, before waiting for server acceptance.
    setDraft("");
    setMentionOpen(false);
    const accepted = await chat.actions.submit(request);
    if (!accepted) {
      setDraft((current) => current || submittedDraft);
      return;
    }
    composerContext.actions.consumeSubmittedContext({
      nodeIds: submittedNodeIds,
      assetIds: submittedAssetIds,
    });
  }

  async function submitConceptChoiceCustom(text: string): Promise<boolean> {
    if (!conceptInteraction) return false;
    const request = buildConceptChoiceSubmitRequest({
      interaction: conceptInteraction,
      selectedOptionId: null,
      customText: text,
      proposalReferences: standaloneGuidedReferences,
    });
    if (!request) return false;
    return submitGuidedInteraction(conceptInteraction, request);
  }

  function renderStandaloneGuidedInteractionCard() {
    if (!standaloneGuidedInteraction || currentInteractionOptimisticallyDismissed) return null;
    const conceptContent = standaloneGuidedInteraction.content.content_kind === "concept_choice"
      ? standaloneGuidedInteraction.content
      : null;
    const proposals = conceptContent
      ? chat.state.items.filter((item): item is ChatProposalCardV2 => item.item_type === "proposal")
      : [];
    const conceptProposal = proposals.find((item) => item.proposal.proposal_id === conceptContent?.proposal_id)
      ?? proposals.findLast((item) => item.proposal.capability_id === conceptContent?.capability_id);
    // Match the card before reading its substep; decisions and chat refresh independently.
    const treatmentSubstep = brandDecisions?.workflow_id === workflow.workflow_id
      && brandDecisions.journey.stage === "treatment"
      && brandDecisions.open_card?.stage === "treatment"
      && brandDecisions.open_card.card_id === conceptContent?.action_id
      && brandDecisions.open_card.stage_revision === conceptContent.stage_revision
      ? brandDecisions.open_card.target_slot_id ?? brandDecisions.journey.treatment_substep
      : null;
    const card = (
      <GuidedInteractionCard
        key={standaloneGuidedInteraction.interaction_id}
        interaction={standaloneGuidedInteraction}
        conceptRoleName={conceptProposal?.proposal.capability_display_name ?? null}
        treatmentSubstep={treatmentSubstep}
        referenceOccurrenceLabel={referenceOccurrenceLabel}
        pending={
          currentInteractionSubmitted || standaloneGuidedInteraction.status === "submitted"
          || chat.state.actingInteractionId === standaloneGuidedInteraction.interaction_id
        }
        disabled={chat.state.brandCardLocked}
        issue={chat.state.guidedInteractionIssue}
        pendingProductMainHandoff={composerContext.productMainHandoff}
        onClearProductMainHandoff={composerContext.actions.clearProductMainHandoff}
        onProjectsRefresh={onProjectsRefresh}
        selectedConceptOptionId={conceptInteraction ? selectedConceptOptionId : null}
        onConfirmConceptOption={conceptInteraction && conceptSelectionReady && !chat.state.sending
          ? () => void send(selectedConceptOptionId) : undefined}
        brandFormAnswers={standaloneGuidedInteraction.content.content_kind === "brand_form"
          && brandFormDraft?.stage === standaloneGuidedInteraction.content.stage
          ? brandFormDraft.answers : {}}
        onBrandFormAnswersChange={(answers) => {
          if (standaloneGuidedInteraction.content.content_kind === "brand_form") {
            setBrandFormDraft({ stage: standaloneGuidedInteraction.content.stage, answers });
          }
        }}
        onSelectConceptOption={(optionId) => {
          if (conceptInteraction?.content.content_kind === "concept_choice"
            && ["brand_skill-stack", "brand_skill-stack-early"].includes(conceptInteraction.content.capability_id) && optionId === "adjust") {
            setSelectedConceptOptionId(null);
            setDraft("");
            onBrandSkillPickerOpen?.();
            return;
          }
          setSelectedConceptOptionId(optionId);
          setDraft("");
        }}
        onSelectConceptCustom={() => {
          setSelectedConceptOptionId(null);
          setDraft("");
        }}
        onSubmitCustom={conceptInteraction ? submitConceptChoiceCustom : undefined}
        onSubmit={(request) => submitGuidedInteraction(standaloneGuidedInteraction, request)}
      />
    );
    if (standaloneGuidedInteraction.content.content_kind !== "brand_form") return card;
    const formId = standaloneGuidedInteraction.content.form_id;
    const thinking = brandThinkingAnchor(Object.values(chat.state.presentationStreams ?? {}), [
      formId,
      `brand-form-intent:${formId}`,
    ]);
    return <>
      {thinking ? <AgentThinkingBlock
        reasoningText={thinking.reasoning_text}
        phase="done"
        durationSeconds={thinking.reasoning_started_at !== null && thinking.terminal_at_ms !== null
          ? Math.max(0, (thinking.terminal_at_ms - thinking.reasoning_started_at) / 1_000)
          : null}
      /> : null}
      {card}
    </>;
  }

  function renderTimelineItem(
    item: ChatTimelineItemV2,
    location: ConversationCanvasLocation | null = null,
    options: TimelineRenderOptions = {},
  ) {
    const thinking = !options.compactCapability
      ? thinkingAnchorForItem(Object.values(chat.state.presentationStreams ?? {}), item)
      : null;
    const content = renderTimelineItemContent(item, location, options);
    return thinking ? (
      <Fragment key={`thinking-anchor-${item.item_type}-${item.sequence}`}>
        <AgentThinkingBlock
          reasoningText={thinking.reasoning_text}
          phase="done"
          durationSeconds={thinking.reasoning_started_at !== null && thinking.terminal_at_ms !== null
            ? Math.max(0, (thinking.terminal_at_ms - thinking.reasoning_started_at) / 1_000)
            : null}
        />
        {content}
      </Fragment>
    ) : content;
  }

  function renderTimelineItemContent(
    item: ChatTimelineItemV2,
    location: ConversationCanvasLocation | null = null,
    options: TimelineRenderOptions = {},
  ) {
    if (item.item_type === "message") {
      const stream = assistantStreams.find(view => view.authoritative_id === item.message_id);
      const playbackKey = stream ? `stream:${stream.stream_id}` : `message:${item.message_id}`;
      return <NaturalMessage
        key={`message-${item.message_id}`}
        message={item}
        animate={(chat.state.initialTimelineSequence != null && item.sequence > chat.state.initialTimelineSequence)
          || Boolean(stream && typewriterPlayback.cache.has(playbackKey))}
        playback={{ cache: typewriterPlayback.cache, key: playbackKey }}
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
      const characterNumber = item.capability_id === "character_design"
        ? characterDesignerNumbers.get(item.turn_id) : undefined;
      return (
        <CapabilityActivityRow
          key={`activity-${item.activity_id}`}
          activity={item}
          displayName={characterNumber ? `${item.capability_display_name} ${characterNumber}` : undefined}
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
      if (isRenderedNodeCreation(item, renderedCanvasNodeIds)) return null;
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
      const question = proposalQuestions.get(item.proposal_id);
      return <>
        {question ? <GuidedQuestionBubble label={question} /> : null}
        <TimelineHydrationSkeleton itemType="proposal" />
      </>;
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
        {proposalQuestions.has(item.proposal.proposal_id) ? (
          <GuidedQuestionBubble label={proposalQuestions.get(item.proposal.proposal_id)!} />
        ) : null}
        {options.proposalActivity ? renderTimelineItem(options.proposalActivity, null, { compactCapability: true }) : null}
        <ProposalCard
          card={item}
          pending={chat.state.actingProposalId === item.proposal.proposal_id}
          compact={options.compactCapability}
          retryingMaterialization={Boolean(
            item.proposal.materialization
            && chat.state.retryingSourceTurnIds[item.proposal.materialization.turn_id]
          )}
          onRetryMaterialization={item.proposal.materialization
            ? () => chat.actions.retryProposalMaterialization(item.proposal.materialization!)
            : undefined}
          onRevise={(proposalId, action, instruction) => (
            chat.actions.reviseProposal(proposalId, action, instruction)
          )}
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

  const brandSkillPicker = brandDecisions?.workflow_id === workflow.workflow_id ? (
    <BrandSkillPicker key={workflow.workflow_id} decisions={brandDecisions}
      open={brandSkillPickerOpen}
      responseLocale={chat.state.guidanceSession?.response_locale ?? "und"}
      onClose={() => onBrandSkillPickerClose?.()}
      onUpdated={(panel) => onBrandDecisionsUpdated?.(panel)}
      onConfirmed={(panel) => {
        if (panel.workflow_id !== workflow.workflow_id) return;
        if (brandSkillPickerOpen) onBrandSkillPickerClose?.();
        // The picker commits outside the chat submit path. Retire its old card
        // while the next question is still being generated.
        if (conceptInteraction && conceptContent
          && ["brand_skill-stack", "brand_skill-stack-early"].includes(conceptContent.capability_id)
          && conceptContent.stage_revision < panel.journey.stage_revision) {
          optimisticInteractionSubmitSeqRef.current = chatEvents.reduce(
            (latest, event) => Math.max(latest, event.seq), -1,
          );
          setSubmittedInteractionKey(interactionRevisionKey(conceptInteraction));
          setInteractionDockCollapsed(true);
        }
        setBrandConfirmation({
          workflowId: panel.workflow_id,
          sequence: ++brandConfirmationSequenceRef.current,
          kind: "skills",
        });
      }}
      onConversationRefresh={async () => {
        await chat.actions.refresh();
        await onWorkflowRefresh?.();
      }} />
  ) : null;

  const brandConfirmationToast = brandConfirmation?.workflowId === workflow.workflow_id
    ? <BrandFormConfirmationToast key={`${brandConfirmation.workflowId}:${brandConfirmation.sequence}`} kind={brandConfirmation.kind} />
    : null;

  if (collapsed) {
    return (
      <>
      {brandConfirmationToast}
      {brandSkillPicker}
      <button
        className="agent-chat__collapsed-trigger"
        type="button"
        aria-label={t("Open AdCraft Bot panel")}
        title={t("Open AdCraft Bot")}
        onClick={() => {
          setInternalCollapsed(false);
          onCollapsedChange?.(false);
        }}
      >
        <img src="/imgs/logo.png" alt="" />
        <span>{t("AdCraft Bot")}</span>
      </button>
      </>
    );
  }

  return (
    <>
    {brandConfirmationToast}
    {brandSkillPicker}
    <aside
      ref={chatPanelRef}
      className={`agent-chat${chatPanelResizing ? " is-resizing" : ""}`}
      style={chatPanelWidth === null ? undefined : { width: `${chatPanelWidth}px` }}
      aria-label={t("AdCraft Video Agent")}
    >
      <button
        className="agent-chat__resize-handle"
        type="button"
        aria-label={t("Resize AdCraft Video Agent panel")}
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
          <img className="agent-chat__logo" src="/imgs/logo.png" alt="" width={36} height={36} />
          <strong>{t("AdCraft Video Agent")}</strong>
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
            aria-label={t("Collapse AdCraft Bot panel")}
            title={t("Collapse AdCraft Bot")}
            onClick={() => {
              setInternalCollapsed(true);
              onCollapsedChange?.(true);
            }}
          >
            <ChevronRightIcon />
          </button>
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
              <div className="agent-chat__empty">{t("Loading conversation...")}</div>
            ) : null}
            {!chat.state.loading
              && !timelineEntries.length
              && !chat.state.currentSessionActions.length ? (
              <div className="agent-chat__empty">{t("Describe the ad you want to build.")}</div>
            ) : null}
            {chat.state.continuations
              .filter((continuation) => ["queued", "leased", "retry_wait"].includes(continuation.delivery_status))
              .map((continuation) => (
                <ContinuationActivityRow key={continuation.continuation_id} continuation={continuation} />
              ))}
            <VirtualizedTimeline
              items={timelineEntries}
              getKey={timelineEntryKey}
              renderItem={(entry) => {
                if (entry.entry_type === "brand_summary") {
                  return <BrandSummaryBubbles summary={entry.summary}
                    showQuestion={!entry.summary.answer?.proposal_id || !proposalQuestions.has(entry.summary.answer.proposal_id)} />;
                }
                if (entry.entry_type === "guided_question") {
                  return (
                    <div className="agent-chat__pending-question">
                      <GuidedQuestionBubble label={entry.label} />
                    </div>
                  );
                }
                if (entry.entry_type === "guided_answer") {
                  return <GuidedAnswerBubble answer={entry.answer}
                    showQuestion={!entry.answer.proposal_id || !proposalQuestions.has(entry.answer.proposal_id)} />;
                }
                if (entry.entry_type === "failed_turn") {
                  return (
                    <FailedTurnBubble
                      turn={entry.turn}
                      retrying={Boolean(chat.state.retryingSourceTurnIds[entry.turn.turn_id])}
                      onRetry={() => void chat.actions.retryTurn(entry.turn)}
                    />
                  );
                }
                const unit = entry.unit;
                const location = conversationLinkIndex.locations.get(unit.key) ?? null;
                if (unit.unit_type === "item") {
                  return renderTimelineItem(unit.item, location);
                }
                const visibleReceipts = unit.receipts.filter((item) => (
                  (isSuccessfulNodeCreation(item) && !isRenderedNodeCreation(item, renderedCanvasNodeIds))
                  || item.action_receipt.status === "failed"
                  || item.action_receipt.status === "rejected"
                  || item.action_receipt.status === "not_applied"
                  || item.action_receipt.status === "applied_with_run_error"
                ));
                // Keep each production status with the proposal produced by that Turn.
                const proposalActivities = new Map<string, ChatCapabilityActivityV2>();
                const movedActivityIds = new Set<string>();
                for (const activity of unit.activities) {
                  const proposal = unit.proposals.find(({ proposal }) => proposal.turn_id === activity.turn_id);
                  if (!proposal) continue;
                  proposalActivities.set(proposal.proposal.proposal_id, activity);
                  movedActivityIds.add(activity.activity_id);
                }
                return (
                  <StageThread
                    unit={unit}
                    motionState={stageRoleMotionStates.get(unit.key) ?? "idle"}
                    result={location ? (
                      <ConversationNodeLinks
                        location={location}
                        nodes={workflow.nodes}
                        variant="result"
                        onViewNodes={viewNodes}
                      />
                    ) : null}
                  >
                    {[
                      ...unit.planning,
                      ...unit.activities.filter(activity => !movedActivityIds.has(activity.activity_id)),
                      ...unit.proposals,
                      ...visibleReceipts,
                    ]
                      .sort((left, right) => left.sequence - right.sequence)
                      .map((item) => {
                        const content = renderTimelineItem(item, null, {
                          compactCapability: true,
                          proposalActivity: item.item_type === "proposal"
                            ? proposalActivities.get(item.proposal.proposal_id) : undefined,
                        });
                        // The user's choice reads as their reply right after the proposal it answers;
                        // a choice made in the decision dock already has its own answer bubble.
                        if (item.item_type !== "proposal" || answeredProposalIds.has(item.proposal.proposal_id)) {
                          return content;
                        }
                        const reply = proposalReply(item, optimisticProposalSelections[item.proposal.proposal_id] ?? null);
                        return reply ? (
                          <Fragment key={`proposal-reply-${item.proposal.proposal_id}`}>
                            {content}
                            <ProposalReplyBubble reply={reply} />
                          </Fragment>
                        ) : content;
                      })}
                  </StageThread>
                );
              }}
            />
            {chat.state.currentSessionActions.length ? (
              <GuidedActionsCard
                actions={chat.state.currentSessionActions}
                actingActionId={chat.state.actingGuidedActionId}
                onApply={chat.actions.applyGuidedAction}
              />
            ) : null}
            {liveAssistantStreams.length ? (
              liveAssistantStreams.map((view) => <LiveAssistantTurn key={view.stream_id} view={view}
                playback={{ cache: typewriterPlayback.cache, key: `stream:${view.stream_id}` }} />)
            ) : chat.state.agentWorking && !waitingForInteraction ? (
              <AgentWorkingRow messageKey={workingMessage} />
            ) : null}
            {waitingForInteraction ? <AgentWorkingRow messageKey={workingMessage} /> : null}
            {chat.state.timelineRecovery ? (
              <ConversationRecoverySurface
                recovery={chat.state.timelineRecovery}
                onAction={() => void chat.actions.refresh()}
                onDismiss={chat.actions.clearTimelineRecovery}
              />
            ) : null}
          </div>
        </div>
        {timelineScroll.hasUnseenContent ? (
          <button
            className="agent-chat__jump-to-latest"
            type="button"
            aria-label={t("Jump to latest message")}
            title={t("Jump to latest message")}
            onClick={timelineScroll.followLatest}
          >
            <ChevronDownIcon />
          </button>
        ) : null}
        {standaloneGuidedInteraction && !currentInteractionOptimisticallyDismissed
          && !waitingForInteraction
          && interactionDockCollapsed ? (
          <button
            className="agent-chat__interaction-chip"
            type="button"
            aria-expanded="false"
            onClick={() => setInteractionDockCollapsed(false)}
          >
            <strong>{standaloneGuidedInteraction.content.content_kind === "product_source"
              ? productSourceCopy(standaloneGuidedInteraction.title, t)
              : standaloneGuidedInteraction.title}</strong>
            <span>{t(currentInteractionSubmitted || standaloneGuidedInteraction.status === "submitted"
              ? "Working" : "Pending your choice")}</span>
            <ChevronUpIcon />
          </button>
        ) : null}
        {/* Collapsing hides the card instead of unmounting it so drafts and scroll position survive. */}
        {standaloneGuidedInteraction && !currentInteractionOptimisticallyDismissed && !waitingForInteraction ? (
          <div
            hidden={interactionDockCollapsed}
            className={`agent-chat__current-interaction agent-chat__current-interaction--overlay${standaloneGuidedInteraction.content.content_kind === "brand_form" ? ` agent-chat__current-interaction--brand-form${standaloneGuidedInteraction.content.rows.some(row => row.options.filter(option => option.option_id !== row.custom_option_id).length > 3) ? " agent-chat__current-interaction--brand-form-expanded" : ""}` : ""}${isBrandCustomInputCard(standaloneGuidedInteraction) ? ` agent-chat__current-interaction--brand-custom-input${standaloneGuidedInteraction.content.content_kind === "concept_choice" && standaloneGuidedInteraction.content.options.length > 3 ? " agent-chat__current-interaction--brand-custom-input-expanded" : ""}` : ""}`}
            aria-live="polite"
          >
            <button
              className="agent-chat__interaction-collapse"
              type="button"
              aria-label={t("Collapse decision card")}
              title={t("Collapse decision card")}
              aria-expanded="true"
              onClick={() => setInteractionDockCollapsed(true)}
            >
              <ChevronDownIcon />
            </button>
            {renderStandaloneGuidedInteractionCard()}
          </div>
        ) : null}
      </div>

      {brandMode && brandStage !== "production" && !brandTreatmentReady
        && !brandDecisions?.open_card && !chat.state.brandCardRecovery
        && (chat.state.brandNextQuestionIssue || (brandDecisions?.continuation?.status === "failed"
          && brandDecisions.continuation.retryable)) ? (
        <section className="agent-chat__recovery is-interaction" role="alert">
          <div className="agent-chat__recovery-copy">
            <strong>{t("The current Brand step could not finish")}</strong>
            <p>{t("Your selected direction is saved. Retry to continue from the unfinished step.")}</p>
          </div>
          <div className="agent-chat__recovery-actions">
            <button type="button" disabled={chat.state.brandNextQuestionPending || chat.state.sending}
              onClick={() => void chat.actions.retryBrandNextQuestion(true)}>
              {chat.state.brandNextQuestionPending ? t("Refreshing...") : t("Retry")}
            </button>
          </div>
        </section>
      ) : null}

      {chat.state.brandCardRecovery ? <BrandCardRecoveryNotice
        state={chat.state.brandCardRecovery} busy={chat.state.brandCardRecoveryBusy}
        onRefresh={() => { setSelectedConceptOptionId(null); setDraft(""); void chat.actions.refreshBrandCard(); }}
      /> : null}

      {chat.state.composerRecovery ? (
        <ConversationRecoverySurface
          recovery={chat.state.composerRecovery}
          onAction={chat.state.failedDraft ? async () => {
            const failedDraft = chat.state.failedDraft!;
            const draftAtRetry = draft;
            const retryingCurrentDraft = draftAtRetry.trim() === failedDraft.text;
            if (retryingCurrentDraft) setDraft("");
            setMentionOpen(false);
            const accepted = await chat.actions.submit(failedDraft);
            if (!accepted) {
              if (retryingCurrentDraft) setDraft((current) => current || draftAtRetry);
              return;
            }
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
          <button type="button" aria-label={t("Dismiss notice")} onClick={chat.actions.clearNotice}>
            <CloseIcon />
          </button>
        </div>
      ) : null}

      {composerContext.view.uploadState === "uploading" ? (
        <div className="agent-chat__context-uploading" role="status">
          {t("Uploading context asset…")}</div>
      ) : null}

      {composerContext.uploadIssue ? (
        <ConversationRecoverySurface
          recovery={composerContext.uploadIssue}
          onDismiss={composerContext.actions.clearUploadIssue}
        />
      ) : null}

      {brandMode && brandStage === "treatment" && brandTreatmentReady ? (
        <BrandTreatmentConfirmation
          onProductionRefresh={onWorkflowRefresh}
          key={workflow.workflow_id}
          workflowId={workflow.workflow_id}
          responseLocale={chat.state.guidanceSession?.response_locale ?? "und"}
          onConfirmed={async () => {
            await onBrandDecisionsRefresh?.();
            await chat.actions.refresh();
          }}
        />
      ) : null}

      <div className="agent-chat__composer">
        {pendingContextFiles.length ? (
          <div className="agent-chat__product-upload-choice" role="status">
            <span>
              {pendingContextFiles.length === 1
                ? t("Use this image as Product Main?")
                : t("Use the first image as Product Main?")}
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
                {t("Product Main")}</button>
              <button
                type="button"
                onClick={() => {
                  const files = pendingContextFiles;
                  setPendingContextFiles([]);
                  void composerContext.actions.upload(files, { semanticRole: null });
                }}
                disabled={chat.state.sending || composerContext.view.uploadState === "uploading"}
              >
                {t("Keep unclassified")}</button>
              <button
                type="button"
                aria-label={t("Cancel image upload")}
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
              <strong>{t("Product Main")}</strong>
              <small>{composerContext.productMainHandoff.displayName}</small>
            </span>
            <button
              type="button"
              aria-label={t("Clear Product Main handoff")}
              onClick={composerContext.actions.clearProductMainHandoff}
            >
              <CloseIcon />
            </button>
          </div>
        ) : null}
        {conceptInteraction ? (
          <div className="agent-chat__guided-composer-hint" role="status">
            {t("You can also describe your own direction below.")}</div>
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
            ? t("Describe your own direction...")
            : t("Ask AdCraft Video Agent...")}
          aria-label={t("Message AdCraft Video Agent")}
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
              aria-label={t("Mention node or image asset")}
              title={t("Mention node or image asset")}
              disabled={Boolean(conceptInteraction) || chat.state.sending}
              onClick={() => setMentionOpen((current) => !current)}
            >
              @
            </button>
            {!conceptInteraction ? (
              <>
                <button
                  type="button"
                  aria-label={t("Upload context images")}
                  title={t("Upload context images")}
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
            {brandMode ? (
              <button type="button" aria-label={t("Choose Skills")} title={t("Choose Skills")}
                disabled={!brandContextReady || chat.state.sending || !["skill-stack", "skill-stack-early"].includes(brandStage ?? "") || brandDecisions?.open_card?.stage !== brandStage}
                onClick={onBrandSkillPickerOpen}>
                <img src="/imgs/ui-icons/skill.svg" alt="" aria-hidden="true" width={20} height={20} />
              </button>
            ) : <AgentCanvasStyleSelector
              workflowId={workflow.workflow_id}
              activeStyle={workflow.active_style_skill}
              onWorkflowRefresh={() => onWorkflowRefresh?.()}
              onSkillSelected={setSelectedSkillTitle}
            />}
          </div>
          <button
            type="button"
            className="agent-chat__send"
            aria-label={conceptInteraction ? t("Submit guided direction") : t("Send message")}
            title={conceptInteraction ? t("Submit guided direction") : t("Send message")}
            disabled={conceptInteraction
              ? (!draft.trim() || !conceptCustomAllowed || chat.state.sending
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
              <h4>{t("Nodes")}</h4>
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
              <h4>{t("Image assets")}</h4>
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
    </>
  );
}

export function AgentWorkingRow({ messageKey = "Agent is working..." }: { messageKey?: UiMessageKey }) {
  const t = useTranslation();
  const label = t(messageKey);
  const characters = Array.from(label);
  const characterIntervalMs = 140;
  const cycleMs = characters.length * characterIntervalMs + 900;
  return (
    <div
      className="agent-chat__working"
      role="status"
      aria-label={messageKey === "Agent is working..." ? t("AdCraft Video Agent is working") : label}
    >
      <InlineLoader
        variant="halo"
        size={20}
        className="agent-chat__working-loader"
      />
      <span
        key={label}
        className="agent-chat__working-text"
        aria-hidden="true"
        style={{ "--typing-cycle": `${cycleMs}ms` } as CSSProperties}
      >
        {characters.map((character, index) => (
          <span
            key={index}
            className="agent-chat__working-character"
            style={{ "--character-reveal": `${(index + 1) * characterIntervalMs / cycleMs * 100}%` } as CSSProperties}
          >{character}</span>
        ))}
      </span>
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
  const t = useTranslation();
  const label = awaiting.kind === "manual_node_run"
    ? t("Waiting for a draft node to be run")
    : awaiting.kind === "milestone_idle"
      ? t("This production milestone is complete")
      : t("Waiting for your guided choice");
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
  const t = useTranslation();
  const plan = card.command_plan;
  const canDecide = plan.confirmation_required && plan.status === "pending_confirmation";
  return (
    <article className={`agent-chat__command is-${plan.status}`}>
      <header>
        <strong>{t("Proposed canvas change")}</strong>
        <span>{plan.status.replaceAll("_", " ")}</span>
      </header>
      <p>{plan.target_summary || t("Review the proposed canvas changes.")}</p>
      <small>
        {plan.operations.length} canvas {plan.operations.length === 1 ? "change" : "changes"} will be applied.
      </small>
      {canDecide ? (
        <div className="agent-chat__command-actions">
          <button
            type="button"
            className="is-confirm"
            aria-label={t("Confirm command")}
            disabled={pending}
            onClick={() => void onAction(plan.plan_id, "confirm")}
          >
            {t("Confirm")}</button>
          <button
            type="button"
            className="is-reject"
            aria-label={t("Reject command")}
            disabled={pending}
            onClick={() => void onAction(plan.plan_id, "reject")}
          >
            {t("Reject")}</button>
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
  const t = useTranslation();
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
  const materializationUserAction = failureUserAction(materialization?.error?.actionable_failure);
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
  const canRecoverMaterialization = materialization?.status === "failed"
    && (materializationUserAction === "revise" || materializationUserAction === "redesign")
    && isOpen
    && Boolean(reviseAction?.enabled)
    && Boolean(onRevise);
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
      {!(compact && readOnly) ? <header>
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
      </header> : null}
      {readOnly ? (
        <HistoricalProposalOptions
          options={displayOptions}
          selectedOptionId={appliedOptionId}
        />
      ) : (
        <div className="agent-chat__options" aria-label={t("Creative direction options")}>
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
        <section className="agent-chat__proposal-references" aria-label={t("Accepted references")}>
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
              aria-label={t("Add proposal reference")}
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
          onRetry={onRetryMaterialization}
          onRecover={canRecoverMaterialization ? () => setRevising(true) : undefined}
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
      {revising && (canRevise || canRecoverMaterialization) && reviseAction ? (
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
            placeholder={t("Describe the change")}
            aria-label={t("Proposal revision")}
          />
          <button
            type="submit"
            aria-label={t("Submit proposal revision")}
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
  const visibleActions = actions.filter((action) => (
    action.state !== "superseded" && action.action !== "set_creative_authority"
  ));
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
