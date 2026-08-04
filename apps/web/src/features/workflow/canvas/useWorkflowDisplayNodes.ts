import { useMemo, useRef } from "react";
import { executionRunningEdgeIds } from "../../../workflow/executionRuntime.ts";
import { visibleWorkflowEdges } from "../../../workflow/visibility.ts";
import type { CanvasEdge } from "../types.ts";
import {
  createWorkflowDisplayNodeProjector,
  type WorkflowDisplayNodeProjectionInput,
  type WorkflowDisplayNodeProjector,
} from "./workflowDisplayNodeProjector.ts";

export type { WorkflowDisplayNodeCallbacks } from "./workflowDisplayNodeProjector.ts";

export type WorkflowDisplayNodeInput = WorkflowDisplayNodeProjectionInput & {
  flowEdges: CanvasEdge[];
  selectedEdgeId?: string | null;
  canvasRuntimeActiveEdgeIds: string[];
  runningNodeIds: string[];
  v2ActiveEdgeSourceNodeIds: string[];
  isV2: boolean;
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
  v2AudioMode,
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
  const displayNodeProjectorRef = useRef<WorkflowDisplayNodeProjector | null>(null);
  if (!displayNodeProjectorRef.current) {
    displayNodeProjectorRef.current = createWorkflowDisplayNodeProjector();
  }
  const displayNodes = useMemo(
    () => displayNodeProjectorRef.current!.project({
      flowNodes,
      effectiveNodeStatusById,
      candidateSummaryByNodeId,
      activeProjectId,
      workflowId,
      dynamicItemRunningByNodeId,
      v2AssetVersions,
      slotVersionAssets,
      v2Runtime,
      v2FallbackRuntime,
      v2AudioMode,
      v2SlotRuntimeStatusById,
      activeV2SlotId,
      activeV2StoryboardItemId,
      v2SlotDraftsById,
      v2ReferenceAssetsBySlotId,
      v2LibraryReferenceOptions,
      callbacks,
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
      v2AudioMode,
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
