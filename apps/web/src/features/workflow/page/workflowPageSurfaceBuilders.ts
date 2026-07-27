import { mediaUrl } from "../../../api/client.ts";
import { localRevisionStateKey } from "../../../workflow/localRevision.ts";
import { DEFAULT_LAYOUT_VIEWPORT_PADDING, validateConnection } from "../canvas/workflowCanvasModel.ts";
import { finalCompositionTimelineTargetAsset } from "../final-composition/useFinalCompositionOperations.ts";
import { getTimelineClipCount } from "../final-composition/finalCompositionTimelineModel.ts";
import { formatSavedAt } from "./workflowPageFormatters.ts";
import type {
  WorkflowPageBuiltSurfaces,
  WorkflowPageCanvasAssemblyArgs,
  WorkflowPagePickerSelectionArgs,
  WorkflowPageSidePanelsAssemblyArgs,
  WorkflowPageSurfaceVisibilityArgs,
  WorkflowPageToolbarAssemblyArgs,
  WorkflowPageWorkbenchAssemblyArgs,
} from "./workflowPageContracts.ts";

export function buildWorkflowCanvasSurface(
  args: WorkflowPageCanvasAssemblyArgs,
): WorkflowPageBuiltSurfaces["canvas"] {
  return {
    model: args.model,
    actions: {
      ...args.actions,
      isValidConnection: (connection) => validateConnection(connection, args.flowNodes, args.flowEdges).ok,
      onNodeClick: (_event, node) => {
        args.setSelectedEdgeId(null);
        args.setSelectedNodeId(node.id);
        if (args.currentWorkflowIsV2()) {
          args.setActiveV2SlotId(null);
          args.setActiveV2StoryboardItemId(null);
          args.setDetailsOpen(node.id === "final-composition");
        } else {
          args.setDetailsOpen(true);
        }
      },
      onEdgeClick: (event, edge) => {
        event.stopPropagation();
        args.setSelectedEdgeId(edge.id);
        if (args.currentWorkflowIsV2()) args.setDetailsOpen(false);
        args.setFlowEdges((current) =>
          current.map((item) => ({ ...item, selected: item.id === edge.id })),
        );
      },
      onPaneClick: () => {
        args.setSelectedEdgeId(null);
        args.setActiveV2SlotId(null);
        args.setActiveV2StoryboardItemId(null);
        args.setDetailsOpen(false);
      },
      onNodesDelete: (deleted) => {
        const ids = new Set(deleted.map((node) => node.id));
        if (args.workflowId) {
          deleted.forEach((node) => void args.deleteNodeFromBackend(node.id));
        }
        args.setCanvasNodes((current) => current.filter((node) => !ids.has(node.id)));
      },
      onEdgesDelete: (deleted) => {
        const ids = new Set(deleted.map((edge) => edge.id));
        if (args.selectedEdgeId && ids.has(args.selectedEdgeId)) {
          args.setSelectedEdgeId(null);
        }
        if (args.workflowId) {
          deleted.forEach((edge) => void args.deleteEdgeFromBackend(edge.id));
        }
        args.setFlowEdges((current) => current.filter((edge) => !ids.has(edge.id)));
      },
    },
  };
}

export function buildWorkflowWorkbenchSurface(
  args: WorkflowPageWorkbenchAssemblyArgs,
): WorkflowPageBuiltSurfaces["workbench"] {
  const workflowId = args.model.workflow?.workflow_id;
  const finalCompositionTargetAsset = workflowId
    ? finalCompositionTimelineTargetAsset(workflowId)
    : null;
  const finalCompositionRevisionState =
    workflowId && finalCompositionTargetAsset
      ? args.model.localRevisionByKey[
          localRevisionStateKey(workflowId, "final-composition", finalCompositionTargetAsset)
        ]
      : undefined;

  return {
    model: {
      ...args.baseModel,
      ...args.model,
      finalCompositionTimelineDraft: args.model.finalCompositionTimelineState.draft,
      finalCompositionRevisionState,
      finalCompositionTargetAsset,
    },
    actions: args.actions,
  };
}

export function buildWorkflowSidePanelsSurface(
  args: WorkflowPageSidePanelsAssemblyArgs,
): WorkflowPageBuiltSurfaces["sidePanels"] {
  const exportVideoPath =
    args.model.exportResult?.public_url || args.model.exportResult?.local_path || "";

  return {
    model: {
      ...args.model,
      timelineClipCount: getTimelineClipCount(args.model.videoTimeline),
      mediaStatusLabel: args.mediaStatus?.status ?? "media unknown",
      exportVideoUrl: exportVideoPath ? mediaUrl(exportVideoPath) : "",
      currentWorkflowIsV2: args.currentWorkflowIsV2(),
    },
    actions: args.actions,
  };
}

export function buildWorkflowBottomToolbarSurface(
  args: WorkflowPageToolbarAssemblyArgs,
): WorkflowPageBuiltSurfaces["toolbar"] {
  const executionId = args.activeExecutionId ?? args.workflowRunExecutionId;
  const executionState =
    args.executionPollingState !== "idle" ? ` · ${args.executionPollingState}` : "";
  const toolbarStatus = `${args.status}${
    executionId && !args.status.includes(executionId) ? ` · ${executionId}` : ""
  }${executionState}${
    args.runtimeConnectionLabel ? ` · ${args.runtimeConnectionLabel}` : ""
  }${args.savedAt ? ` · saved ${formatSavedAt(args.savedAt)}` : ""}`;

  return {
    model: {
      workflowRunning: args.workflowRunning,
      saving: args.saving,
      canUndo: args.canvasHistoryCount > 0,
      canRedo: args.canvasFutureCount > 0,
      canDeleteSelection: args.hasCanvasSelection || args.hasSelectedPlanNode,
      toolbarStatus,
    },
    actions: {
      createNewProject: args.createNewProject,
      runWorkflow: args.runWorkflow,
      saveCanvas: args.saveCanvas,
      undoCanvas: args.undoCanvas,
      redoCanvas: args.redoCanvas,
      deleteSelection: args.deleteSelection,
      autoLayout: args.autoLayout,
      fitView: () =>
        args.reactFlow?.fitView({ padding: DEFAULT_LAYOUT_VIEWPORT_PADDING }),
    },
  };
}

export function workflowPageSurfaceVisibility(args: WorkflowPageSurfaceVisibilityArgs) {
  return {
    showWorkbench: !args.isV2,
    showV2FinalComposition: Boolean(
      args.isV2 &&
        args.detailsOpen &&
        args.selectedNodeId === "final-composition" &&
        args.workflowId,
    ),
  };
}

export function workflowPageFloatingEditorVisibility(args: {
  isV2: boolean;
  hasActiveSlotId: boolean;
  slotIsEditable: boolean;
  hasSlotDraft: boolean;
  hasActiveStoryboardItemId: boolean;
  hasStoryboardItem: boolean;
}) {
  return {
    showSlotComposer:
      args.isV2 &&
      args.hasActiveSlotId &&
      args.slotIsEditable &&
      args.hasSlotDraft,
    showStoryboardComposer:
      args.isV2 &&
      args.hasActiveStoryboardItemId &&
      args.hasStoryboardItem,
  };
}

export function selectWorkflowPickerEntity(args: WorkflowPagePickerSelectionArgs) {
  if (args.pickerTarget === "v2-slot-replace") {
    if (args.activeV2SlotId) {
      void args.replaceV2SlotWithLibraryEntity(args.activeV2SlotId, args.entity);
    }
    args.closePicker();
    return;
  }
  args.toggleLibraryEntityForTarget(args.pickerTarget, args.entity);
}
