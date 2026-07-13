import { useMemo } from "react";
import type { AssetVersionV2, WorkflowRuntimeV2 } from "../../../types-v2.ts";
import { executionRunningEdgeIds, nodeStatusWithExecution } from "../../../workflow/executionRuntime.ts";
import { isUserVisibleWorkflowNode, visibleWorkflowEdges } from "../../../workflow/visibility.ts";
import { mergeV2AssetVersions } from "../../../workflow-v2/assets.ts";
import type { CanvasEdge, CanvasNode, WorkflowNodeData } from "../types.ts";

type CandidateSummary = {
  candidateCount?: number;
  warningCount?: number;
  pendingVisibleCandidateCount?: number;
};

type WorkflowDisplayNodeCallbacks = Pick<
  WorkflowNodeData,
  | "onOpenMedia"
  | "onSelectDynamicItem"
  | "onOpenScreenplay"
  | "onOpenV2SlotEditor"
  | "onOpenV2StoryboardPrompt"
  | "onChangeV2SlotPrompt"
  | "onChangeV2SlotNegativePrompt"
  | "onUploadV2SlotReference"
  | "onSelectV2SlotLibraryReference"
  | "onRemoveV2SlotReference"
  | "onOpenV2SlotAssetLibraryReplace"
  | "onOpenV2SlotAssetLibrarySave"
  | "onSaveV2ItemPrompt"
  | "onSubmitV2SlotPrompt"
  | "onSelectV2SlotVersion"
  | "onDiscardV2SlotWorkingVersion"
  | "onLoadV2SlotVersions"
>;

export type WorkflowDisplayNodeInput = {
  flowNodes: CanvasNode[];
  flowEdges: CanvasEdge[];
  selectedEdgeId?: string | null;
  effectiveNodeStatusById: Record<string, string>;
  candidateSummaryByNodeId: Record<string, CandidateSummary | undefined>;
  activeProjectId?: string | null;
  workflowId?: string | null;
  dynamicItemRunningByNodeId: Record<string, WorkflowNodeData["runningDynamicItemById"]>;
  v2AssetVersions: AssetVersionV2[];
  slotVersionAssets: AssetVersionV2[];
  v2Runtime?: WorkflowRuntimeV2;
  v2FallbackRuntime?: WorkflowRuntimeV2;
  v2SlotRuntimeStatusById: Record<string, string>;
  activeV2SlotId?: string | null;
  activeV2StoryboardItemId?: string | null;
  v2SlotDraftsById: NonNullable<WorkflowNodeData["v2SlotDraftsById"]>;
  v2ReferenceAssetsBySlotId: NonNullable<WorkflowNodeData["v2ReferenceAssetsBySlotId"]>;
  v2LibraryReferenceOptions: NonNullable<WorkflowNodeData["v2LibraryReferenceOptions"]>;
  canvasRuntimeActiveEdgeIds: string[];
  runningNodeIds: string[];
  v2ActiveEdgeSourceNodeIds: string[];
  isV2: boolean;
  callbacks: WorkflowDisplayNodeCallbacks;
};

export function useWorkflowDisplayNodes({
  flowNodes,
  flowEdges,
  selectedEdgeId,
  effectiveNodeStatusById,
  candidateSummaryByNodeId,
  activeProjectId,
  workflowId,
  dynamicItemRunningByNodeId,
  v2AssetVersions,
  slotVersionAssets,
  v2Runtime,
  v2FallbackRuntime,
  v2SlotRuntimeStatusById,
  activeV2SlotId,
  activeV2StoryboardItemId,
  v2SlotDraftsById,
  v2ReferenceAssetsBySlotId,
  v2LibraryReferenceOptions,
  canvasRuntimeActiveEdgeIds,
  runningNodeIds,
  v2ActiveEdgeSourceNodeIds,
  isV2,
  callbacks,
}: WorkflowDisplayNodeInput) {
  const displayNodes = useMemo(
    () =>
      flowNodes
        .filter((node) => isUserVisibleWorkflowNode({ id: node.id, node_type: node.data.kind }))
        .map((node) => {
          const summary = candidateSummaryByNodeId[node.id];
          return {
            ...node,
            data: {
              ...node.data,
              status: nodeStatusWithExecution(node.id, node.data.status, effectiveNodeStatusById),
              candidateCount: summary?.candidateCount ?? 0,
              candidateWarningCount: summary?.warningCount ?? 0,
              pendingVisibleCandidateCount: summary?.pendingVisibleCandidateCount ?? 0,
              ...callbacks,
              projectId: activeProjectId,
              workflowId,
              runningDynamicItemById: dynamicItemRunningByNodeId[node.id],
              v2AssetVersions: mergeV2AssetVersions(node.data.v2AssetVersions ?? [], v2AssetVersions, slotVersionAssets),
              v2Runtime: v2Runtime ?? v2FallbackRuntime,
              v2SlotRuntimeStatusById,
              v2OpenSlotId: activeV2SlotId,
              v2OpenStoryboardItemId: activeV2StoryboardItemId,
              v2SlotDraftsById,
              v2ReferenceAssetsBySlotId,
              v2LibraryReferenceOptions,
            },
          };
        }),
    [
      activeProjectId,
      activeV2SlotId,
      activeV2StoryboardItemId,
      callbacks,
      candidateSummaryByNodeId,
      dynamicItemRunningByNodeId,
      effectiveNodeStatusById,
      flowNodes,
      slotVersionAssets,
      v2AssetVersions,
      v2FallbackRuntime,
      v2LibraryReferenceOptions,
      v2ReferenceAssetsBySlotId,
      v2Runtime,
      v2SlotDraftsById,
      v2SlotRuntimeStatusById,
      workflowId,
    ],
  );

  const activeRuntimeEdgeIds = useMemo(() => {
    if (!isV2 && canvasRuntimeActiveEdgeIds.length) return new Set(canvasRuntimeActiveEdgeIds);
    const activeSourceNodeIds = isV2 ? v2ActiveEdgeSourceNodeIds : runningNodeIds;
    return executionRunningEdgeIds(flowEdges, new Set(activeSourceNodeIds));
  }, [canvasRuntimeActiveEdgeIds, flowEdges, isV2, runningNodeIds, v2ActiveEdgeSourceNodeIds]);

  const displayEdges = useMemo(
    () =>
      visibleWorkflowEdges(
        flowEdges,
        displayNodes.map((node) => ({ id: node.id, node_type: node.data.kind })),
      ).map((edge) => {
        const selectedEdgeActive = edge.id === selectedEdgeId;
        const runtimeEdgeActive = activeRuntimeEdgeIds.has(edge.id);
        const baseClassName = removeClassName(removeClassName(edge.className, "is-active-edge"), "is-runtime-active-edge");
        return {
          ...edge,
          animated: selectedEdgeActive || runtimeEdgeActive,
          className: joinClassNames(
            baseClassName,
            selectedEdgeActive ? "is-active-edge" : undefined,
            runtimeEdgeActive ? "is-runtime-active-edge" : undefined,
          ),
        };
      }),
    [activeRuntimeEdgeIds, displayNodes, flowEdges, selectedEdgeId],
  );

  return { displayNodes, activeRuntimeEdgeIds, displayEdges };
}

function joinClassNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}

function removeClassName(value: string | undefined, className: string) {
  return (value ?? "")
    .split(/\s+/)
    .filter((item) => item && item !== className)
    .join(" ");
}
