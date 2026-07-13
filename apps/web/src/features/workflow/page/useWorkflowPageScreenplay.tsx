import { useCallback, useEffect, useMemo, useRef, type MutableRefObject, type ReactNode } from "react";
import type { WorkflowItemV2 } from "../../../types-v2.ts";
import { V2ScreenplayDrawer } from "../v2/screenplay/V2ScreenplayDrawer.tsx";
import {
  useV2ScreenplayController,
  type V2ScreenplayController,
} from "../v2/screenplay/useV2ScreenplayController.ts";
import { createV2SynchronizationRefreshCoordinator } from "../runtime/v2SynchronizationRefreshCoordinator.ts";

type ScreenplayEventActions = Pick<
  V2ScreenplayController,
  "handleRuntimeEvents" | "refreshHistory" | "refreshSelected"
>;

export type WorkflowPageScreenplay = {
  controllerRef: MutableRefObject<V2ScreenplayController | null>;
  actionsRef: MutableRefObject<ScreenplayEventActions | null>;
  openScreenplay: (trigger: HTMLElement) => void;
  panel: ReactNode;
};

export function useWorkflowPageScreenplay({
  activeWorkflowId,
  workflowItems,
  refreshV2WorkflowGraph,
  refreshV2WorkflowStructure,
  syncV2RuntimeSnapshot,
}: {
  activeWorkflowId: string | null;
  workflowItems: WorkflowItemV2[];
  refreshV2WorkflowGraph: (
    workflowId: string,
    options?: { refreshRuntime?: boolean; refreshAssets?: boolean },
  ) => Promise<unknown>;
  refreshV2WorkflowStructure: (workflowId: string) => Promise<unknown>;
  syncV2RuntimeSnapshot: (workflowId: string) => Promise<unknown>;
}): WorkflowPageScreenplay {
  const triggerElementRef = useRef<HTMLElement | null>(null);
  const synchronizationCoordinatorRef = useRef<ReturnType<typeof createV2SynchronizationRefreshCoordinator> | null>(null);
  if (!synchronizationCoordinatorRef.current) {
    synchronizationCoordinatorRef.current = createV2SynchronizationRefreshCoordinator();
  }
  const synchronizationCoordinator = synchronizationCoordinatorRef.current;
  const controller = useV2ScreenplayController({
    refreshWorkflow: (workflowId) => refreshV2WorkflowGraph(workflowId),
    refreshRuntime: (workflowId) => syncV2RuntimeSnapshot(workflowId),
    refreshSynchronizationWorkflow: async (workflowId, scopes) => {
      const result = scopes.has("assets")
        ? await refreshV2WorkflowGraph(workflowId, { refreshRuntime: false, refreshAssets: true })
        : await refreshV2WorkflowStructure(workflowId);
      if (result === null) throw new Error("V2 synchronization workflow refresh failed.");
      return result;
    },
    synchronizationCoordinator,
  });
  const controllerRef = useRef<V2ScreenplayController | null>(null);
  const actionsRef = useRef<ScreenplayEventActions | null>(null);
  controllerRef.current = controller;
  actionsRef.current = {
    handleRuntimeEvents: controller.handleRuntimeEvents,
    refreshHistory: controller.refreshHistory,
    refreshSelected: controller.refreshSelected,
  };

  const productOptions = useMemo(
    () => workflowItems
      .filter((item) => item.item_type === "product" && item.lifecycle_state !== "archived")
      .map((item) => ({ id: item.item_id, label: item.display_name || item.item_id })),
    [workflowItems],
  );
  const { discardDraftAndClose, open } = controller;

  const openScreenplay = useCallback((trigger: HTMLElement) => {
    if (!activeWorkflowId) return;
    triggerElementRef.current = trigger;
    void open(activeWorkflowId);
  }, [activeWorkflowId, open]);

  useEffect(() => {
    synchronizationCoordinator.activateWorkflow(activeWorkflowId);
    return () => synchronizationCoordinator.clearWorkflow(activeWorkflowId);
  }, [activeWorkflowId, synchronizationCoordinator]);

  useEffect(() => {
    if (!controller.state.workflowId || controller.state.workflowId === activeWorkflowId) return;
    triggerElementRef.current = null;
    discardDraftAndClose();
  }, [activeWorkflowId, controller.state.workflowId, discardDraftAndClose]);

  const panel = activeWorkflowId && controller.state.workflowId === activeWorkflowId
    ? <V2ScreenplayDrawer controller={controller} productOptions={productOptions} returnFocusRef={triggerElementRef} />
    : null;

  return { controllerRef, actionsRef, openScreenplay, panel };
}
