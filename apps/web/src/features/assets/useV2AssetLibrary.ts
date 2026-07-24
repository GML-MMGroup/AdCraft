import { useCallback, useEffect, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import { createSettledQueryResource } from "../../collections/settledQueryResource.ts";
import type {
  V2AssetLibraryCategory,
  V2AssetLibraryEntityDetail,
  V2AssetLibraryListResponse,
  V2AssetLibraryEntitySummary,
  V2AssetLibraryScope,
} from "../../types-v2.ts";

type UseV2AssetLibraryOptions = {
  scope: V2AssetLibraryScope;
  category: V2AssetLibraryCategory;
  search: string;
  enabled?: boolean;
};

export const assetLibraryQueryResource = createSettledQueryResource<V2AssetLibraryListResponse>();

export function useV2AssetLibrary({ scope, category, search, enabled = true }: UseV2AssetLibraryOptions) {
  const [entities, setEntities] = useState<V2AssetLibraryEntitySummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const previousQueryRef = useRef<{ scope: V2AssetLibraryScope; category: V2AssetLibraryCategory; search: string; refresh: number } | null>(null);
  const paginationQueryRef = useRef<unknown>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    if (!enabled) {
      requestIdRef.current += 1;
      setLoading(false);
      return;
    }
    const currentQuery = { scope, category, search, refresh: refreshVersion };
    const previousQuery = previousQueryRef.current;
    previousQueryRef.current = currentQuery;
    const delay = previousQuery
      && previousQuery.scope === scope
      && previousQuery.category === category
      && previousQuery.refresh === refreshVersion
      && previousQuery.search !== search
      ? 250
      : 0;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setEntities([]);
    setNextCursor(null);
    const query = { scope, category, search, cursor: null, limit: 40, refresh: refreshVersion };
    let signal: AbortSignal | null = null;
    const startRequest = () => {
      void assetLibraryQueryResource.get(
        query,
        (nextSignal) => {
          signal = nextSignal;
          return v2Api.listAssetLibraryEntities({ scope, category, search, cursor: null, limit: 40 }, { signal: nextSignal });
        },
      ).then((response) => {
        if (signal?.aborted || requestId !== requestIdRef.current) return;
        setEntities(response.entities);
        setNextCursor(response.next_cursor ?? null);
      }).catch((caught) => {
        if (signal?.aborted || requestId !== requestIdRef.current) return;
        setError(caught instanceof Error ? caught.message : "Asset library request failed");
      }).finally(() => {
        if (!signal?.aborted && requestId === requestIdRef.current) setLoading(false);
      });
    };
    const timer = delay ? window.setTimeout(startRequest, delay) : null;
    if (!delay) startRequest();
    return () => {
      if (timer !== null) window.clearTimeout(timer);
      assetLibraryQueryResource.invalidate(query);
      if (paginationQueryRef.current) {
        assetLibraryQueryResource.invalidate(paginationQueryRef.current);
        paginationQueryRef.current = null;
      }
    };
  }, [category, enabled, refreshVersion, scope, search]);

  const refresh = useCallback(() => setRefreshVersion((version) => version + 1), []);
  const loadMore = useCallback(() => {
    if (!nextCursor || loadingMore || loading) return Promise.resolve();
    const requestId = ++requestIdRef.current;
    const query = { scope, category, search, cursor: nextCursor, limit: 40, refresh: refreshVersion };
    paginationQueryRef.current = query;
    setLoadingMore(true);
    setError(null);
    return assetLibraryQueryResource.get(
      query,
      (signal) => v2Api.listAssetLibraryEntities({ scope, category, search, cursor: nextCursor, limit: 40 }, { signal }),
    ).then((response) => {
      if (requestId !== requestIdRef.current) return;
      setEntities((current) => [...current, ...response.entities]);
      setNextCursor(response.next_cursor ?? null);
    }).catch((caught) => {
      if (requestId !== requestIdRef.current) return;
      setError(caught instanceof Error ? caught.message : "Asset library request failed");
    }).finally(() => {
      if (requestId === requestIdRef.current) {
        paginationQueryRef.current = null;
        setLoadingMore(false);
      }
    });
  }, [category, loading, loadingMore, nextCursor, refreshVersion, scope, search]);
  const fetchDetail = useCallback((entityId: string): Promise<V2AssetLibraryEntityDetail> => v2Api.assetLibraryEntity(entityId), []);

  return { entities, nextCursor, loading, loadingMore, error, refresh, loadMore, fetchDetail };
}
