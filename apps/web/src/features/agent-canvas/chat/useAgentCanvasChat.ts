import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { v2Api } from "../../../api/v2Client.ts";
import { createOperationKey } from "../../../api/operationKey.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasPositionV2,
  CanvasRuntimeEventV2,
  ChatMessageV2,
  ChatTimelineItemV2,
} from "../../../types-v2.ts";
import { projectChatEvents } from "./projectChatEvents.ts";

type SubmitDraft = {
  text: string;
  mentionedNodeIds: string[];
  mentionedImageAssetIds: string[];
};

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
    return `activity:${item.activity_id}`;
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
  proposalPosition,
}: {
  workflow: AgentCanvasWorkflowV2 | null;
  chatRevision: number;
  chatEvents: CanvasRuntimeEventV2[];
  proposalPosition: CanvasPositionV2;
}) {
  const [persistedItems, setPersistedItems] = useState<ChatTimelineItemV2[]>([]);
  const [optimisticItems, setOptimisticItems] = useState<ChatTimelineItemV2[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [actingProposalId, setActingProposalId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedDraft, setFailedDraft] = useState<SubmitDraft | null>(null);
  const refreshGenerationRef = useRef(0);
  const workflowId = workflow?.workflow_id ?? null;

  const refresh = useCallback(async () => {
    if (!workflowId) return;
    const generation = refreshGenerationRef.current + 1;
    refreshGenerationRef.current = generation;
    setLoading(true);
    try {
      const items: ChatTimelineItemV2[] = [];
      let cursor = 0;
      for (;;) {
        const timeline = await v2Api.agentCanvasChatTimeline(workflowId, cursor, 200);
        items.push(...timeline.items);
        if (timeline.items.length < 200 || timeline.next_after_seq <= cursor) break;
        cursor = timeline.next_after_seq;
      }
      if (generation !== refreshGenerationRef.current) return;
      setPersistedItems(items);
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
  }, [workflowId]);

  useEffect(() => {
    setPersistedItems([]);
    setOptimisticItems([]);
    setFailedDraft(null);
    setActingProposalId(null);
    setError(null);
  }, [workflowId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 80);
    return () => window.clearTimeout(timer);
  }, [chatRevision, refresh]);

  const submit = useCallback(async (draft: SubmitDraft) => {
    if (!workflowId || !draft.text.trim()) return false;
    const optimisticId = createOperationKey("optimistic");
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
      const accepted = await v2Api.submitAgentCanvasChatMessage(workflowId, {
        text: draft.text.trim(),
        mentioned_node_ids: draft.mentionedNodeIds,
        mentioned_image_asset_ids: draft.mentionedImageAssetIds,
        video_skill_run_id: null,
        auto_continue: false,
      }, createOperationKey("chat"));
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
      setError(null);
      return true;
    } catch (submitError) {
      setOptimisticItems((current) => current.filter((item) => (
        item.item_type !== "message" || item.message_id !== optimisticId
      )));
      setFailedDraft(draft);
      setError(submitError instanceof Error ? submitError.message : "Message could not be sent.");
      return false;
    } finally {
      setSending(false);
    }
  }, [workflowId]);

  const selectProposal = useCallback(async (
    proposalId: string,
    optionId: string,
    nextAction: "generate_now" | "continue_planning",
  ) => {
    if (!workflowId || actingProposalId) return;
    setActingProposalId(proposalId);
    setError(null);
    try {
      await v2Api.actOnAgentCanvasProposal(workflowId, proposalId, {
        action: "select",
        option_id: optionId,
        next_action: nextAction,
        position: proposalPosition,
      }, createOperationKey("proposal-select"));
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "The proposal could not be selected.");
    } finally {
      setActingProposalId(null);
    }
  }, [actingProposalId, proposalPosition, workflowId]);

  const reviseProposal = useCallback(async (proposalId: string, instruction: string) => {
    if (!workflowId || !instruction.trim() || actingProposalId) return;
    setActingProposalId(proposalId);
    setError(null);
    try {
      await v2Api.actOnAgentCanvasProposal(workflowId, proposalId, {
        action: "revise",
        instruction: instruction.trim(),
      }, createOperationKey("proposal-revise"));
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "The proposal could not be revised.");
    } finally {
      setActingProposalId(null);
    }
  }, [actingProposalId, workflowId]);

  const skipProposal = useCallback(async (proposalId: string) => {
    if (!workflowId || actingProposalId) return;
    setActingProposalId(proposalId);
    setError(null);
    try {
      await v2Api.actOnAgentCanvasProposal(workflowId, proposalId, {
        action: "skip",
      }, createOperationKey("proposal-skip"));
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "The proposal could not be skipped.");
    } finally {
      setActingProposalId(null);
    }
  }, [actingProposalId, workflowId]);

  const projectedItems = useMemo(() => projectChatEvents(chatEvents), [chatEvents]);
  const items = useMemo(
    () => mergeTimelineItems(persistedItems, projectedItems, optimisticItems),
    [optimisticItems, persistedItems, projectedItems],
  );

  return {
    state: {
      items,
      loading,
      sending,
      actingProposalId,
      error,
      failedDraft,
    },
    actions: {
      refresh,
      submit,
      selectProposal,
      reviseProposal,
      skipProposal,
      clearFailedDraft: () => setFailedDraft(null),
    },
  };
}
