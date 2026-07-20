import { useMemo } from "react";
import type { DynamicMediaItem, UploadedAsset, WorkflowNode } from "../../../types";
import { activeWorkflowAssets } from "../assets/workflowAssetPreviewModel.ts";
import type { CanvasCandidateSummaryState, LocalRevisionCardState } from "../assets/useWorkflowAssetOperations.ts";
import { localRevisionPendingCandidatesForState, isRevisionCandidateNotable } from "../assets/localRevisionViewModel.ts";
import { buildCanvasEntityArea, isCanvasEntityAreaNode } from "../../../workflow/canvasEntityAreas.ts";
import { canvasTargetMentionOptions, type NodeMentionOption } from "../../../workflow/nodeMentions.ts";
import { getWorkflowNodeType } from "../canvas/workflowNodeModel.ts";
import { prioritizeNodeMentionOptions } from "../copilot/agentConversationPanelModel.ts";

export function useWorkflowPageRuntimeSummaries({
  workflowIsV2,
  v2NodeRuntimeStatusById,
  canvasRuntimeNodeStatusById,
  canvasNodes,
  selectedPlanNode,
  selectedNodeId,
  selectedDynamicMediaItems,
  selectedOutputAssets,
  localRevisionByKey,
  workflowId,
  canvasCandidateSummaryByNodeId,
  dynamicItemRunningById,
}: {
  workflowIsV2: boolean;
  v2NodeRuntimeStatusById: Record<string, string>;
  canvasRuntimeNodeStatusById: Record<string, string>;
  canvasNodes: WorkflowNode[];
  selectedPlanNode?: WorkflowNode | null;
  selectedNodeId: string;
  selectedDynamicMediaItems: DynamicMediaItem[];
  selectedOutputAssets: UploadedAsset[];
  localRevisionByKey: Record<string, LocalRevisionCardState>;
  workflowId: string;
  canvasCandidateSummaryByNodeId: Record<string, CanvasCandidateSummaryState>;
  dynamicItemRunningById: Record<string, boolean>;
}) {
  const effectiveNodeStatusById = workflowIsV2 ? v2NodeRuntimeStatusById : canvasRuntimeNodeStatusById;

  const conversationNodeMentionOptions = useMemo(
    () => prioritizeNodeMentionOptions(
      canvasTargetMentionOptions(canvasNodes, {
        selectedNode: selectedPlanNode,
        dynamicItems: selectedDynamicMediaItems,
        outputAssets: selectedOutputAssets,
      }),
      selectedNodeId,
    ),
    [canvasNodes, selectedNodeId, selectedPlanNode, selectedDynamicMediaItems, selectedOutputAssets],
  );

  const localRevisionSummaryByNodeId = useMemo(() => {
    const summary: Record<string, { candidateCount: number; warningCount: number; pendingVisibleCandidateCount: number }> = {};
    Object.values(localRevisionByKey).forEach((state) => {
      const [keyWorkflowId, nodeId] = state.key.split("::");
      if (!nodeId || (workflowId && keyWorkflowId && keyWorkflowId !== workflowId)) return;
      const candidates = localRevisionPendingCandidatesForState(state);
      if (!candidates.length) return;
      const current = summary[nodeId] ?? { candidateCount: 0, warningCount: 0, pendingVisibleCandidateCount: 0 };
      current.candidateCount += candidates.length;
      current.warningCount += candidates.filter(isRevisionCandidateNotable).length;
      current.pendingVisibleCandidateCount += candidates.length;
      summary[nodeId] = current;
    });
    return summary;
  }, [localRevisionByKey, workflowId]);

  const candidateSummaryByNodeId = useMemo(() => {
    const summary = { ...localRevisionSummaryByNodeId };
    Object.entries(canvasCandidateSummaryByNodeId).forEach(([nodeId, canvasSummary]) => {
      const localSummary = summary[nodeId] ?? { candidateCount: 0, warningCount: 0, pendingVisibleCandidateCount: 0 };
      summary[nodeId] = {
        candidateCount: canvasSummary.candidateCount ?? canvasSummary.pendingVisibleCandidateCount ?? localSummary.candidateCount,
        warningCount: canvasSummary.candidateWarningCount ?? localSummary.warningCount,
        pendingVisibleCandidateCount: canvasSummary.pendingVisibleCandidateCount ?? localSummary.pendingVisibleCandidateCount,
      };
    });
    return summary;
  }, [canvasCandidateSummaryByNodeId, localRevisionSummaryByNodeId]);

  const dynamicItemRunningByNodeId = useMemo(() => {
    if (!Object.values(dynamicItemRunningById).some(Boolean)) return {};
    const next: Record<string, Record<string, boolean | undefined>> = {};
    canvasNodes.forEach((node) => {
      if (!isCanvasEntityAreaNode(getWorkflowNodeType(node))) return;
      const area = buildCanvasEntityArea(node, { outputAssets: activeWorkflowAssets(node.output_assets ?? []) });
      if (!area) return;
      const runningForNode: Record<string, boolean | undefined> = {};
      area.items.forEach((item) => {
        if (dynamicItemRunningById[item.itemId]) runningForNode[item.itemId] = true;
        const videoKey = `${item.itemId}:video`;
        if (dynamicItemRunningById[videoKey]) runningForNode[videoKey] = true;
      });
      if (Object.keys(runningForNode).length) next[node.id] = runningForNode;
    });
    return next;
  }, [canvasNodes, dynamicItemRunningById]);

  return {
    effectiveNodeStatusById,
    conversationNodeMentionOptions: conversationNodeMentionOptions satisfies NodeMentionOption[],
    candidateSummaryByNodeId,
    dynamicItemRunningByNodeId,
  };
}
