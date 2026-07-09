import type { AssetVersionV2 } from "../../../../types-v2.ts";
import { mergeV2AssetVersions } from "../../../../workflow-v2/assets.ts";

export type WorkflowAssetRefreshRequest = {
  workflowId: string;
  requestId: number;
};

export type WorkflowAssetHydrationState = {
  workflowId: string | null;
  baseAssets: AssetVersionV2[];
  loadedAssets: AssetVersionV2[];
  requestId: number;
  isLoading: boolean;
  lastLoadedAt: string | null;
  lastError: string | null;
};

export function createWorkflowAssetHydrationState(
  workflowId: string | null = null,
  baseAssets: AssetVersionV2[] = [],
): WorkflowAssetHydrationState {
  return {
    workflowId,
    baseAssets,
    loadedAssets: [],
    requestId: 0,
    isLoading: false,
    lastLoadedAt: null,
    lastError: null,
  };
}

export function mergedWorkflowAssetVersions(state: WorkflowAssetHydrationState) {
  return mergeV2AssetVersions(state.baseAssets, state.loadedAssets);
}

export function updateWorkflowAssetBaseAssets(
  state: WorkflowAssetHydrationState,
  workflowId: string | null,
  baseAssets: AssetVersionV2[],
): WorkflowAssetHydrationState {
  if (state.workflowId !== workflowId) {
    return {
      ...createWorkflowAssetHydrationState(workflowId, baseAssets),
      requestId: state.requestId + 1,
    };
  }
  return {
    ...state,
    baseAssets,
  };
}

export function startWorkflowAssetRefresh(
  state: WorkflowAssetHydrationState,
  workflowId: string,
): WorkflowAssetRefreshRequest {
  return {
    workflowId,
    requestId: state.requestId + 1,
  };
}

export function markWorkflowAssetRefreshStarted(
  state: WorkflowAssetHydrationState,
  request: WorkflowAssetRefreshRequest,
): WorkflowAssetHydrationState {
  return {
    ...state,
    workflowId: request.workflowId,
    requestId: request.requestId,
    isLoading: true,
    lastError: null,
  };
}

export function completeWorkflowAssetRefresh(
  state: WorkflowAssetHydrationState,
  request: WorkflowAssetRefreshRequest,
  assets: AssetVersionV2[],
  loadedAt = new Date().toISOString(),
): WorkflowAssetHydrationState {
  if (state.workflowId !== request.workflowId || state.requestId > request.requestId) return state;
  return {
    ...state,
    workflowId: request.workflowId,
    loadedAssets: assets,
    requestId: request.requestId,
    isLoading: false,
    lastLoadedAt: loadedAt,
    lastError: null,
  };
}

export function failWorkflowAssetRefresh(
  state: WorkflowAssetHydrationState,
  request: WorkflowAssetRefreshRequest,
  message: string,
): WorkflowAssetHydrationState {
  if (state.workflowId !== request.workflowId || state.requestId > request.requestId) return state;
  return {
    ...state,
    requestId: request.requestId,
    isLoading: false,
    lastError: message,
  };
}

export function clearWorkflowAssetHydrationForWorkflow(
  state: WorkflowAssetHydrationState,
  nextWorkflowId: string | null,
): WorkflowAssetHydrationState {
  if (state.workflowId === nextWorkflowId) {
    return {
      ...state,
      isLoading: false,
      lastError: null,
    };
  }
  return {
    ...createWorkflowAssetHydrationState(nextWorkflowId, []),
    requestId: state.requestId + 1,
  };
}
