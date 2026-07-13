import { useCallback, useReducer, useRef } from "react";
import { V2ApiError, v2Api } from "../../../../api/v2Client.ts";
import type {
  V2EditableScriptDocument,
  V2LinkedContextSummary,
  V2ScriptConfirmResponse,
  V2ScriptReadResponse,
  V2ScriptSelectVersionResponse,
  V2ScriptVersionListResponse,
  WorkflowRuntimeEventV2,
} from "../../../../types-v2.ts";
import { isV2SynchronizationEvent } from "../../../../workflow-v2/runtime.ts";
import { validateEditableScript } from "./screenplayModel.ts";
import {
  createV2LocalSynchronizationRefreshPlan,
  createV2SynchronizationRefreshPlan,
  type V2SynchronizationRefreshPlan,
} from "../../runtime/v2RuntimeEventModel.ts";
import {
  createV2SynchronizationRefreshCoordinator,
  type V2SynchronizationRefreshCoordinator,
  type V2SynchronizationRefreshScope,
} from "../../runtime/v2SynchronizationRefreshCoordinator.ts";
import {
  createV2ScreenplayState,
  screenplayReducer,
  type ScreenplayRequestError,
  type ScreenplayReducerAction,
  type V2ScreenplayState,
} from "./screenplayReducer.ts";

export type ScreenplayDraftUpdater = (draft: V2EditableScriptDocument) => V2EditableScriptDocument;

export type V2ScreenplayApi = Pick<typeof v2Api, "script" | "confirmScript" | "scriptVersions" | "selectScriptVersion">;

export type V2ScreenplayControllerCallbacks = {
  refreshWorkflow?: (workflowId: string, linkedContext: V2LinkedContextSummary) => Promise<unknown> | unknown;
  refreshRuntime?: (workflowId: string, linkedContext: V2LinkedContextSummary) => Promise<unknown> | unknown;
  refreshSynchronizationWorkflow?: (
    workflowId: string,
    scopes: ReadonlySet<V2SynchronizationRefreshScope>,
  ) => Promise<unknown> | unknown;
};

export type V2ScreenplayControllerRuntimeOptions = V2ScreenplayControllerCallbacks & {
  api: V2ScreenplayApi;
  getState: () => V2ScreenplayState;
  dispatch: (action: ScreenplayReducerAction) => void;
  synchronizationCoordinator?: V2SynchronizationRefreshCoordinator;
};

export type UseV2ScreenplayControllerOptions = V2ScreenplayControllerCallbacks & {
  api?: V2ScreenplayApi;
  synchronizationCoordinator?: V2SynchronizationRefreshCoordinator;
};

export type V2ScreenplayController = {
  state: V2ScreenplayState;
  open: (workflowId: string) => Promise<void>;
  close: () => "closed" | "confirmation_required";
  cancelClose: () => void;
  discardDraftAndClose: () => void;
  updateDraft: (update: V2EditableScriptDocument | ScreenplayDraftUpdater) => void;
  confirm: () => Promise<void>;
  selectVersion: (versionId: string) => Promise<void>;
  refreshSelected: () => Promise<void>;
  refreshHistory: () => Promise<void>;
  keepReviewingLocalDraft: () => void;
  discardLocalDraftAndReloadLatest: () => void;
  handleRuntimeEvents: (events: WorkflowRuntimeEventV2[]) => Promise<void>;
};

export type V2ScreenplayControllerRuntime = Omit<V2ScreenplayController, "state">;

export function createV2ScreenplayControllerRuntime({
  api,
  getState,
  dispatch,
  refreshWorkflow,
  refreshRuntime,
  refreshSynchronizationWorkflow,
  synchronizationCoordinator = createV2SynchronizationRefreshCoordinator(),
}: V2ScreenplayControllerRuntimeOptions): V2ScreenplayControllerRuntime {
  let sessionGeneration = 0;
  let requestToken = 0;
  let queuedHistoryRefresh: {
    workflowId: string;
    generation: number;
    ownerRequestToken: number;
    promise: Promise<void>;
    resolve: () => void;
  } | null = null;
  let queuedSynchronizationPlans: Array<{
    workflowId: string;
    generation: number;
    plan: V2SynchronizationRefreshPlan;
  }> = [];

  const nextRequestToken = () => {
    requestToken += 1;
    return requestToken;
  };

  const isSessionActive = (workflowId: string, generation: number): boolean => {
    const state = getState();
    return state.isOpen && state.workflowId === workflowId && state.generation === generation;
  };

  const isSelectedRequestActive = (workflowId: string, generation: number, request: number): boolean => {
    return isSessionActive(workflowId, generation) && getState().selectedRequestToken === request;
  };

  const isHistoryRequestActive = (workflowId: string, generation: number, request: number): boolean => {
    return isSessionActive(workflowId, generation) && getState().historyRequestToken === request;
  };

  const isSelectedBundleRequestActive = (workflowId: string, generation: number, request: number): boolean => {
    return isSelectedRequestActive(workflowId, generation, request)
      && getState().historyRequestToken === request;
  };

  const isOpenRequestActive = (workflowId: string, generation: number, request: number): boolean => {
    return isSelectedBundleRequestActive(workflowId, generation, request);
  };

  const isInitialOpenPending = (state: V2ScreenplayState): boolean => {
    return state.selectedScriptVersionId === null
      && state.draft === null
      && state.selectedRequestToken !== null
      && state.historyRequestToken === state.selectedRequestToken;
  };

  const hasActiveLocalSelectionOperation = (state: V2ScreenplayState): boolean =>
    (state.isSaving
      && state.saveRequestToken !== null
      && state.saveRequestToken === state.selectedRequestToken)
    || (state.isSelecting
      && state.selectRequestToken !== null
      && state.selectRequestToken === state.selectedRequestToken);

  const clearQueuedSynchronizationPlans = (): void => {
    queuedSynchronizationPlans = [];
  };

  const queueSynchronizationPlan = (
    workflowId: string,
    generation: number,
    plan: V2SynchronizationRefreshPlan,
  ): void => {
    let mergedPlan = plan;
    const aliases = synchronizationPlanAliases(plan);
    for (let index = queuedSynchronizationPlans.length - 1; index >= 0; index -= 1) {
      const queued = queuedSynchronizationPlans[index];
      if (queued.workflowId !== workflowId || queued.generation !== generation) continue;
      const queuedAliases = synchronizationPlanAliases(queued.plan);
      const shouldMerge = aliases.size === 0
        ? queuedAliases.size === 0
        : setsOverlap(aliases, queuedAliases);
      if (!shouldMerge) continue;
      mergedPlan = mergeSynchronizationRefreshPlans(queued.plan, mergedPlan);
      synchronizationPlanAliases(mergedPlan).forEach((alias) => aliases.add(alias));
      queuedSynchronizationPlans.splice(index, 1);
    }
    queuedSynchronizationPlans.push({ workflowId, generation, plan: mergedPlan });
    if (queuedSynchronizationPlans.length > 32) queuedSynchronizationPlans.splice(0, queuedSynchronizationPlans.length - 32);
  };

  const clearQueuedHistoryRefresh = (criteria?: { workflowId: string; generation: number; ownerRequestToken?: number }): void => {
    const queued = queuedHistoryRefresh;
    if (!queued || (criteria && (
      queued.workflowId !== criteria.workflowId
      || queued.generation !== criteria.generation
      || (criteria.ownerRequestToken !== undefined && queued.ownerRequestToken !== criteria.ownerRequestToken)
    ))) return;
    queuedHistoryRefresh = null;
    queued.resolve();
  };

  const handoffQueuedHistoryRefresh = (workflowId: string, generation: number, ownerRequestToken: number): void => {
    if (queuedHistoryRefresh?.workflowId !== workflowId || queuedHistoryRefresh.generation !== generation) return;
    queuedHistoryRefresh.ownerRequestToken = ownerRequestToken;
  };

  const queueHistoryRefresh = (workflowId: string, generation: number): Promise<void> => {
    if (queuedHistoryRefresh?.workflowId === workflowId && queuedHistoryRefresh.generation === generation) {
      return queuedHistoryRefresh.promise;
    }
    clearQueuedHistoryRefresh();
    let resolve = () => {};
    const promise = new Promise<void>((nextResolve) => { resolve = nextResolve; });
    queuedHistoryRefresh = {
      workflowId,
      generation,
      ownerRequestToken: getState().selectedRequestToken ?? -1,
      promise,
      resolve,
    };
    return promise;
  };

  const flushQueuedHistoryRefresh = async (workflowId: string, generation: number, ownerRequestToken: number): Promise<void> => {
    const queued = queuedHistoryRefresh;
    if (!queued || queued.workflowId !== workflowId || queued.generation !== generation || queued.ownerRequestToken !== ownerRequestToken) return;
    queuedHistoryRefresh = null;
    try {
      if (isSessionActive(workflowId, generation)) await refreshHistory();
    } finally {
      queued.resolve();
    }
  };

  const open = async (workflowId: string): Promise<void> => {
    synchronizationCoordinator.activateWorkflow(workflowId);
    clearQueuedHistoryRefresh();
    clearQueuedSynchronizationPlans();
    const generation = ++sessionGeneration;
    const request = nextRequestToken();
    dispatch({ type: "OPEN_STARTED", workflowId, generation, requestToken: request });
    try {
      const [selected, history] = await Promise.all([api.script(workflowId), api.scriptVersions(workflowId)]);
      assertCoherentOpenResponse(workflowId, selected, history);
      if (!isOpenRequestActive(workflowId, generation, request)) return;
      dispatch({
        type: "OPEN_SUCCEEDED",
        workflowId,
        generation,
        requestToken: request,
        script: selected.script,
        selectedScriptVersionId: selected.selected_script_version_id,
        versions: history.versions,
      });
      await flushQueuedHistoryRefresh(workflowId, generation, request);
    } catch (error) {
      if (!isOpenRequestActive(workflowId, generation, request)) {
        clearQueuedHistoryRefresh({ workflowId, generation, ownerRequestToken: request });
        return;
      }
      dispatch({ type: "OPEN_FAILED", workflowId, generation, requestToken: request, error: toRequestError("open", error) });
      clearQueuedHistoryRefresh({ workflowId, generation, ownerRequestToken: request });
    }
  };

  const updateDraft = (update: V2EditableScriptDocument | ScreenplayDraftUpdater): void => {
    const current = getState().draft;
    if (!current) return;
    const workingCopy = structuredClone(current);
    const document = typeof update === "function" ? update(workingCopy) : update;
    dispatch({ type: "DRAFT_UPDATED", document });
  };

  const refreshSelectedWithHistory = async (
    reusableHistory: V2ScriptVersionListResponse | null = null,
  ): Promise<void> => {
    const state = getState();
    if (!state.workflowId || !state.isOpen) return;
    const workflowId = state.workflowId;
    const request = nextRequestToken();
    dispatch({ type: "SELECTED_REFRESH_STARTED", workflowId, generation: state.generation, requestToken: request });
    handoffQueuedHistoryRefresh(workflowId, state.generation, request);
    try {
      let selected: V2ScriptReadResponse;
      let history: V2ScriptVersionListResponse;
      if (reusableHistory?.workflow_id === workflowId) {
        selected = await api.script(workflowId);
        history = reusableHistory.selected_script_version_id === selected.selected_script_version_id
          ? reusableHistory
          : await api.scriptVersions(workflowId);
      } else {
        [selected, history] = await Promise.all([api.script(workflowId), api.scriptVersions(workflowId)]);
      }
      assertCoherentOpenResponse(workflowId, selected, history);
      if (!isSelectedBundleRequestActive(workflowId, state.generation, request)) return;
      dispatch({
        type: "SELECTED_BUNDLE_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        script: selected.script,
        selectedScriptVersionId: selected.selected_script_version_id,
        versions: history.versions,
      });
      await flushQueuedHistoryRefresh(workflowId, state.generation, request);
    } catch (error) {
      if (!isSelectedBundleRequestActive(workflowId, state.generation, request)) return;
      dispatch({
        type: "SELECTED_BUNDLE_FAILED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        error: toRequestError("refresh_selected", error),
      });
      clearQueuedHistoryRefresh({ workflowId, generation: state.generation, ownerRequestToken: request });
    }
  };

  const refreshSelected = async (): Promise<void> => {
    await refreshSelectedWithHistory();
  };

  const refreshHistoryResponse = async (): Promise<V2ScriptVersionListResponse | null> => {
    const state = getState();
    if (!state.workflowId || !state.isOpen) return null;
    if (isInitialOpenPending(state)) {
      await queueHistoryRefresh(state.workflowId, state.generation);
      return null;
    }
    const workflowId = state.workflowId;
    const request = nextRequestToken();
    dispatch({ type: "HISTORY_REFRESH_STARTED", workflowId, generation: state.generation, requestToken: request });
    try {
      const response = await api.scriptVersions(workflowId);
      if (response.workflow_id !== workflowId) throw new Error("Screenplay history response belongs to a different workflow.");
      if (!isHistoryRequestActive(workflowId, state.generation, request)) return null;
      dispatch({
        type: "HISTORY_REFRESH_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        selectedScriptVersionId: response.selected_script_version_id,
        versions: response.versions,
      });
      return response;
    } catch (error) {
      if (!isHistoryRequestActive(workflowId, state.generation, request)) return null;
      dispatch({
        type: "HISTORY_REFRESH_FAILED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        error: toRequestError("refresh_history", error),
      });
      return null;
    }
  };

  const refreshHistory = async (): Promise<void> => {
    await refreshHistoryResponse();
  };

  const flushQueuedSynchronizationPlans = async (
    workflowId: string,
    generation: number,
  ): Promise<{ refreshedSelected: boolean }> => {
    const queued = queuedSynchronizationPlans.filter((entry) =>
      entry.workflowId === workflowId && entry.generation === generation);
    queuedSynchronizationPlans = queuedSynchronizationPlans.filter((entry) =>
      entry.workflowId !== workflowId || entry.generation !== generation);
    let refreshedSelected = false;
    for (const entry of queued) {
      refreshedSelected ||= entry.plan.refreshSelectedScreenplay;
      if (!isSessionActive(workflowId, generation)) break;
      await coordinateSynchronizationRefresh(workflowId, entry.plan);
    }
    return { refreshedSelected };
  };

  const confirm = async (): Promise<void> => {
    const state = getState();
    if (!state.workflowId || !state.draftBaseScriptVersionId || !state.draft || !state.isOpen) return;
    const validationErrors = validateEditableScript(state.draft);
    if (validationErrors.length > 0) {
      dispatch({ type: "VALIDATION_FAILED", validationErrors });
      return;
    }

    const workflowId = state.workflowId;
    const baseScriptVersionId = state.draftBaseScriptVersionId;
    const document = structuredClone(state.draft);
    const request = nextRequestToken();
    dispatch({ type: "CONFIRM_STARTED", workflowId, generation: state.generation, requestToken: request });
    try {
      const response = await api.confirmScript(workflowId, {
        base_script_version_id: baseScriptVersionId,
        document,
        source_action: "script_editor_confirm",
      });
      assertWorkflowResponse(workflowId, response);
      if (!isSelectedRequestActive(workflowId, state.generation, request)) return;
      dispatch({
        type: "CONFIRM_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        script: response.script,
        selectedScriptVersionId: response.selected_script_version_id,
        structuralDiff: response.structural_diff,
      });
      await coordinateSynchronizationRefresh(
        workflowId,
        createV2LocalSynchronizationRefreshPlan(response.selected_script_version_id, response.structural_diff, response.linked_context),
        { localSelection: true, linkedContext: response.linked_context },
      );
      await flushQueuedSynchronizationPlans(workflowId, state.generation);
      if (!isSelectedRequestActive(workflowId, state.generation, request)) return;
      await notifyRuntimeRefresh(workflowId, response.linked_context, refreshRuntime);
    } catch (error) {
      if (!isSelectedRequestActive(workflowId, state.generation, request)) return;
      if (isScriptVersionConflict(error)) {
        dispatch({
          type: "CONFLICT_DETECTED",
          workflowId,
          generation: state.generation,
          requestToken: request,
          failedBaseScriptVersionId: baseScriptVersionId,
          localDraft: document,
          message: error.message,
        });
        const queued = await flushQueuedSynchronizationPlans(workflowId, state.generation);
        if (!queued.refreshedSelected) await refreshSelected();
        return;
      }
      dispatch({
        type: "CONFIRM_FAILED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        error: toRequestError("confirm", error),
      });
      await flushQueuedSynchronizationPlans(workflowId, state.generation);
    }
  };

  const selectVersion = async (versionId: string): Promise<void> => {
    const state = getState();
    if (!state.workflowId || !state.selectedScriptVersionId || !state.isOpen) return;
    const workflowId = state.workflowId;
    const request = nextRequestToken();
    dispatch({ type: "SELECT_STARTED", workflowId, generation: state.generation, requestToken: request });
    try {
      const response = await api.selectScriptVersion(workflowId, versionId, {
        base_selected_script_version_id: state.selectedScriptVersionId,
      });
      assertWorkflowResponse(workflowId, response);
      if (!isSelectedRequestActive(workflowId, state.generation, request)) return;
      dispatch({
        type: "SELECT_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        script: response.script,
        selectedScriptVersionId: response.selected_script_version_id,
        structuralDiff: response.structural_diff,
      });
      await coordinateSynchronizationRefresh(
        workflowId,
        createV2LocalSynchronizationRefreshPlan(response.selected_script_version_id, response.structural_diff, response.linked_context),
        { localSelection: true, linkedContext: response.linked_context },
      );
      await flushQueuedSynchronizationPlans(workflowId, state.generation);
      if (!isSelectedRequestActive(workflowId, state.generation, request)) return;
      await notifyRuntimeRefresh(workflowId, response.linked_context, refreshRuntime);
    } catch (error) {
      if (!isSelectedRequestActive(workflowId, state.generation, request)) return;
      dispatch({ type: "SELECT_FAILED", workflowId, generation: state.generation, requestToken: request, error: toRequestError("select", error) });
      await flushQueuedSynchronizationPlans(workflowId, state.generation);
    }
  };

  const close = (): "closed" | "confirmation_required" => {
    dispatch({ type: "CLOSE_REQUESTED" });
    if (getState().closeState === "confirmation_required") return "confirmation_required";
    finishClose();
    return "closed";
  };

  const cancelClose = (): void => dispatch({ type: "CLOSE_CANCELLED" });
  const finishClose = (): void => {
    if (!getState().isOpen) return;
    clearQueuedHistoryRefresh();
    clearQueuedSynchronizationPlans();
    dispatch({ type: "CLOSE_CONFIRMED", generation: ++sessionGeneration });
  };
  const discardDraftAndClose = (): void => finishClose();
  const keepReviewingLocalDraft = (): void => dispatch({ type: "KEEP_REVIEWING_LOCAL_DRAFT" });
  const discardLocalDraftAndReloadLatest = (): void => dispatch({ type: "DISCARD_LOCAL_DRAFT_AND_RELOAD_LATEST" });

  const handleRuntimeEvents = async (events: WorkflowRuntimeEventV2[]): Promise<void> => {
    const workflowId = events.find((event) => isV2SynchronizationEvent(event.event_type))?.workflow_id;
    if (workflowId) {
      const workflowEvents = events.filter((event) => event.workflow_id === workflowId);
      const plan = createV2SynchronizationRefreshPlan(workflowEvents);
      const state = getState();
      if (
        state.workflowId === workflowId
        && state.isOpen
        && hasActiveLocalSelectionOperation(state)
      ) {
        queueSynchronizationPlan(workflowId, state.generation, plan);
        return;
      }
      await coordinateSynchronizationRefresh(workflowId, plan);
      return;
    }
    const openWorkflowId = getState().workflowId;
    if (!openWorkflowId) return;
    const workflowEvents = events.filter((event) => event.workflow_id === openWorkflowId);
    if (workflowEvents.some(isScreenplayRuntimeEvent)) await refreshSelected();
  };

  const coordinateSynchronizationRefresh = async (
    workflowId: string,
    plan: V2SynchronizationRefreshPlan,
    options: { localSelection?: boolean; linkedContext?: V2LinkedContextSummary } = {},
  ) => {
    const state = getState();
    const screenplayOpen = state.isOpen && state.workflowId === workflowId;
    await synchronizationCoordinator.coordinate(workflowId, plan, {
      refreshHistory: screenplayOpen ? refreshHistoryResponse : undefined,
      refreshSelectedScreenplay: screenplayOpen
        ? options.localSelection
          ? async () => { await refreshHistoryResponse(); }
          : refreshSelectedWithHistory
        : undefined,
      refreshWorkflow: refreshSynchronizationWorkflow || refreshWorkflow
        ? (scopes) => refreshSynchronizationWorkflow?.(workflowId, scopes)
          ?? refreshWorkflow?.(workflowId, options.linkedContext ?? linkedContextFromPlan(plan))
        : undefined,
    });
  };

  return {
    open,
    close,
    cancelClose,
    discardDraftAndClose,
    updateDraft,
    confirm,
    selectVersion,
    refreshSelected,
    refreshHistory,
    keepReviewingLocalDraft,
    discardLocalDraftAndReloadLatest,
    handleRuntimeEvents,
  };
}

export function useV2ScreenplayController(options: UseV2ScreenplayControllerOptions = {}): V2ScreenplayController {
  const [state, reactDispatch] = useReducer(screenplayReducer, undefined, createV2ScreenplayState);
  const stateRef = useRef(state);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const runtimeRef = useRef<V2ScreenplayControllerRuntime | null>(null);

  if (!runtimeRef.current) {
    const api: V2ScreenplayApi = {
      script: (...args) => (optionsRef.current.api ?? v2Api).script(...args),
      confirmScript: (...args) => (optionsRef.current.api ?? v2Api).confirmScript(...args),
      scriptVersions: (...args) => (optionsRef.current.api ?? v2Api).scriptVersions(...args),
      selectScriptVersion: (...args) => (optionsRef.current.api ?? v2Api).selectScriptVersion(...args),
    };
    runtimeRef.current = createV2ScreenplayControllerRuntime({
      api,
      getState: () => stateRef.current,
      dispatch: (action) => {
        stateRef.current = screenplayReducer(stateRef.current, action);
        reactDispatch(action);
      },
      refreshWorkflow: (...args) => optionsRef.current.refreshWorkflow?.(...args),
      refreshRuntime: (...args) => optionsRef.current.refreshRuntime?.(...args),
      refreshSynchronizationWorkflow: (...args) => optionsRef.current.refreshSynchronizationWorkflow?.(...args),
      synchronizationCoordinator: options.synchronizationCoordinator,
    });
  }
  stateRef.current = state;

  const runtime = runtimeRef.current;
  return {
    state,
    open: useCallback((workflowId) => runtime.open(workflowId), [runtime]),
    close: useCallback(() => runtime.close(), [runtime]),
    cancelClose: useCallback(() => runtime.cancelClose(), [runtime]),
    discardDraftAndClose: useCallback(() => runtime.discardDraftAndClose(), [runtime]),
    updateDraft: useCallback((update) => runtime.updateDraft(update), [runtime]),
    confirm: useCallback(() => runtime.confirm(), [runtime]),
    selectVersion: useCallback((versionId) => runtime.selectVersion(versionId), [runtime]),
    refreshSelected: useCallback(() => runtime.refreshSelected(), [runtime]),
    refreshHistory: useCallback(() => runtime.refreshHistory(), [runtime]),
    keepReviewingLocalDraft: useCallback(() => runtime.keepReviewingLocalDraft(), [runtime]),
    discardLocalDraftAndReloadLatest: useCallback(() => runtime.discardLocalDraftAndReloadLatest(), [runtime]),
    handleRuntimeEvents: useCallback((events) => runtime.handleRuntimeEvents(events), [runtime]),
  };
}

function assertCoherentOpenResponse(
  workflowId: string,
  selected: V2ScriptReadResponse,
  history: V2ScriptVersionListResponse,
): void {
  assertWorkflowResponse(workflowId, selected);
  if (history.workflow_id !== workflowId) throw new ScreenplaySelectionHistoryConsistencyError("Screenplay history response belongs to a different workflow.");
  if (selected.selected_script_version_id !== history.selected_script_version_id) {
    throw new ScreenplaySelectionHistoryConsistencyError("Screenplay selected script and version history disagree.");
  }
}

function assertWorkflowResponse(workflowId: string, response: V2ScriptReadResponse | V2ScriptConfirmResponse | V2ScriptSelectVersionResponse): void {
  if (response.workflow_id !== workflowId) throw new Error("Screenplay response belongs to a different workflow.");
}

class ScreenplaySelectionHistoryConsistencyError extends Error {
  readonly code = "screenplay_selection_history_mismatch";

  constructor(message: string) {
    super(message);
    this.name = "ScreenplaySelectionHistoryConsistencyError";
  }
}

function toRequestError(operation: ScreenplayRequestError["operation"], error: unknown): ScreenplayRequestError {
  if (error instanceof V2ApiError) {
    return {
      operation,
      message: error.message,
      status: error.status,
      code: error.code,
      details: { ...error.details, violations: error.violations },
    };
  }
  if (error instanceof ScreenplaySelectionHistoryConsistencyError) {
    return { operation, message: error.message, code: error.code };
  }
  return { operation, message: error instanceof Error ? error.message : "Screenplay request failed." };
}

function isScriptVersionConflict(error: unknown): error is V2ApiError {
  return error instanceof V2ApiError && error.status === 409 && error.code === "script_version_conflict";
}

function isScreenplayRuntimeEvent(event: WorkflowRuntimeEventV2): boolean {
  return /(^|[.:_])script([.:_]|$)|screenplay/i.test(event.event_type);
}

function synchronizationPlanAliases(plan: V2SynchronizationRefreshPlan): Set<string> {
  return new Set([
    ...plan.transactionIds.map((id) => `transaction:${id}`),
    ...plan.scriptVersionIds.map((id) => `script:${id}`),
  ]);
}

function setsOverlap(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  for (const value of left) {
    if (right.has(value)) return true;
  }
  return false;
}

function mergeSynchronizationRefreshPlans(
  left: V2SynchronizationRefreshPlan,
  right: V2SynchronizationRefreshPlan,
): V2SynchronizationRefreshPlan {
  const unique = (values: string[]) => Array.from(new Set(values));
  return {
    isSynchronizationBatch: left.isSynchronizationBatch || right.isSynchronizationBatch,
    refreshScreenplayHistory: left.refreshScreenplayHistory || right.refreshScreenplayHistory,
    refreshSelectedScreenplay: left.refreshSelectedScreenplay || right.refreshSelectedScreenplay,
    refreshWorkflow: left.refreshWorkflow || right.refreshWorkflow,
    refreshWorkflowStructure: left.refreshWorkflowStructure || right.refreshWorkflowStructure,
    refreshSlotPrompts: left.refreshSlotPrompts || right.refreshSlotPrompts,
    refreshReferences: left.refreshReferences || right.refreshReferences,
    refreshAssets: left.refreshAssets || right.refreshAssets,
    nodeIds: unique([...left.nodeIds, ...right.nodeIds]),
    itemIds: unique([...left.itemIds, ...right.itemIds]),
    slotIds: unique([...left.slotIds, ...right.slotIds]),
    transactionIds: unique([...left.transactionIds, ...right.transactionIds]),
    scriptVersionIds: unique([...left.scriptVersionIds, ...right.scriptVersionIds]),
  };
}

async function notifyRuntimeRefresh(
  workflowId: string,
  linkedContext: V2LinkedContextSummary,
  refreshRuntime: V2ScreenplayControllerCallbacks["refreshRuntime"],
): Promise<void> {
  await Promise.allSettled([refreshRuntime?.(workflowId, linkedContext)]);
}

function linkedContextFromPlan(plan: V2SynchronizationRefreshPlan): V2LinkedContextSummary {
  return {
    updated_node_ids: plan.nodeIds,
    updated_item_ids: plan.itemIds,
    updated_slot_ids: plan.slotIds,
    updated_fields: [],
    selected_asset_versions_changed: false,
    provider_execution_started: false,
    refresh: [
      ...(plan.refreshWorkflow || plan.refreshWorkflowStructure ? ["workflow"] : []),
      ...(plan.refreshSlotPrompts ? ["slot_prompts"] : []),
      ...(plan.refreshReferences ? ["references"] : []),
      ...(plan.refreshAssets ? ["assets"] : []),
    ],
  };
}
