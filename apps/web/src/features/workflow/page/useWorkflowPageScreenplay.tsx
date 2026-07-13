import { useCallback, useEffect, useMemo, useRef, type MutableRefObject, type ReactNode } from "react";
import type { WorkflowItemV2 } from "../../../types-v2.ts";
import { V2ScreenplayDrawer } from "../v2/screenplay/V2ScreenplayDrawer.tsx";
import {
  useV2ScreenplayController,
  type V2ScreenplayController,
} from "../v2/screenplay/useV2ScreenplayController.ts";

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
  syncV2RuntimeSnapshot,
}: {
  activeWorkflowId: string | null;
  workflowItems: WorkflowItemV2[];
  refreshV2WorkflowGraph: (workflowId: string) => Promise<unknown>;
  syncV2RuntimeSnapshot: (workflowId: string) => Promise<unknown>;
}): WorkflowPageScreenplay {
  const triggerElementRef = useRef<HTMLElement | null>(null);
  const controller = useV2ScreenplayController({
    refreshWorkflow: (workflowId) => refreshV2WorkflowGraph(workflowId),
    refreshRuntime: (workflowId) => syncV2RuntimeSnapshot(workflowId),
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
    if (!controller.state.workflowId || controller.state.workflowId === activeWorkflowId) return;
    triggerElementRef.current = null;
    discardDraftAndClose();
  }, [activeWorkflowId, controller.state.workflowId, discardDraftAndClose]);

  const panel = activeWorkflowId && controller.state.workflowId === activeWorkflowId
    ? <V2ScreenplayDrawer controller={controller} productOptions={productOptions} returnFocusRef={triggerElementRef} />
    : null;

  return { controllerRef, actionsRef, openScreenplay, panel };
}
