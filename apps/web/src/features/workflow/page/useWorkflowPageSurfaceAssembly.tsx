import { WorkflowBottomToolbar } from "./WorkflowBottomToolbar.tsx";
import { WorkflowCanvasSurface } from "./WorkflowCanvasSurface.tsx";
import { WorkflowPageFloatingEditors } from "./WorkflowPageFloatingEditors.tsx";
import {
  WorkflowPageFinalPanel,
  WorkflowPageOverlays,
} from "./WorkflowPageOverlays.tsx";
import { WorkflowSidePanelsSurface } from "./WorkflowSidePanelsSurface.tsx";
import type { WorkflowPageSurfaceAssemblyArgs } from "./workflowPageContracts.ts";
import {
  buildWorkflowBottomToolbarSurface,
  buildWorkflowCanvasSurface,
  buildWorkflowSidePanelsSurface,
  workflowPageSurfaceVisibility,
} from "./workflowPageSurfaceBuilders.ts";

export function useWorkflowPageSurfaceAssembly(
  args: WorkflowPageSurfaceAssemblyArgs,
) {
  const canvasSurface = buildWorkflowCanvasSurface(args.canvas);
  const sidePanelsSurface = buildWorkflowSidePanelsSurface(args.sidePanels);
  const toolbarSurface = buildWorkflowBottomToolbarSurface(args.toolbar);
  const visibility = workflowPageSurfaceVisibility({
    isV2: args.overlays.finalComposition.isV2,
    detailsOpen: args.chrome.model.detailsOpen,
    selectedNodeId: args.overlays.finalComposition.selectedNodeId,
    workflowId: args.overlays.finalComposition.workflowId,
  });

  const canvas = (
    <section className="workflow-page">
      <WorkflowCanvasSurface
        model={canvasSurface.model}
        actions={canvasSurface.actions}
      />
      <WorkflowSidePanelsSurface
        model={sidePanelsSurface.model}
        actions={sidePanelsSurface.actions}
      />
      <WorkflowPageFinalPanel
        finalComposition={args.overlays.finalComposition}
      />
      <WorkflowPageFloatingEditors {...args.floatingEditors} />
      <WorkflowBottomToolbar
        model={toolbarSurface.model}
        actions={toolbarSurface.actions}
      />
      <WorkflowPageOverlays {...args.overlays} />
    </section>
  );

  return {
    model: {
      chrome: args.chrome.model,
      canvas,
      copilot: null,
      panels: args.screenplayPanel,
      modals: null,
    },
    actions: {
      toggleCollapsed: () => args.chrome.setCollapsed((value) => !value),
      setDetailsOpen: args.chrome.setDetailsOpen,
      setRunPanelOpen: args.chrome.setRunPanelOpen,
      setVariablesPanelOpen: args.chrome.setVariablesPanelOpen,
    },
  };
}
