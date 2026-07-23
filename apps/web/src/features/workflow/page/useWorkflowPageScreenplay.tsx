import { useCallback, useEffect, useMemo, useRef, type MutableRefObject, type ReactNode } from "react";
import type { WorkflowItemV2 } from "../../../types-v2.ts";
import { LazyV2ScreenplayDrawer } from "./LazyV2ScreenplayDrawer.tsx";
import {
  useV2ScreenplayController,
  type V2ScreenplayController,
} from "../v2/screenplay/useV2ScreenplayController.ts";
import { createV2SynchronizationRefreshCoordinator } from "../runtime/v2SynchronizationRefreshCoordinator.ts";

const V2_AUTHORING_DRAFT_DISCARDED_EVENT = "v2-authoring-draft-discarded";
const V2_AUTHORING_CONFLICT_RESOLVED_EVENT = "v2-authoring-conflict-resolved";

type V2AuthoringConflictResolution = {
  target: { resource: "project" | "workflow"; id: string };
  operationPath: string;
  action: "retry" | "discard";
};

export function shouldRefreshScreenplayAfterAuthoringResolution(
  resolution: V2AuthoringConflictResolution | null | undefined,
  workflowId: string | null,
): boolean {
  return resolution?.action === "retry"
    && resolution.target.resource === "workflow"
    && resolution.target.id === workflowId
    && /\/script(?:\/|$)/.test(resolution.operationPath);
}

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

  useEffect(() => {
    function discardConflictDraft(event: Event) {
      const resolution = (event as CustomEvent<V2AuthoringConflictResolution>).detail;
      if (resolution?.target.resource !== "workflow" || resolution.target.id !== activeWorkflowId) return;
      if (!/\/script(?:\/|$)/.test(resolution.operationPath)) return;
      triggerElementRef.current = null;
      controllerRef.current?.discardDraftAndClose();
    }

    window.addEventListener(V2_AUTHORING_DRAFT_DISCARDED_EVENT, discardConflictDraft as EventListener);
    return () => window.removeEventListener(V2_AUTHORING_DRAFT_DISCARDED_EVENT, discardConflictDraft as EventListener);
  }, [activeWorkflowId]);

  useEffect(() => {
    function refreshScreenplayAfterRetry(event: Event) {
      const resolution = (event as CustomEvent<V2AuthoringConflictResolution>).detail;
      if (!shouldRefreshScreenplayAfterAuthoringResolution(resolution, activeWorkflowId)) return;
      void controllerRef.current?.refreshSelected();
    }

    window.addEventListener(V2_AUTHORING_CONFLICT_RESOLVED_EVENT, refreshScreenplayAfterRetry as EventListener);
    return () => window.removeEventListener(V2_AUTHORING_CONFLICT_RESOLVED_EVENT, refreshScreenplayAfterRetry as EventListener);
  }, [activeWorkflowId]);

  const panel = activeWorkflowId && controller.state.workflowId === activeWorkflowId
    ? <LazyV2ScreenplayDrawer controller={controller} productOptions={productOptions} returnFocusRef={triggerElementRef} />
    : null;

  return { controllerRef, actionsRef, openScreenplay, panel };
}
