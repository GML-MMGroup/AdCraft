import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  AgentCanvasContinuationV2,
  AgentActionReceiptV2,
  CanvasRuntimeEventV2,
  ChatMessageV2,
  ChatTimelineItemV2,
  GuidanceSessionActionV2,
  GuidedSessionStateV2,
  ProposalActionDescriptorV2,
  ProposedDraftReferenceV2,
} from "../../../types-v2.ts";
import { projectChatEvents } from "./projectChatEvents.ts";

type SubmitDraft = {
  text: string;
  mentionedNodeIds: string[];
  mentionedImageAssetIds: string[];
  idempotencyKey?: string;
};

const PROPOSAL_ACTION_ERROR_CODES = new Set([
  "proposal_reference_unavailable",
  "proposal_snapshot_unavailable",
  "proposal_action_stale",
  "proposal_action_invalid",
  "draft_reference_not_allowed",
  "idempotency_conflict",
]);

const GUIDANCE_CONFLICT_ERROR_CODES = new Set([
  "guidance_revision_conflict",
  "proposal_action_stale",
]);

function agentTurnErrorMessage(code: string, fallback: string | null): string {
  if (code === "agent_runtime_unavailable") {
    return "The agent runtime is temporarily unavailable. Your input is preserved; try again shortly.";
  }
  if (code === "agent_deadline_exceeded") {
    return "The agent took too long to respond. Your input is preserved; retry when ready.";
  }
  if (code === "guidance_decision_invalid") {
    return "The agent could not produce a valid next guidance step. Try again.";
  }
  if (code === "guidance_completion_invalid") {
    return "The guidance session is not ready to finish yet.";
  }
  if (code === "specialist_context_invalid") {
    return "The specialist could not use the current project context. Refresh and try again.";
  }
  return fallback ?? "The agent could not complete this request.";
}

function handleProposalActionError(
  proposalId: string,
  error: unknown,
  setIssues: Dispatch<SetStateAction<Record<string, string>>>,
) {
  if (
    !isV2ApiError(error)
    || !error.code
    || !PROPOSAL_ACTION_ERROR_CODES.has(error.code)
  ) return false;
  setIssues((current) => ({
    ...current,
    [proposalId]: error.message,
  }));
  return true;
}

function mergeTimelineItems(
  persisted: ChatTimelineItemV2[],
  projected: ChatTimelineItemV2[],
  optimistic: ChatTimelineItemV2[],
) {
  const keys = new Map<string, ChatTimelineItemV2>();
  const keyFor = (item: ChatTimelineItemV2) => {
    if (item.item_type === "message") return `message:${item.message_id}`;
    if (item.item_type === "artifact") return `artifact:${item.artifact_id}`;
    if (item.item_type === "proposal") return `proposal:${item.proposal.proposal_id}`;
    if (item.item_type === "expert_activity") return `activity:${item.activity_id}`;
    if (item.item_type === "command_plan") return `command:${item.command_plan.plan_id}`;
    if (item.item_type === "action_receipt") return `receipt:${item.action_receipt.receipt_id}`;
    if (item.item_type === "proposal_pointer") return `proposal:${item.proposal_id}`;
    const exhaustiveItem: never = item;
    return exhaustiveItem;
  };
  [...persisted, ...projected, ...optimistic].forEach((item) => {
    keys.set(keyFor(item), item);
  });
  return [...keys.values()].sort((left, right) => left.sequence - right.sequence);
}

export function useAgentCanvasChat({
  workflow,
  chatRevision,
  chatEvents,
  onActionReceipt,
  onWorkflowRefresh,
}: {
  workflow: AgentCanvasWorkflowV2 | null;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  onActionReceipt?: (receipt: AgentActionReceiptV2) => void;
  onWorkflowRefresh?: () => Promise<void> | void;
}) {
  const [persistedItems, setPersistedItems] = useState<ChatTimelineItemV2[]>([]);
  const [optimisticItems, setOptimisticItems] = useState<ChatTimelineItemV2[]>([]);
  const [guidanceSession, setGuidanceSession] = useState<GuidedSessionStateV2 | null>(null);
  const [currentSessionActions, setCurrentSessionActions] = useState<GuidanceSessionActionV2[]>([]);
  const [continuationsById, setContinuationsById] = useState<Record<string, AgentCanvasContinuationV2>>({});
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [actingProposalId, setActingProposalId] = useState<string | null>(null);
  const [actingCommandPlanId, setActingCommandPlanId] = useState<string | null>(null);
  const [actingGuidedActionId, setActingGuidedActionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [proposalIssues, setProposalIssues] = useState<Record<string, string>>({});
  const [failedDraft, setFailedDraft] = useState<SubmitDraft | null>(null);
  const refreshGenerationRef = useRef(0);
  const workflowGenerationRef = useRef(0);
  const pendingActionTurnIdsRef = useRef(new Set<string>());
  const pendingCommandPlanIdsRef = useRef(new Set<string>());
  const expectedReceiptIdsRef = useRef(new Set<string>());
  const deliveredReceiptIdsRef = useRef(new Set<string>());
  const submittedDraftsByTurnIdRef = useRef(new Map<string, SubmitDraft>());
  const workflowId = workflow?.workflow_id ?? null;

  const upsertContinuation = useCallback((continuation: AgentCanvasContinuationV2) => {
    setContinuationsById((current) => ({
      ...current,
      [continuation.continuation_id]: continuation,
    }));
  }, []);

  const refreshTurn = useCallback(async (turnId: string) => {
    if (!workflowId) return;
    try {
      const turn = await agentCanvasApi.agentCanvasChatTurn(workflowId, turnId);
      if (turn.continuation) upsertContinuation(turn.continuation);
      const terminalErrorCode = turn.continuation?.last_error_code ?? turn.error_code;
      const terminalErrorMessage = turn.continuation?.last_error_message ?? turn.error_message;
      const continuationFailed = turn.continuation?.delivery_status === "failed";
      if ((continuationFailed || turn.status === "failed") && terminalErrorCode) {
        const failedMessage = submittedDraftsByTurnIdRef.current.get(turnId);
        if (failedMessage) {
          // A confirmed backend failure must use a new idempotency key when retried.
          setFailedDraft({ ...failedMessage, idempotencyKey: undefined });
        }
        setError(agentTurnErrorMessage(terminalErrorCode, terminalErrorMessage));
      }
    } catch {
      // A later timeline refresh remains authoritative after a transient turn lookup failure.
    }
  }, [upsertContinuation, workflowId]);

  const trackAcceptedTurn = useCallback((
    accepted: { turn_id: string },
    submittedDraft?: SubmitDraft,
  ) => {
    if (submittedDraft) submittedDraftsByTurnIdRef.current.set(accepted.turn_id, submittedDraft);
    void refreshTurn(accepted.turn_id);
  }, [refreshTurn]);

  const refresh = useCallback(async () => {
    if (!workflowId) return;
    const generation = refreshGenerationRef.current + 1;
    refreshGenerationRef.current = generation;
    setLoading(true);
    try {
      const items: ChatTimelineItemV2[] = [];
      let nextGuidanceSession: GuidedSessionStateV2 | null = null;
      let nextCurrentSessionActions: GuidanceSessionActionV2[] = [];
      const nextContinuations = new Map<string, AgentCanvasContinuationV2>();
      let cursor = 0;
      for (;;) {
        const timeline = await agentCanvasApi.agentCanvasChatTimeline(workflowId, cursor, 200);
        nextGuidanceSession = timeline.guidanceSession;
        nextCurrentSessionActions = timeline.current_session_actions ?? [];
        (timeline.continuations ?? []).forEach((continuation) => {
          nextContinuations.set(continuation.continuation_id, continuation);
        });
        const hydrated = await Promise.all(timeline.items.map(async (item): Promise<ChatTimelineItemV2> => {
          if (item.item_type !== "proposal_pointer") return item;
          const proposal = await agentCanvasApi.agentCanvasProposal(workflowId, item.proposal_id);
          return {
            item_type: "proposal",
            proposal,
            sequence: item.sequence,
            created_at: item.created_at,
          };
        }));
        items.push(...hydrated);
        if (timeline.items.length < 200 || timeline.next_cursor <= cursor) break;
        cursor = timeline.next_cursor;
      }
      if (generation !== refreshGenerationRef.current) return;
      setGuidanceSession(nextGuidanceSession);
      setCurrentSessionActions(nextCurrentSessionActions);
      setContinuationsById(Object.fromEntries(nextContinuations));
      setPersistedItems(items);
      items.forEach((item) => {
        if (item.item_type !== "action_receipt") return;
        const receipt = item.action_receipt;
        const expectedByEvent = expectedReceiptIdsRef.current.has(receipt.receipt_id);
        const expectedByTurn = Boolean(
          receipt.action_id
          && pendingActionTurnIdsRef.current.has(receipt.action_id),
        );
        const expectedByPlan = Boolean(
          receipt.plan_id
          && pendingCommandPlanIdsRef.current.has(receipt.plan_id),
        );
        if (
          (!expectedByEvent && !expectedByTurn && !expectedByPlan)
          || deliveredReceiptIdsRef.current.has(receipt.receipt_id)
        ) return;
        if (receipt.action_id) pendingActionTurnIdsRef.current.delete(receipt.action_id);
        if (receipt.plan_id) pendingCommandPlanIdsRef.current.delete(receipt.plan_id);
        expectedReceiptIdsRef.current.delete(receipt.receipt_id);
        deliveredReceiptIdsRef.current.add(receipt.receipt_id);
        if (receipt.status === "applied" || receipt.status === "applied_with_run_error") {
          onActionReceipt?.(receipt);
        } else if (receipt.status === "not_applied") {
          setNotice(receipt.summary || "No canvas change was needed.");
        }
      });
      const persistedMessageIds = new Set(
        items
          .filter((item): item is ChatMessageV2 => item.item_type === "message")
          .map((item) => item.message_id),
      );
      setOptimisticItems((current) => current.filter((item) => (
        item.item_type !== "message"
        || !persistedMessageIds.has(item.message_id)
      )));
      setError(null);
    } catch (refreshError) {
      if (generation !== refreshGenerationRef.current) return;
      setError(refreshError instanceof Error ? refreshError.message : "Conversation could not be loaded.");
    } finally {
      if (generation === refreshGenerationRef.current) setLoading(false);
    }
  }, [onActionReceipt, workflowId]);

  const handleStructuredActionError = useCallback((actionError: unknown): boolean => {
    if (!isV2ApiError(actionError)) return false;
    if (
      actionError.code === "guided_action_stale"
      || actionError.code === "guided_action_superseded"
    ) {
      setNotice("This action is no longer current. The conversation was refreshed.");
      void refresh();
      return true;
    }
    if (actionError.code === "guided_action_no_effect") {
      setNotice("No canvas change was needed.");
      void refresh();
      return true;
    }
    if (
      actionError.code === "guidance_revision_conflict"
      || actionError.code === "proposal_action_stale"
    ) {
      setNotice("The guidance session changed. Review the latest guidance state before trying again.");
      void refresh();
      void onWorkflowRefresh?.();
      return true;
    }
    if (actionError.code === "guidance_decision_invalid") {
      setError("The agent could not produce a valid next guidance step. Try again.");
      return true;
    }
    if (actionError.code === "guidance_completion_invalid") {
      setError("The guidance session is not ready to finish yet.");
      return true;
    }
    if (actionError.code === "specialist_context_invalid") {
      setError("The specialist could not use the current project context. Refresh and try again.");
      return true;
    }
    if (actionError.code === "agent_deadline_exceeded") {
      setError("The agent took too long to respond. Your input is preserved; retry when ready.");
      return true;
    }
    if (actionError.code === "agent_runtime_unavailable") {
      setError("The agent runtime is temporarily unavailable. Your input is preserved; try again shortly.");
      return true;
    }
    return false;
  }, [onWorkflowRefresh, refresh]);

  const handleProposalFailure = useCallback(async (
    proposalId: string,
    actionError: unknown,
    fallbackMessage: string,
  ) => {
    if (
      isV2ApiError(actionError)
      && actionError.code
      && GUIDANCE_CONFLICT_ERROR_CODES.has(actionError.code)
    ) {
      setProposalIssues((current) => ({
        ...current,
        [proposalId]: actionError.message,
      }));
      setNotice("The guidance session changed. Review the latest guidance state before trying again.");
      await refresh();
      await onWorkflowRefresh?.();
      return;
    }
    if (handleProposalActionError(proposalId, actionError, setProposalIssues)) return;
    if (!handleStructuredActionError(actionError)) {
      setError(actionError instanceof Error ? actionError.message : fallbackMessage);
    }
  }, [handleStructuredActionError, onWorkflowRefresh, refresh]);

  useEffect(() => {
    refreshGenerationRef.current += 1;
    workflowGenerationRef.current += 1;
    setPersistedItems([]);
    setOptimisticItems([]);
    setGuidanceSession(null);
    setCurrentSessionActions([]);
    setContinuationsById({});
    setLoading(false);
    setSending(false);
    setFailedDraft(null);
    setActingProposalId(null);
    setActingCommandPlanId(null);
    setActingGuidedActionId(null);
    pendingActionTurnIdsRef.current.clear();
    pendingCommandPlanIdsRef.current.clear();
    expectedReceiptIdsRef.current.clear();
    deliveredReceiptIdsRef.current.clear();
    submittedDraftsByTurnIdRef.current.clear();
    setError(null);
    setNotice(null);
    setProposalIssues({});
  }, [workflowId]);

  useEffect(() => {
    chatEvents.forEach((event) => {
      if (event.event_type === "action_receipt_created") {
        const receiptId = event.payload?.receipt_id;
        if (typeof receiptId === "string" && !deliveredReceiptIdsRef.current.has(receiptId)) {
          expectedReceiptIdsRef.current.add(receiptId);
        }
      }
      if (event.event_type.startsWith("continuation_") && event.turn_id) {
        void refreshTurn(event.turn_id);
      }
    });
  }, [chatEvents, refreshTurn]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 80);
    return () => window.clearTimeout(timer);
  }, [chatRevision, refresh]);

  const submit = useCallback(async (draft: SubmitDraft) => {
    if (!workflowId || !draft.text.trim()) return false;
    const workflowGeneration = workflowGenerationRef.current;
    const optimisticId = createOperationKey("optimistic");
    const idempotencyKey = draft.idempotencyKey ?? createOperationKey("chat");
    setOptimisticItems((current) => [...current, {
      item_type: "message",
      message_id: optimisticId,
      conversation_id: "pending",
      speaker: "user",
      text: draft.text.trim(),
      linked_node_ids: draft.mentionedNodeIds,
      script_node_id: null,
      proposal_id: null,
      sequence: Date.now(),
      created_at: new Date().toISOString(),
    }]);
    setSending(true);
    setFailedDraft(null);
    try {
      const accepted = await agentCanvasApi.submitAgentCanvasChatMessage(workflowId, {
        text: draft.text.trim(),
        mentioned_node_ids: draft.mentionedNodeIds,
        mentioned_image_asset_ids: draft.mentionedImageAssetIds,
        video_skill_run_id: null,
      }, idempotencyKey);
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      if (accepted.message_id) {
        setOptimisticItems((current) => current.map((item) => (
          item.item_type === "message" && item.message_id === optimisticId
            ? {
                ...item,
                message_id: accepted.message_id!,
                conversation_id: accepted.conversation_id,
              }
          : item
        )));
      }
      trackAcceptedTurn(accepted, { ...draft, idempotencyKey });
      setError(null);
      return true;
    } catch (submitError) {
      if (workflowGeneration !== workflowGenerationRef.current) return false;
      setOptimisticItems((current) => current.filter((item) => (
        item.item_type !== "message" || item.message_id !== optimisticId
      )));
      setFailedDraft({ ...draft, idempotencyKey });
      setError(submitError instanceof Error ? submitError.message : "Message could not be sent.");
      return false;
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setSending(false);
      }
    }
  }, [trackAcceptedTurn, workflowId]);

  const selectProposal = useCallback(async (
    proposalId: string,
    actionDescriptor: ProposalActionDescriptorV2,
    optionId: string,
    acceptedReferences: ProposedDraftReferenceV2[],
  ) => {
    if (!workflowId || actingProposalId || actionDescriptor.action !== "select_option") return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    setProposalIssues((current) => {
      const next = { ...current };
      delete next[proposalId];
      return next;
    });
    try {
      const request = {
        action_id: actionDescriptor.action_id,
        expected_session_revision: actionDescriptor.expected_session_revision,
        action: "select_option",
        option_id: optionId,
        accepted_references: acceptedReferences,
      } as const;
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(
        workflowId,
        proposalId,
        request,
        createOperationKey("proposal-select-option"),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        await handleProposalFailure(proposalId, actionError, "The proposal could not be selected.");
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actingProposalId, handleProposalFailure, refresh, trackAcceptedTurn, workflowId]);

  const reviseProposal = useCallback(async (
    proposalId: string,
    actionDescriptor: ProposalActionDescriptorV2,
    instruction: string,
  ) => {
    if (
      !workflowId
      || !instruction.trim()
      || actingProposalId
      || actionDescriptor.action !== "revise_options"
    ) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    setProposalIssues((current) => {
      const next = { ...current };
      delete next[proposalId];
      return next;
    });
    try {
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(workflowId, proposalId, {
        action_id: actionDescriptor.action_id,
        expected_session_revision: actionDescriptor.expected_session_revision,
        action: "revise_options",
        instruction: instruction.trim(),
      }, createOperationKey("proposal-revise-options"));
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        await handleProposalFailure(proposalId, actionError, "The proposal could not be revised.");
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actingProposalId, handleProposalFailure, refresh, trackAcceptedTurn, workflowId]);

  const applyProposalAction = useCallback(async (
    proposalId: string,
    actionDescriptor: ProposalActionDescriptorV2,
  ) => {
    if (
      !workflowId
      || actingProposalId
      || !["defer_topic", "exclude_element", "delegate_choice"].includes(actionDescriptor.action)
    ) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingProposalId(proposalId);
    setError(null);
    setProposalIssues((current) => {
      const next = { ...current };
      delete next[proposalId];
      return next;
    });
    try {
      const accepted = await agentCanvasApi.actOnAgentCanvasProposal(
        workflowId,
        proposalId,
        {
          action_id: actionDescriptor.action_id,
          expected_session_revision: actionDescriptor.expected_session_revision,
          action: actionDescriptor.action as "defer_topic" | "exclude_element" | "delegate_choice",
        },
        createOperationKey(`proposal-${actionDescriptor.action.replaceAll("_", "-")}`),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        await handleProposalFailure(proposalId, actionError, "The proposal action could not be applied.");
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingProposalId(null);
      }
    }
  }, [actingProposalId, handleProposalFailure, refresh, trackAcceptedTurn, workflowId]);

  const actOnCommandPlan = useCallback(async (
    planId: string,
    action: "confirm" | "reject",
  ) => {
    if (!workflowId || actingCommandPlanId) return;
    const workflowGeneration = workflowGenerationRef.current;
    pendingCommandPlanIdsRef.current.add(planId);
    setActingCommandPlanId(planId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.actOnAgentCanvasCommandPlan(
        workflowId,
        planId,
        { action },
        createOperationKey(`command-${action}`),
      );
      pendingActionTurnIdsRef.current.add(accepted.turn_id);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      pendingCommandPlanIdsRef.current.delete(planId);
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(actionError instanceof Error
            ? actionError.message
            : `The command could not be ${action === "confirm" ? "confirmed" : "rejected"}.`);
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingCommandPlanId(null);
      }
    }
  }, [actingCommandPlanId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const applyGuidedAction = useCallback(async (actionId: string) => {
    if (!workflowId || actingGuidedActionId) return;
    const workflowGeneration = workflowGenerationRef.current;
    setActingGuidedActionId(actionId);
    setError(null);
    try {
      const accepted = await agentCanvasApi.applyAgentCanvasGuidedAction(
        workflowId,
        actionId,
        { confirmed: true },
        createOperationKey("guided-action"),
      );
      pendingActionTurnIdsRef.current.add(actionId);
      trackAcceptedTurn(accepted);
      void refresh();
    } catch (actionError) {
      if (workflowGeneration === workflowGenerationRef.current) {
        if (!handleStructuredActionError(actionError)) {
          setError(actionError instanceof Error
            ? actionError.message
            : "The guided action could not be applied.");
        }
      }
    } finally {
      if (workflowGeneration === workflowGenerationRef.current) {
        setActingGuidedActionId(null);
      }
    }
  }, [actingGuidedActionId, handleStructuredActionError, refresh, trackAcceptedTurn, workflowId]);

  const projectedItems = useMemo(() => projectChatEvents(chatEvents), [chatEvents]);
  const items = useMemo(
    () => mergeTimelineItems(persistedItems, projectedItems, optimisticItems),
    [optimisticItems, persistedItems, projectedItems],
  );

  return {
    state: {
      items,
      guidanceSession,
      currentSessionActions,
      continuations: Object.values(continuationsById),
      loading,
      sending,
      actingProposalId,
      actingCommandPlanId,
      actingGuidedActionId,
      error,
      notice,
      proposalIssues,
      failedDraft,
    },
    actions: {
      refresh,
      submit,
      selectProposal,
      reviseProposal,
      applyProposalAction,
      actOnCommandPlan,
      applyGuidedAction,
      clearFailedDraft: () => setFailedDraft(null),
      clearNotice: () => setNotice(null),
    },
  };
}
