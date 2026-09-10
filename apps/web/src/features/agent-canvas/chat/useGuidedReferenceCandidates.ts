import { useCallback, useEffect, useRef, useState } from "react";

import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import type {
  GuidedReferenceCandidateScopeV2,
  GuidedReferenceCandidateV2,
  GuidedReferenceKindV1,
} from "../../../types-v2.ts";

export interface UseGuidedReferenceCandidatesOptions {
  workflowId: string;
  referenceKind: GuidedReferenceKindV1;
  scope: GuidedReferenceCandidateScopeV2;
  query?: string;
  enabled?: boolean;
}

export interface UseGuidedReferenceCandidatesResult {
  items: GuidedReferenceCandidateV2[];
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  hasMore: boolean;
  retry: () => Promise<void>;
  loadMore: () => Promise<void>;
}

function readableError(error: unknown): string {
  if (isV2ApiError(error)) {
    return error.message || error.code || "Unable to load reference candidates.";
  }
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Unable to load reference candidates.";
}

export function useGuidedReferenceCandidates({
  workflowId,
  referenceKind,
  scope,
  query = "",
  enabled = true,
}: UseGuidedReferenceCandidatesOptions): UseGuidedReferenceCandidatesResult {
  const [items, setItems] = useState<GuidedReferenceCandidateV2[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async (cursor: string | null, append: boolean) => {
    const requestId = ++requestIdRef.current;
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError(null);
    try {
      const response = await agentCanvasApi.listAgentCanvasReferenceCandidates(workflowId, {
        referenceKind,
        scope,
        cursor,
        query,
        signal: controller.signal,
      });
      if (requestId !== requestIdRef.current) return;
      setItems((current) => append ? [...current, ...response.items] : response.items);
      setNextCursor(response.next_cursor);
    } catch (loadError) {
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;
      setError(readableError(loadError));
    } finally {
      if (requestId === requestIdRef.current) {
        if (append) setLoadingMore(false);
        else setLoading(false);
      }
    }
  }, [query, referenceKind, scope, workflowId]);

  useEffect(() => {
    requestIdRef.current += 1;
    abortControllerRef.current?.abort();
    setItems([]);
    setNextCursor(null);
    setError(null);
    if (!enabled) {
      setLoading(false);
      setLoadingMore(false);
      return undefined;
    }
    void load(null, false);
    return () => {
      requestIdRef.current += 1;
      abortControllerRef.current?.abort();
    };
  }, [enabled, load]);

  const retry = useCallback(() => load(null, false), [load]);
  const loadMore = useCallback(() => {
    if (!nextCursor || loading || loadingMore) return Promise.resolve();
    return load(nextCursor, true);
  }, [load, loading, loadingMore, nextCursor]);

  return {
    items,
    loading,
    loadingMore,
    error,
    hasMore: Boolean(nextCursor),
    retry,
    loadMore,
  };
}
