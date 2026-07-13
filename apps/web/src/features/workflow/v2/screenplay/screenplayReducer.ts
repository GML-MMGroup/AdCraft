import type {
  V2EditableScriptDocument,
  V2ScriptPlan,
  V2ScriptStructuralDiff,
  V2ScriptVersionSummary,
} from "../../../../types-v2.ts";
import {
  scriptToEditableDocument,
  type EditableScriptValidationIssue,
} from "./screenplayModel.ts";

export type ScreenplayRequestError = {
  operation: "open" | "confirm" | "select" | "refresh_selected" | "refresh_history";
  message: string;
  status?: number;
  code?: string;
  details?: Record<string, unknown>;
};

export type ScreenplayConflict = {
  status: "unresolved" | "reviewing_local";
  failedBaseScriptVersionId: string;
  localDraft: V2EditableScriptDocument;
  message: string;
  serverScriptVersionId: string | null;
};

export type ScreenplayCloseState = "idle" | "confirmation_required" | "closed";

export type V2ScreenplayState = {
  workflowId: string | null;
  isOpen: boolean;
  isLoading: boolean;
  isSaving: boolean;
  isSelecting: boolean;
  selectedScript: V2ScriptPlan | null;
  selectedScriptVersionId: string | null;
  versions: ReadonlyArray<V2ScriptVersionSummary>;
  draft: V2EditableScriptDocument | null;
  dirty: boolean;
  validationErrors: ReadonlyArray<EditableScriptValidationIssue>;
  requestError: ScreenplayRequestError | null;
  conflict: ScreenplayConflict | null;
  lastStructuralDiff: V2ScriptStructuralDiff | null;
  closeState: ScreenplayCloseState;
  generation: number;
  selectedRequestToken: number | null;
  historyRequestToken: number | null;
  saveRequestToken: number | null;
  selectRequestToken: number | null;
};

export type ScreenplayReducerAction =
  | { type: "OPEN_STARTED"; workflowId: string; generation: number; requestToken: number }
  | { type: "OPEN_SUCCEEDED"; workflowId: string; generation: number; requestToken: number; script: V2ScriptPlan; selectedScriptVersionId: string; versions: V2ScriptVersionSummary[] }
  | { type: "OPEN_FAILED"; workflowId: string; generation: number; requestToken: number; error: ScreenplayRequestError }
  | { type: "DRAFT_UPDATED"; document: V2EditableScriptDocument }
  | { type: "VALIDATION_FAILED"; validationErrors: EditableScriptValidationIssue[] }
  | { type: "CONFIRM_STARTED"; workflowId: string; generation: number; requestToken: number }
  | { type: "CONFIRM_SUCCEEDED"; workflowId: string; generation: number; requestToken: number; script: V2ScriptPlan; selectedScriptVersionId: string; structuralDiff: V2ScriptStructuralDiff }
  | { type: "CONFIRM_FAILED"; workflowId: string; generation: number; requestToken: number; error: ScreenplayRequestError }
  | { type: "CONFLICT_DETECTED"; workflowId: string; generation: number; requestToken: number; failedBaseScriptVersionId: string; localDraft: V2EditableScriptDocument; message: string }
  | { type: "SELECT_STARTED"; workflowId: string; generation: number; requestToken: number }
  | { type: "SELECT_SUCCEEDED"; workflowId: string; generation: number; requestToken: number; script: V2ScriptPlan; selectedScriptVersionId: string; structuralDiff: V2ScriptStructuralDiff }
  | { type: "SELECT_FAILED"; workflowId: string; generation: number; requestToken: number; error: ScreenplayRequestError }
  | { type: "SELECTED_REFRESH_STARTED"; workflowId: string; generation: number; requestToken: number }
  | { type: "SELECTED_REFRESH_SUCCEEDED"; workflowId: string; generation: number; requestToken: number; script: V2ScriptPlan; selectedScriptVersionId: string }
  | { type: "SELECTED_REFRESH_FAILED"; workflowId: string; generation: number; requestToken: number; error: ScreenplayRequestError }
  | { type: "HISTORY_REFRESH_STARTED"; workflowId: string; generation: number; requestToken: number }
  | { type: "HISTORY_REFRESH_SUCCEEDED"; workflowId: string; generation: number; requestToken: number; versions: V2ScriptVersionSummary[] }
  | { type: "HISTORY_REFRESH_FAILED"; workflowId: string; generation: number; requestToken: number; error: ScreenplayRequestError }
  | { type: "KEEP_REVIEWING_LOCAL_DRAFT" }
  | { type: "DISCARD_LOCAL_DRAFT_AND_RELOAD_LATEST" }
  | { type: "CLOSE_REQUESTED" }
  | { type: "CLOSE_CANCELLED" }
  | { type: "CLOSE_CONFIRMED" };

export function createV2ScreenplayState(): V2ScreenplayState {
  return {
    workflowId: null,
    isOpen: false,
    isLoading: false,
    isSaving: false,
    isSelecting: false,
    selectedScript: null,
    selectedScriptVersionId: null,
    versions: freezeVersions([]),
    draft: null,
    dirty: false,
    validationErrors: [],
    requestError: null,
    conflict: null,
    lastStructuralDiff: null,
    closeState: "idle",
    generation: 0,
    selectedRequestToken: null,
    historyRequestToken: null,
    saveRequestToken: null,
    selectRequestToken: null,
  };
}

export function screenplayReducer(state: V2ScreenplayState, action: ScreenplayReducerAction): V2ScreenplayState {
  switch (action.type) {
    case "OPEN_STARTED":
      return {
        ...createV2ScreenplayState(),
        workflowId: action.workflowId,
        isOpen: true,
        isLoading: true,
        generation: action.generation,
        selectedRequestToken: action.requestToken,
        historyRequestToken: action.requestToken,
      };
    case "OPEN_SUCCEEDED":
      if (!matchesOpenRequest(state, action)) return state;
      return adoptServerScript({
        ...state,
        isLoading: false,
        selectedRequestToken: null,
        historyRequestToken: null,
        requestError: null,
        versions: freezeVersions(action.versions),
      }, action.script, action.selectedScriptVersionId, true);
    case "OPEN_FAILED":
      if (!matchesOpenRequest(state, action)) return state;
      return {
        ...state,
        isLoading: false,
        selectedRequestToken: null,
        historyRequestToken: null,
        requestError: action.error,
      };
    case "DRAFT_UPDATED":
      if (!state.isOpen) return state;
      return {
        ...state,
        draft: cloneDocument(action.document),
        dirty: true,
        validationErrors: [],
        requestError: null,
        closeState: "idle",
      };
    case "VALIDATION_FAILED":
      return {
        ...state,
        validationErrors: action.validationErrors.map((issue) => ({ ...issue })),
        requestError: null,
      };
    case "CONFIRM_STARTED":
      if (!matchesWorkflowAndGeneration(state, action)) return state;
      return { ...state, isSaving: true, saveRequestToken: action.requestToken, requestError: null, validationErrors: [] };
    case "CONFIRM_SUCCEEDED":
      if (!matchesSaveRequest(state, action)) return state;
      return adoptServerScript({
        ...state,
        isSaving: false,
        saveRequestToken: null,
        dirty: false,
        validationErrors: [],
        requestError: null,
        conflict: null,
        lastStructuralDiff: action.structuralDiff,
      }, action.script, action.selectedScriptVersionId, true);
    case "CONFIRM_FAILED":
      if (!matchesSaveRequest(state, action)) return state;
      return { ...state, isSaving: false, saveRequestToken: null, requestError: action.error };
    case "CONFLICT_DETECTED":
      if (!matchesSaveRequest(state, action)) return state;
      return {
        ...state,
        isSaving: false,
        saveRequestToken: null,
        conflict: {
          status: "unresolved",
          failedBaseScriptVersionId: action.failedBaseScriptVersionId,
          localDraft: cloneDocument(action.localDraft),
          message: action.message,
          serverScriptVersionId: state.selectedScriptVersionId,
        },
      };
    case "SELECT_STARTED":
      if (!matchesWorkflowAndGeneration(state, action)) return state;
      return { ...state, isSelecting: true, selectRequestToken: action.requestToken, requestError: null };
    case "SELECT_SUCCEEDED":
      if (!matchesSelectRequest(state, action)) return state;
      return adoptServerScript({
        ...state,
        isSelecting: false,
        selectRequestToken: null,
        dirty: false,
        validationErrors: [],
        requestError: null,
        conflict: null,
        lastStructuralDiff: action.structuralDiff,
      }, action.script, action.selectedScriptVersionId, true);
    case "SELECT_FAILED":
      if (!matchesSelectRequest(state, action)) return state;
      return { ...state, isSelecting: false, selectRequestToken: null, requestError: action.error };
    case "SELECTED_REFRESH_STARTED":
      if (!matchesWorkflowAndGeneration(state, action)) return state;
      return { ...state, isLoading: true, selectedRequestToken: action.requestToken, requestError: null };
    case "SELECTED_REFRESH_SUCCEEDED":
      if (!matchesSelectedRefreshRequest(state, action)) return state;
      return adoptServerScript({
        ...state,
        isLoading: false,
        selectedRequestToken: null,
        requestError: null,
      }, action.script, action.selectedScriptVersionId, !state.dirty && !state.conflict);
    case "SELECTED_REFRESH_FAILED":
      if (!matchesSelectedRefreshRequest(state, action)) return state;
      return { ...state, isLoading: false, selectedRequestToken: null, requestError: action.error };
    case "HISTORY_REFRESH_STARTED":
      if (!matchesWorkflowAndGeneration(state, action)) return state;
      return { ...state, isLoading: true, historyRequestToken: action.requestToken, requestError: null };
    case "HISTORY_REFRESH_SUCCEEDED":
      if (!matchesHistoryRefreshRequest(state, action)) return state;
      return { ...state, isLoading: false, historyRequestToken: null, requestError: null, versions: freezeVersions(action.versions) };
    case "HISTORY_REFRESH_FAILED":
      if (!matchesHistoryRefreshRequest(state, action)) return state;
      return { ...state, isLoading: false, historyRequestToken: null, requestError: action.error };
    case "KEEP_REVIEWING_LOCAL_DRAFT":
      if (!state.conflict) return state;
      return { ...state, conflict: { ...state.conflict, status: "reviewing_local" } };
    case "DISCARD_LOCAL_DRAFT_AND_RELOAD_LATEST":
      if (!state.conflict || !state.selectedScript) return state;
      return {
        ...state,
        draft: scriptToEditableDocument(state.selectedScript),
        dirty: false,
        validationErrors: [],
        requestError: null,
        conflict: null,
        closeState: "idle",
      };
    case "CLOSE_REQUESTED":
      if (!state.isOpen) return state;
      return state.dirty
        ? { ...state, closeState: "confirmation_required" }
        : { ...state, isOpen: false, closeState: "closed" };
    case "CLOSE_CANCELLED":
      return state.closeState === "confirmation_required" ? { ...state, closeState: "idle" } : state;
    case "CLOSE_CONFIRMED":
      if (!state.isOpen) return state;
      return {
        ...state,
        isOpen: false,
        closeState: "closed",
        draft: state.selectedScript ? scriptToEditableDocument(state.selectedScript) : state.draft,
        dirty: false,
        validationErrors: [],
        conflict: null,
      };
  }
}

function adoptServerScript(
  state: V2ScreenplayState,
  script: V2ScriptPlan,
  selectedScriptVersionId: string,
  replaceDraft: boolean,
): V2ScreenplayState {
  const conflict = state.conflict
    ? { ...state.conflict, serverScriptVersionId: selectedScriptVersionId }
    : null;
  return {
    ...state,
    selectedScript: script,
    selectedScriptVersionId,
    draft: replaceDraft ? scriptToEditableDocument(script) : state.draft,
    conflict,
  };
}

function freezeVersions(versions: V2ScriptVersionSummary[]): ReadonlyArray<V2ScriptVersionSummary> {
  return Object.freeze(versions.map((version) => Object.freeze({
    ...version,
    structural_diff_summary: Object.freeze({ ...version.structural_diff_summary }),
  })));
}

function cloneDocument(document: V2EditableScriptDocument): V2EditableScriptDocument {
  return structuredClone(document);
}

function matchesWorkflowAndGeneration(
  state: V2ScreenplayState,
  action: { workflowId: string; generation: number },
): boolean {
  return state.workflowId === action.workflowId && state.generation === action.generation;
}

function matchesOpenRequest(
  state: V2ScreenplayState,
  action: { workflowId: string; generation: number; requestToken: number },
): boolean {
  return matchesWorkflowAndGeneration(state, action)
    && state.selectedRequestToken === action.requestToken
    && state.historyRequestToken === action.requestToken;
}

function matchesSaveRequest(
  state: V2ScreenplayState,
  action: { workflowId: string; generation: number; requestToken: number },
): boolean {
  return matchesWorkflowAndGeneration(state, action) && state.saveRequestToken === action.requestToken;
}

function matchesSelectRequest(
  state: V2ScreenplayState,
  action: { workflowId: string; generation: number; requestToken: number },
): boolean {
  return matchesWorkflowAndGeneration(state, action) && state.selectRequestToken === action.requestToken;
}

function matchesSelectedRefreshRequest(
  state: V2ScreenplayState,
  action: { workflowId: string; generation: number; requestToken: number },
): boolean {
  return matchesWorkflowAndGeneration(state, action) && state.selectedRequestToken === action.requestToken;
}

function matchesHistoryRefreshRequest(
  state: V2ScreenplayState,
  action: { workflowId: string; generation: number; requestToken: number },
): boolean {
  return matchesWorkflowAndGeneration(state, action) && state.historyRequestToken === action.requestToken;
}
