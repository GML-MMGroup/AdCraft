import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type {
  AgentConversation,
  AgentConversationEvent,
  AssetLibraryReference,
  CanvasTargetReference,
  ChatNodeReference,
} from "../../../types";

export type ConversationActionBusyState = Record<string, "apply" | "reject" | undefined>;

export type WorkflowConversationController = {
  state: {
    agentConversations: AgentConversation[];
    activeConversationId: string | null;
    conversationEventsById: Record<string, AgentConversationEvent[]>;
    conversationMentionReferences: AssetLibraryReference[];
    conversationNodeReferences: ChatNodeReference[];
    conversationTargetReferences: CanvasTargetReference[];
    conversationLoading: boolean;
    conversationSending: boolean;
    conversationError: string | null;
    actionBusyById: ConversationActionBusyState;
  };
  actions: {
    setAgentConversations: Dispatch<SetStateAction<AgentConversation[]>>;
    setActiveConversationId: Dispatch<SetStateAction<string | null>>;
    setConversationEventsById: Dispatch<SetStateAction<Record<string, AgentConversationEvent[]>>>;
    setConversationMentionReferences: Dispatch<SetStateAction<AssetLibraryReference[]>>;
    setConversationNodeReferences: Dispatch<SetStateAction<ChatNodeReference[]>>;
    setConversationTargetReferences: Dispatch<SetStateAction<CanvasTargetReference[]>>;
    setConversationLoading: Dispatch<SetStateAction<boolean>>;
    setConversationSending: Dispatch<SetStateAction<boolean>>;
    setConversationError: Dispatch<SetStateAction<string | null>>;
    setActionBusyById: Dispatch<SetStateAction<ConversationActionBusyState>>;
  };
};

export function useWorkflowConversationController(): WorkflowConversationController {
  const [agentConversations, setAgentConversations] = useState<AgentConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [conversationEventsById, setConversationEventsById] = useState<Record<string, AgentConversationEvent[]>>({});
  const [conversationMentionReferences, setConversationMentionReferences] = useState<AssetLibraryReference[]>([]);
  const [conversationNodeReferences, setConversationNodeReferences] = useState<ChatNodeReference[]>([]);
  const [conversationTargetReferences, setConversationTargetReferences] = useState<CanvasTargetReference[]>([]);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationSending, setConversationSending] = useState(false);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [actionBusyById, setActionBusyById] = useState<ConversationActionBusyState>({});

  return useMemo(
    () => ({
      state: {
        agentConversations,
        activeConversationId,
        conversationEventsById,
        conversationMentionReferences,
        conversationNodeReferences,
        conversationTargetReferences,
        conversationLoading,
        conversationSending,
        conversationError,
        actionBusyById,
      },
      actions: {
        setAgentConversations,
        setActiveConversationId,
        setConversationEventsById,
        setConversationMentionReferences,
        setConversationNodeReferences,
        setConversationTargetReferences,
        setConversationLoading,
        setConversationSending,
        setConversationError,
        setActionBusyById,
      },
    }),
    [
      actionBusyById,
      activeConversationId,
      agentConversations,
      conversationError,
      conversationEventsById,
      conversationLoading,
      conversationMentionReferences,
      conversationNodeReferences,
      conversationSending,
      conversationTargetReferences,
    ],
  );
}
