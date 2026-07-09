import { useState } from "react";
import type { AgentConversation, AgentConversationSuggestedAction, WorkflowGraph } from "../../../types.ts";
import type { WorkflowV2 } from "../../../types-v2.ts";
import type { PromptGenerateContext } from "../../../components/PromptComposer.tsx";

export function useWorkflowCopilotController(options: {
  workflow?: WorkflowGraph | null;
  workflowV2?: WorkflowV2 | null;
  selectedNodeId?: string | null;
  selectedV2SlotId?: string | null;
  refreshWorkflowGraph?: (workflowId: string) => Promise<void>;
  refreshV2WorkflowGraph?: (workflowId: string) => Promise<void>;
  applyWorkflowGraph?: (workflow: WorkflowGraph) => Promise<void>;
  applyWorkflowV2?: (workflow: WorkflowV2) => Promise<void>;
} = {}) {
  const [activeConversation] = useState<AgentConversation | null>(null);
  const [conversations] = useState<AgentConversation[]>([]);
  async function askCopilot(prompt: string, context: PromptGenerateContext = { asset_references: [] }) {
    void prompt;
    void context;
    return null;
  }
  async function sendCopilotMessage(prompt: string, context: PromptGenerateContext = { asset_references: [] }) {
    return askCopilot(prompt, context);
  }
  async function sendAgentConversationMessage(prompt: string, context: PromptGenerateContext = { asset_references: [] }) {
    return askCopilot(prompt, context);
  }
  async function sendV2ChatTargetMessage(prompt: string, context: PromptGenerateContext = { asset_references: [] }) {
    return askCopilot(prompt, context);
  }
  async function applyConversationAction(action: AgentConversationSuggestedAction) {
    void action;
    return null;
  }
  async function rejectConversationAction(action: AgentConversationSuggestedAction) {
    void action;
    return null;
  }
  void options;
  return { askCopilot, sendCopilotMessage, sendAgentConversationMessage, sendV2ChatTargetMessage, applyConversationAction, rejectConversationAction, activeConversation, conversations };
}
