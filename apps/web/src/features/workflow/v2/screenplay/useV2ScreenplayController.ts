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
import { validateEditableScript } from "./screenplayModel.ts";
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
};

export type V2ScreenplayControllerRuntimeOptions = V2ScreenplayControllerCallbacks & {
  api: V2ScreenplayApi;
  getState: () => V2ScreenplayState;
  dispatch: (action: ScreenplayReducerAction) => void;
};

export type UseV2ScreenplayControllerOptions = V2ScreenplayControllerCallbacks & {
  api?: V2ScreenplayApi;
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
}: V2ScreenplayControllerRuntimeOptions): V2ScreenplayControllerRuntime {
  let generation = 0;
  let requestToken = 0;

  const nextRequestToken = () => {
    requestToken += 1;
    return requestToken;
  };

  const open = async (workflowId: string): Promise<void> => {
    generation += 1;
    const request = nextRequestToken();
    dispatch({ type: "OPEN_STARTED", workflowId, generation, requestToken: request });
    try {
      const [selected, history] = await Promise.all([api.script(workflowId), api.scriptVersions(workflowId)]);
      assertCoherentOpenResponse(workflowId, selected, history);
      dispatch({
        type: "OPEN_SUCCEEDED",
        workflowId,
        generation,
        requestToken: request,
        script: selected.script,
        selectedScriptVersionId: selected.selected_script_version_id,
        versions: history.versions,
      });
    } catch (error) {
      dispatch({ type: "OPEN_FAILED", workflowId, generation, requestToken: request, error: toRequestError("open", error) });
    }
  };

  const updateDraft = (update: V2EditableScriptDocument | ScreenplayDraftUpdater): void => {
    const current = getState().draft;
    if (!current) return;
    const workingCopy = structuredClone(current);
    const document = typeof update === "function" ? update(workingCopy) : update;
    dispatch({ type: "DRAFT_UPDATED", document });
  };

  const refreshSelected = async (): Promise<void> => {
    const state = getState();
    if (!state.workflowId || !state.isOpen) return;
    const workflowId = state.workflowId;
    const request = nextRequestToken();
    dispatch({ type: "SELECTED_REFRESH_STARTED", workflowId, generation: state.generation, requestToken: request });
    try {
      const response = await api.script(workflowId);
      assertWorkflowResponse(workflowId, response);
      dispatch({
        type: "SELECTED_REFRESH_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        script: response.script,
        selectedScriptVersionId: response.selected_script_version_id,
      });
    } catch (error) {
      dispatch({
        type: "SELECTED_REFRESH_FAILED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        error: toRequestError("refresh_selected", error),
      });
    }
  };

  const refreshHistory = async (): Promise<void> => {
    const state = getState();
    if (!state.workflowId || !state.isOpen) return;
    const workflowId = state.workflowId;
    const request = nextRequestToken();
    dispatch({ type: "HISTORY_REFRESH_STARTED", workflowId, generation: state.generation, requestToken: request });
    try {
      const response = await api.scriptVersions(workflowId);
      if (response.workflow_id !== workflowId) throw new Error("Screenplay history response belongs to a different workflow.");
      dispatch({
        type: "HISTORY_REFRESH_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        versions: response.versions,
      });
    } catch (error) {
      dispatch({
        type: "HISTORY_REFRESH_FAILED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        error: toRequestError("refresh_history", error),
      });
    }
  };

  const confirm = async (): Promise<void> => {
    const state = getState();
    if (!state.workflowId || !state.selectedScriptVersionId || !state.draft || !state.isOpen) return;
    const validationErrors = validateEditableScript(state.draft);
    if (validationErrors.length > 0) {
      dispatch({ type: "VALIDATION_FAILED", validationErrors });
      return;
    }

    const workflowId = state.workflowId;
    const baseScriptVersionId = state.selectedScriptVersionId;
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
      dispatch({
        type: "CONFIRM_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        script: response.script,
        selectedScriptVersionId: response.selected_script_version_id,
        structuralDiff: response.structural_diff,
      });
      await refreshHistory();
      await notifyLinkedRefresh(workflowId, response.linked_context, refreshWorkflow, refreshRuntime);
    } catch (error) {
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
        await Promise.all([refreshSelected(), refreshHistory()]);
        return;
      }
      dispatch({
        type: "CONFIRM_FAILED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        error: toRequestError("confirm", error),
      });
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
      dispatch({
        type: "SELECT_SUCCEEDED",
        workflowId,
        generation: state.generation,
        requestToken: request,
        script: response.script,
        selectedScriptVersionId: response.selected_script_version_id,
        structuralDiff: response.structural_diff,
      });
      await refreshHistory();
      await notifyLinkedRefresh(workflowId, response.linked_context, refreshWorkflow, refreshRuntime);
    } catch (error) {
      dispatch({ type: "SELECT_FAILED", workflowId, generation: state.generation, requestToken: request, error: toRequestError("select", error) });
    }
  };

  const close = (): "closed" | "confirmation_required" => {
    dispatch({ type: "CLOSE_REQUESTED" });
    return getState().closeState === "confirmation_required" ? "confirmation_required" : "closed";
  };

  const cancelClose = (): void => dispatch({ type: "CLOSE_CANCELLED" });
  const discardDraftAndClose = (): void => dispatch({ type: "CLOSE_CONFIRMED" });
  const keepReviewingLocalDraft = (): void => dispatch({ type: "KEEP_REVIEWING_LOCAL_DRAFT" });
  const discardLocalDraftAndReloadLatest = (): void => dispatch({ type: "DISCARD_LOCAL_DRAFT_AND_RELOAD_LATEST" });

  const handleRuntimeEvents = async (events: WorkflowRuntimeEventV2[]): Promise<void> => {
    const workflowId = getState().workflowId;
    if (!workflowId || !events.some((event) => event.workflow_id === workflowId && isScreenplayRuntimeEvent(event))) return;
    await Promise.all([refreshSelected(), refreshHistory()]);
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
  if (history.workflow_id !== workflowId) throw new Error("Screenplay history response belongs to a different workflow.");
  if (selected.selected_script_version_id !== history.selected_script_version_id) {
    throw new Error("Screenplay selected script and version history disagree.");
  }
}

function assertWorkflowResponse(workflowId: string, response: V2ScriptReadResponse | V2ScriptConfirmResponse | V2ScriptSelectVersionResponse): void {
  if (response.workflow_id !== workflowId) throw new Error("Screenplay response belongs to a different workflow.");
}

function toRequestError(operation: ScreenplayRequestError["operation"], error: unknown): ScreenplayRequestError {
  if (error instanceof V2ApiError) {
    return { operation, message: error.message, status: error.status, code: error.code, details: error.details };
  }
  return { operation, message: error instanceof Error ? error.message : "Screenplay request failed." };
}

function isScriptVersionConflict(error: unknown): error is V2ApiError {
  return error instanceof V2ApiError && error.status === 409 && error.code === "script_version_conflict";
}

function isScreenplayRuntimeEvent(event: WorkflowRuntimeEventV2): boolean {
  return /(^|[.:_])script([.:_]|$)|screenplay/i.test(event.event_type);
}

async function notifyLinkedRefresh(
  workflowId: string,
  linkedContext: V2LinkedContextSummary,
  refreshWorkflow: V2ScreenplayControllerCallbacks["refreshWorkflow"],
  refreshRuntime: V2ScreenplayControllerCallbacks["refreshRuntime"],
): Promise<void> {
  await Promise.allSettled([
    refreshWorkflow?.(workflowId, linkedContext),
    refreshRuntime?.(workflowId, linkedContext),
  ]);
}
