import { useMemo } from "react";
import type { AgentConversationEvent, FrontDeskMessage, NodeRunResult, WorkflowGraph } from "../../../types";
import { findNodeRunForWorkflowNode } from "../../../workflow/runtimeResults.ts";
import { isUserVisibleWorkflowNode, visibleWorkflowNodes } from "../../../workflow/visibility.ts";
import {
  frontDeskConversationId,
  frontDeskMessagesAsConversationEvents,
} from "../copilot/agentConversationPanelModel.ts";
import { isNodeRunForCanvasInstance } from "../canvas/workflowCanvasModel.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";

export function useWorkflowPageSelectionState({
  workflow,
  messages,
  canvasNodes,
  nodeRuns,
  nodeRunByType,
  selectedNodeId,
  selectedNodeRun,
  activeConversationId,
  conversationEventsById,
}: {
  workflow?: WorkflowGraph | null;
  messages: FrontDeskMessage[];
  canvasNodes: WorkflowGraph["nodes"];
  nodeRuns: NodeRunResult[];
  nodeRunByType: Map<string, NodeRunResult>;
  selectedNodeId: string;
  selectedNodeRun: NodeRunResult | null;
  activeConversationId: string | null;
  conversationEventsById: Record<string, AgentConversationEvent[]>;
}) {
  const visibleCanvasNodes = useMemo(() => visibleWorkflowNodes(canvasNodes), [canvasNodes]);
  const visibleNodeRuns = useMemo(
    () => nodeRuns.filter((run) => isUserVisibleWorkflowNode({ id: run.node_id || run.node_type, node_type: run.node_type })),
    [nodeRuns],
  );

  const selectedPlanNode = visibleCanvasNodes.find((node) => node.id === selectedNodeId);
  const activeConversationEvents = activeConversationId ? conversationEventsById[activeConversationId] ?? [] : [];
  const workflowFrontDeskEvents = workflow?.workflow_id
    ? frontDeskMessagesAsConversationEvents(messages, {
        conversationId: activeConversationId ?? frontDeskConversationId(workflow.workflow_id),
        workflowId: workflow.workflow_id,
        bridge: true,
      })
    : [];
  const copilotPanelEvents = workflow?.workflow_id
    ? activeConversationEvents.length ? activeConversationEvents : workflowFrontDeskEvents
    : frontDeskMessagesAsConversationEvents(messages);
  const selectedRunType = selectedPlanNode ? getWorkflowNodeType(selectedPlanNode) : selectedNodeId;
  const selectedRunFromList = selectedPlanNode ? findNodeRunForWorkflowNode(selectedPlanNode, nodeRunByType, visibleCanvasNodes) : undefined;
  const selectedRun = selectedPlanNode && isNodeRunForCanvasInstance(selectedNodeRun, selectedPlanNode, visibleCanvasNodes) ? selectedNodeRun : selectedRunFromList;

  return {
    visibleCanvasNodes,
    visibleNodeRuns,
    selectedPlanNode,
    copilotPanelEvents,
    selectedRunType,
    selectedRun,
  };
}
