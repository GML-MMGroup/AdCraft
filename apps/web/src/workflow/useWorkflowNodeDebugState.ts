import { useCallback, useEffect, useRef, useState } from "react";
import type { ResolvedNodeInputs, WorkflowNodeVersion } from "../types";

export type DebugLoadStatus = "idle" | "loading" | "loaded" | "error";

export type NodeDebugLoadState = {
  resolved: DebugLoadStatus;
  versions: DebugLoadStatus;
  resolvedError?: string | null;
  versionsError?: string | null;
};

type NodeDebugCacheEntry = {
  resolvedInputs?: ResolvedNodeInputs | null;
  versions?: WorkflowNodeVersion[];
};

type WorkflowNodeVersionResponse = {
  versions?: WorkflowNodeVersion[];
};

type WorkflowNodeDebugStateOptions = {
  workflowId?: string | null;
  selectedNodeId: string;
  isBackendWorkflowNode: (nodeId: string) => boolean;
  isCurrentWorkflow: (workflowId: string) => boolean;
  loadResolvedInputs: (workflowId: string, nodeId: string) => Promise<ResolvedNodeInputs | null | undefined>;
  loadNodeVersions: (workflowId: string, nodeId: string) => Promise<WorkflowNodeVersionResponse>;
};

const emptyNodeDebugLoadState: NodeDebugLoadState = {
  resolved: "idle",
  versions: "idle",
  resolvedError: null,
  versionsError: null,
};

export function useWorkflowNodeDebugState({
  workflowId,
  selectedNodeId,
  isBackendWorkflowNode,
  isCurrentWorkflow,
  loadResolvedInputs,
  loadNodeVersions,
}: WorkflowNodeDebugStateOptions) {
  const nodeDebugCache = useRef<Map<string, NodeDebugCacheEntry>>(new Map());
  const [selectedResolvedInputs, setSelectedResolvedInputs] = useState<ResolvedNodeInputs | null>(null);
  const [nodeVersions, setNodeVersions] = useState<WorkflowNodeVersion[]>([]);
  const [debugLoadState, setDebugLoadState] = useState<NodeDebugLoadState>(emptyNodeDebugLoadState);

  const nodeDebugCacheKey = useCallback(
    (nodeId = selectedNodeId) => (workflowId && nodeId ? `${workflowId}:${nodeId}` : ""),
    [selectedNodeId, workflowId],
  );

  const getNodeDebugCacheEntry = useCallback(
    (nodeId = selectedNodeId) => {
      const key = nodeDebugCacheKey(nodeId);
      return key ? nodeDebugCache.current.get(key) : undefined;
    },
    [nodeDebugCacheKey, selectedNodeId],
  );

  const mergeNodeDebugCache = useCallback(
    (nodeId: string, patch: NodeDebugCacheEntry) => {
      const key = nodeDebugCacheKey(nodeId);
      if (!key) return;
      nodeDebugCache.current.set(key, {
        ...(nodeDebugCache.current.get(key) ?? {}),
        ...patch,
      });
    },
    [nodeDebugCacheKey],
  );

  const invalidateNodeDebugCache = useCallback(
    (nodeId = selectedNodeId) => {
      const key = nodeDebugCacheKey(nodeId);
      if (key) nodeDebugCache.current.delete(key);
    },
    [nodeDebugCacheKey, selectedNodeId],
  );

  useEffect(() => {
    const cached = getNodeDebugCacheEntry(selectedNodeId);
    setSelectedResolvedInputs(cached?.resolvedInputs ?? null);
    setNodeVersions(cached?.versions ?? []);
    setDebugLoadState({
      ...emptyNodeDebugLoadState,
      resolved: cached?.resolvedInputs ? "loaded" : "idle",
      versions: cached?.versions ? "loaded" : "idle",
    });
  }, [getNodeDebugCacheEntry, selectedNodeId, workflowId]);

  const refreshNodeVersions = useCallback(
    async (nodeId = selectedNodeId, options: { force?: boolean } = {}) => {
      if (!workflowId || !nodeId) return;
      const requestWorkflowId = workflowId;
      if (!isBackendWorkflowNode(nodeId)) {
        setNodeVersions([]);
        setDebugLoadState((current) => ({ ...current, versions: "idle", versionsError: null }));
        return;
      }
      const cached = getNodeDebugCacheEntry(nodeId);
      if (!options.force && cached?.versions) {
        setNodeVersions(cached.versions);
        setDebugLoadState((current) => ({ ...current, versions: "loaded", versionsError: null }));
        return cached.versions;
      }
      setDebugLoadState((current) => ({ ...current, versions: "loading", versionsError: null }));
      try {
        const result = await loadNodeVersions(requestWorkflowId, nodeId);
        if (!isCurrentWorkflow(requestWorkflowId)) return;
        const versions = result.versions ?? [];
        mergeNodeDebugCache(nodeId, { versions });
        setNodeVersions(versions);
        setDebugLoadState((current) => ({ ...current, versions: "loaded", versionsError: null }));
        return versions;
      } catch (error) {
        if (!isCurrentWorkflow(requestWorkflowId)) return;
        setNodeVersions([]);
        setDebugLoadState((current) => ({
          ...current,
          versions: "error",
          versionsError: error instanceof Error ? error.message : "Version history request failed",
        }));
      }
    },
    [getNodeDebugCacheEntry, isBackendWorkflowNode, isCurrentWorkflow, loadNodeVersions, mergeNodeDebugCache, selectedNodeId, workflowId],
  );

  const ensureNodeVersions = useCallback(
    async (nodeId = selectedNodeId) => {
      const cached = getNodeDebugCacheEntry(nodeId);
      if (cached?.versions) {
        setNodeVersions(cached.versions);
        setDebugLoadState((current) => ({ ...current, versions: "loaded", versionsError: null }));
        return cached.versions;
      }
      return refreshNodeVersions(nodeId);
    },
    [getNodeDebugCacheEntry, refreshNodeVersions, selectedNodeId],
  );

  const refreshSelectedResolvedInputs = useCallback(
    async (nodeId = selectedNodeId, options: { force?: boolean } = {}) => {
      if (!workflowId || !nodeId || !isBackendWorkflowNode(nodeId)) {
        setSelectedResolvedInputs(null);
        setDebugLoadState((current) => ({ ...current, resolved: "idle", resolvedError: null }));
        return null;
      }
      const requestWorkflowId = workflowId;
      const cached = getNodeDebugCacheEntry(nodeId);
      if (!options.force && cached?.resolvedInputs) {
        setSelectedResolvedInputs(cached.resolvedInputs);
        setDebugLoadState((current) => ({ ...current, resolved: "loaded", resolvedError: null }));
        return cached.resolvedInputs;
      }
      setDebugLoadState((current) => ({ ...current, resolved: "loading", resolvedError: null }));
      try {
        const result = await loadResolvedInputs(requestWorkflowId, nodeId);
        if (!isCurrentWorkflow(requestWorkflowId)) return null;
        if (!result) return null;
        mergeNodeDebugCache(nodeId, { resolvedInputs: result });
        setSelectedResolvedInputs(result);
        setDebugLoadState((current) => ({ ...current, resolved: "loaded", resolvedError: null }));
        return result;
      } catch (error) {
        if (!isCurrentWorkflow(requestWorkflowId)) return null;
        setDebugLoadState((current) => ({
          ...current,
          resolved: "error",
          resolvedError: error instanceof Error ? error.message : "Resolved inputs request failed",
        }));
        return null;
      }
    },
    [getNodeDebugCacheEntry, isBackendWorkflowNode, isCurrentWorkflow, loadResolvedInputs, mergeNodeDebugCache, selectedNodeId, workflowId],
  );

  const ensureSelectedResolvedInputs = useCallback(
    async (nodeId = selectedNodeId) => {
      const cached = getNodeDebugCacheEntry(nodeId);
      if (cached?.resolvedInputs) {
        setSelectedResolvedInputs(cached.resolvedInputs);
        setDebugLoadState((current) => ({ ...current, resolved: "loaded", resolvedError: null }));
        return cached.resolvedInputs;
      }
      return refreshSelectedResolvedInputs(nodeId);
    },
    [getNodeDebugCacheEntry, refreshSelectedResolvedInputs, selectedNodeId],
  );

  return {
    selectedResolvedInputs,
    setSelectedResolvedInputs,
    nodeVersions,
    setNodeVersions,
    debugLoadState,
    ensureNodeVersions,
    refreshNodeVersions,
    ensureSelectedResolvedInputs,
    refreshSelectedResolvedInputs,
    invalidateNodeDebugCache,
  };
}
