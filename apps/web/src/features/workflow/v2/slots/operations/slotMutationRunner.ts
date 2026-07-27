import type { WorkflowV2 } from "../../../../../types-v2.ts";
import type { V2WorkflowApplicationCapture } from "../../../graph/v2WorkflowApplicationRevisionGuard.ts";
import { reconcileV2SlotMutationWorkflow } from "../v2SlotMutationWorkflowGuard.ts";

type ApplyWorkflowOptions = { refreshAssetsReason?: string | false };

export type SlotMutationRunnerDependencies = {
  getWorkflowId: () => string | null | undefined;
  currentWorkflowIsV2: () => boolean;
  getActiveWorkflowId: () => string | null;
  getWorkflowEpoch: () => number;
  captureRevision: (workflowId: string) => V2WorkflowApplicationCapture;
  isCurrentRevision: (
    capture: V2WorkflowApplicationCapture,
    currentActiveWorkflowId: string | null,
  ) => boolean;
  applyWorkflow: (workflow: WorkflowV2, options?: ApplyWorkflowOptions) => Promise<void>;
  refreshWorkflow: (workflowId: string) => Promise<WorkflowV2 | null>;
  refreshAssets: (
    workflowId: string,
    reason: string,
    workflow?: WorkflowV2 | null,
  ) => Promise<unknown>;
  syncSnapshot: (workflowId: string) => Promise<unknown>;
};

type MutationResult = {
  stale: boolean;
  workflow: WorkflowV2 | null;
};

export type SlotWorkflowMutationScope = {
  workflowId: string;
  epoch: number;
};

type MutationLifecycle<T> = {
  setStatus: (status: string) => void;
  setInFlight?: (inFlight: boolean, error?: string) => void;
  startStatus?: string;
  successStatus?: string | ((result: T) => string);
  failureMessage: string;
  cleanupBeforeErrorStatus?: boolean;
  onError?: (error: unknown, message: string) => void;
  propagateError?: boolean;
};

type GenerationCompletion = {
  workflowId: string;
  scope: SlotWorkflowMutationScope;
  capture: V2WorkflowApplicationCapture;
  returnedWorkflow: WorkflowV2 | null;
  refreshAssetsReason: string;
  refreshSlotVersions?: (
    scope: SlotWorkflowMutationScope,
  ) => Promise<unknown>;
  afterRefresh?: (workflow: WorkflowV2 | null) => void | Promise<void>;
};

const STALE_WITH_REFRESH_MESSAGE =
  "V2 slot changed while this request was in flight. Latest state loaded; review and retry.";
const STALE_WITHOUT_REFRESH_MESSAGE =
  "V2 slot changed while this request was in flight. Review the latest state and retry.";

class StaleSlotWorkflowMutationError extends Error {
  constructor() {
    super("V2 slot operation cancelled after workflow navigation.");
    this.name = "StaleSlotWorkflowMutationError";
  }
}

export function createSlotMutationRunner(dependencies: SlotMutationRunnerDependencies) {
  function activeWorkflowId() {
    const workflowId = dependencies.getWorkflowId();
    return workflowId && dependencies.currentWorkflowIsV2() ? workflowId : null;
  }

  function isWorkflowCurrent(workflowId: string) {
    return dependencies.getActiveWorkflowId() === workflowId;
  }

  function capture(workflowId: string) {
    return dependencies.captureRevision(workflowId);
  }

  function captureWorkflowScope(
    workflowId: string,
  ): SlotWorkflowMutationScope {
    return {
      workflowId,
      epoch: dependencies.getWorkflowEpoch(),
    };
  }

  function isWorkflowScopeCurrent(scope: SlotWorkflowMutationScope) {
    return isWorkflowCurrent(scope.workflowId)
      && dependencies.getWorkflowEpoch() === scope.epoch;
  }

  function requireCurrentWorkflowScope(scope: SlotWorkflowMutationScope) {
    if (!isWorkflowScopeCurrent(scope)) {
      throw new StaleSlotWorkflowMutationError();
    }
  }

  function isStaleWorkflowMutation(error: unknown) {
    return error instanceof StaleSlotWorkflowMutationError;
  }

  async function applyReconciledWorkflow(
    workflowId: string,
    revisionCapture: V2WorkflowApplicationCapture,
    returnedWorkflow: WorkflowV2 | null,
    options?: ApplyWorkflowOptions,
  ) {
    const reconciled = await reconcileV2SlotMutationWorkflow({
      workflowId,
      capture: revisionCapture,
      activeWorkflowId: dependencies.getActiveWorkflowId(),
      isCurrentRevision: dependencies.isCurrentRevision,
      returnedWorkflow,
      applyWorkflowV2: (workflow) => dependencies.applyWorkflow(workflow, options),
      refreshLatestWorkflow: () => dependencies.refreshWorkflow(workflowId),
    });
    if (reconciled.stale && !reconciled.workflow) {
      throw new Error(STALE_WITHOUT_REFRESH_MESSAGE);
    }
    return reconciled;
  }

  function requireFresh(result: MutationResult) {
    if (result.stale) throw new Error(STALE_WITH_REFRESH_MESSAGE);
    return result;
  }

  async function requireFreshWorkflow(
    workflowId: string,
    revisionCapture: V2WorkflowApplicationCapture,
  ) {
    return requireFresh(await applyReconciledWorkflow(workflowId, revisionCapture, null));
  }

  async function applyGuardedWorkflow(
    workflowId: string,
    workflow: WorkflowV2,
    options?: ApplyWorkflowOptions,
  ) {
    if (!isWorkflowCurrent(workflowId)) return false;
    await dependencies.applyWorkflow(workflow, options);
    return true;
  }

  async function completeGeneration(options: GenerationCompletion) {
    if (options.scope.workflowId !== options.workflowId) {
      throw new StaleSlotWorkflowMutationError();
    }
    requireCurrentWorkflowScope(options.scope);
    const reconciled = requireFresh(await applyReconciledWorkflow(
      options.workflowId,
      options.capture,
      options.returnedWorkflow,
      { refreshAssetsReason: false },
    ));
    requireCurrentWorkflowScope(options.scope);
    await dependencies.refreshAssets(
      options.workflowId,
      options.refreshAssetsReason,
      options.returnedWorkflow,
    );
    requireCurrentWorkflowScope(options.scope);
    await dependencies.syncSnapshot(options.workflowId);
    requireCurrentWorkflowScope(options.scope);
    await options.refreshSlotVersions?.(options.scope);
    requireCurrentWorkflowScope(options.scope);
    await options.afterRefresh?.(reconciled.workflow);
    requireCurrentWorkflowScope(options.scope);
    return reconciled;
  }

  async function refreshWorkflowSnapshotAndVersions(
    workflowId: string,
    refreshSlotVersions?: (
      scope: SlotWorkflowMutationScope,
    ) => Promise<unknown>,
    scope = captureWorkflowScope(workflowId),
  ) {
    if (scope.workflowId !== workflowId) {
      throw new StaleSlotWorkflowMutationError();
    }
    requireCurrentWorkflowScope(scope);
    const workflow = await dependencies.refreshWorkflow(workflowId);
    requireCurrentWorkflowScope(scope);
    await dependencies.syncSnapshot(workflowId);
    requireCurrentWorkflowScope(scope);
    await refreshSlotVersions?.(scope);
    requireCurrentWorkflowScope(scope);
    return workflow;
  }

  async function execute<T>(
    lifecycle: MutationLifecycle<T>,
    operation: (
      scope: SlotWorkflowMutationScope | null,
    ) => Promise<T>,
  ): Promise<T | undefined> {
    const workflowId = activeWorkflowId();
    const scope = workflowId ? captureWorkflowScope(workflowId) : null;
    const lifecycleIsCurrent = () => (
      !scope || isWorkflowScopeCurrent(scope)
    );
    lifecycle.setInFlight?.(true);
    if (lifecycle.startStatus) lifecycle.setStatus(lifecycle.startStatus);
    let result: T | undefined;
    let failure: { error: unknown; message: string } | null = null;
    try {
      result = await operation(scope);
      if (lifecycleIsCurrent()) {
        const successStatus = typeof lifecycle.successStatus === "function"
          ? lifecycle.successStatus(result)
          : lifecycle.successStatus;
        if (successStatus) lifecycle.setStatus(successStatus);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : lifecycle.failureMessage;
      failure = { error, message };
      if (lifecycleIsCurrent()) {
        lifecycle.onError?.(error, message);
      }
      if (
        lifecycle.cleanupBeforeErrorStatus === false
        && lifecycleIsCurrent()
      ) {
        lifecycle.setStatus(message);
      }
    } finally {
      if (lifecycleIsCurrent()) {
        lifecycle.setInFlight?.(false, failure?.message);
      }
    }
    if (!failure) return result;
    if (
      lifecycle.cleanupBeforeErrorStatus !== false
      && lifecycleIsCurrent()
    ) {
      lifecycle.setStatus(failure.message);
    }
    if (lifecycle.propagateError) throw failure.error;
    return undefined;
  }

  return {
    activeWorkflowId,
    isWorkflowCurrent,
    capture,
    captureWorkflowScope,
    isWorkflowScopeCurrent,
    isStaleWorkflowMutation,
    applyReconciledWorkflow,
    requireFresh,
    requireFreshWorkflow,
    applyGuardedWorkflow,
    completeGeneration,
    refreshWorkflowSnapshotAndVersions,
    refreshAssets: dependencies.refreshAssets,
    syncSnapshot: dependencies.syncSnapshot,
    refreshWorkflow: dependencies.refreshWorkflow,
    execute,
  };
}

export type SlotMutationRunner = ReturnType<typeof createSlotMutationRunner>;
