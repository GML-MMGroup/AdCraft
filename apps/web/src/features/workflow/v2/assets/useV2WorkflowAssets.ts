import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AssetVersionV2,
  V2WorkflowAssetFilters,
  WorkflowAssetListResponseV2,
} from "../../../../types-v2.ts";
import { v2AssetById } from "../../../../workflow-v2/assets.ts";
import {
  clearWorkflowAssetHydrationForWorkflow,
  completeWorkflowAssetRefresh,
  createWorkflowAssetHydrationState,
  failWorkflowAssetRefresh,
  markWorkflowAssetRefreshStarted,
  mergedWorkflowAssetVersions,
  startWorkflowAssetRefresh,
  updateWorkflowAssetBaseAssets,
  type WorkflowAssetHydrationState,
} from "./workflowAssetHydration.ts";

export type UseV2WorkflowAssetsOptions = {
  workflowId?: string | null;
  baseAssetVersions?: AssetVersionV2[];
  listWorkflowAssets: (
    workflowId: string,
    filters?: V2WorkflowAssetFilters,
  ) => Promise<WorkflowAssetListResponseV2>;
};

export function useV2WorkflowAssets({
  workflowId,
  baseAssetVersions = [],
  listWorkflowAssets,
}: UseV2WorkflowAssetsOptions) {
  const [state, setState] = useState<WorkflowAssetHydrationState>(() =>
    createWorkflowAssetHydrationState(workflowId ?? null, baseAssetVersions),
  );
  const stateRef = useRef(state);
  const inFlightRefreshRef = useRef<{ key: string; promise: Promise<AssetVersionV2[]> } | null>(null);

  const commitState = useCallback((updater: (current: WorkflowAssetHydrationState) => WorkflowAssetHydrationState) => {
    setState((current) => {
      const next = updater(current);
      stateRef.current = next;
      return next;
    });
  }, []);

  useEffect(() => {
    commitState((current) => updateWorkflowAssetBaseAssets(current, workflowId ?? null, baseAssetVersions));
  }, [baseAssetVersions, commitState, workflowId]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const assetVersions = useMemo(() => mergedWorkflowAssetVersions(state), [state]);
  const assetById = useMemo(() => v2AssetById(assetVersions), [assetVersions]);

  const clearWorkflowAssets = useCallback((nextWorkflowId?: string | null) => {
    commitState((current) => clearWorkflowAssetHydrationForWorkflow(current, nextWorkflowId ?? current.workflowId));
  }, [commitState]);

  const refreshWorkflowAssets = useCallback(
    async (
      reason = "manual",
      overrideWorkflowId?: string | null,
      overrideBaseAssetVersions?: AssetVersionV2[],
    ) => {
      const targetWorkflowId = overrideWorkflowId ?? workflowId;
      if (!targetWorkflowId) return mergedWorkflowAssetVersions(stateRef.current);
      const refreshKey = `${targetWorkflowId}:${reason}`;
      if (inFlightRefreshRef.current?.key === refreshKey) return inFlightRefreshRef.current.promise;

      if (overrideBaseAssetVersions) {
        commitState((current) => updateWorkflowAssetBaseAssets(current, targetWorkflowId, overrideBaseAssetVersions));
      }

      const requestBaseState = overrideBaseAssetVersions
        ? updateWorkflowAssetBaseAssets(stateRef.current, targetWorkflowId, overrideBaseAssetVersions)
        : stateRef.current;
      const request = startWorkflowAssetRefresh(requestBaseState, targetWorkflowId);
      commitState((current) =>
        markWorkflowAssetRefreshStarted(
          overrideBaseAssetVersions ? updateWorkflowAssetBaseAssets(current, targetWorkflowId, overrideBaseAssetVersions) : current,
          request,
        ),
      );

      const refreshPromise = (async () => {
        try {
          const response = await listWorkflowAssets(targetWorkflowId);
          let nextMerged: AssetVersionV2[] = [];
          commitState((current) => {
            const completed = completeWorkflowAssetRefresh(current, request, response.assets);
            nextMerged = mergedWorkflowAssetVersions(completed);
            return completed;
          });
          return nextMerged;
        } catch (error) {
          const message = error instanceof Error ? error.message : `Failed to refresh workflow assets: ${reason}`;
          let fallback: AssetVersionV2[] = [];
          commitState((current) => {
            const failed = failWorkflowAssetRefresh(current, request, message);
            fallback = mergedWorkflowAssetVersions(failed);
            return failed;
          });
          return fallback;
        } finally {
          if (inFlightRefreshRef.current?.key === refreshKey) inFlightRefreshRef.current = null;
        }
      })();
      inFlightRefreshRef.current = { key: refreshKey, promise: refreshPromise };
      return refreshPromise;
    },
    [commitState, listWorkflowAssets, workflowId],
  );

  return {
    assetVersions,
    assetById,
    isLoading: state.isLoading,
    lastLoadedAt: state.lastLoadedAt,
    lastError: state.lastError,
    refreshWorkflowAssets,
    clearWorkflowAssets,
  };
}
