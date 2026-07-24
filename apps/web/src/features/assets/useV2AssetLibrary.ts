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
  const requestGenerationRef = useRef(0);
  const previousQueryRef = useRef<{ scope: V2AssetLibraryScope; category: V2AssetLibraryCategory; search: string; refresh: number } | null>(null);
  const paginationSubscriptionRef = useRef<{ generation: number; release(): void } | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const generation = ++requestGenerationRef.current;
    let mounted = true;
    if (!enabled) {
      setLoading(false);
      return () => {
        mounted = false;
        if (requestGenerationRef.current === generation) requestGenerationRef.current += 1;
      };
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
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setEntities([]);
    setNextCursor(null);
    const query = { scope, category, search, cursor: null, limit: 40, refresh: refreshVersion };
    let signal: AbortSignal | undefined;
    let release: (() => void) | undefined;
    const isCurrent = () => mounted && requestGenerationRef.current === generation;
    const startRequest = () => {
      const subscription = assetLibraryQueryResource.subscribe(
        query,
        (nextSignal) => {
          signal = nextSignal;
          return v2Api.listAssetLibraryEntities({ scope, category, search, cursor: null, limit: 40 }, { signal: nextSignal });
        },
      );
      release = subscription.release;
      void subscription.promise.then((response) => {
        if (signal?.aborted || !isCurrent()) return;
        setEntities(response.entities);
        setNextCursor(response.next_cursor ?? null);
      }).catch((caught) => {
        if (signal?.aborted || !isCurrent()) return;
        setError(caught instanceof Error ? caught.message : "Asset library request failed");
      }).finally(() => {
        if (!signal?.aborted && isCurrent()) setLoading(false);
        release?.();
      });
    };
    const timer = delay ? window.setTimeout(startRequest, delay) : null;
    if (!delay) startRequest();
    return () => {
      mounted = false;
      if (timer !== null) window.clearTimeout(timer);
      release?.();
      const pagination = paginationSubscriptionRef.current;
      if (pagination?.generation === generation) {
        pagination.release();
        paginationSubscriptionRef.current = null;
      }
      if (requestGenerationRef.current === generation) requestGenerationRef.current += 1;
    };
  }, [category, enabled, refreshVersion, scope, search]);

  const refresh = useCallback(() => setRefreshVersion((version) => version + 1), []);
  const loadMore = useCallback(() => {
    if (!nextCursor || loadingMore || loading) return Promise.resolve();
    const generation = requestGenerationRef.current;
    const query = { scope, category, search, cursor: nextCursor, limit: 40, refresh: refreshVersion };
    let signal: AbortSignal | undefined;
    const subscription = assetLibraryQueryResource.subscribe(
      query,
      (nextSignal) => {
        signal = nextSignal;
        return v2Api.listAssetLibraryEntities({ scope, category, search, cursor: nextCursor, limit: 40 }, { signal: nextSignal });
      },
    );
    const pagination = { generation, release: subscription.release };
    paginationSubscriptionRef.current = pagination;
    const isCurrent = () => !signal?.aborted && requestGenerationRef.current === generation;
    setLoadingMore(true);
    setError(null);
    return subscription.promise.then((response) => {
      if (!isCurrent()) return;
      setEntities((current) => [...current, ...response.entities]);
      setNextCursor(response.next_cursor ?? null);
    }).catch((caught) => {
      if (!isCurrent()) return;
      setError(caught instanceof Error ? caught.message : "Asset library request failed");
    }).finally(() => {
      assetLibraryQueryResource.evict(query);
      subscription.release();
      if (!isCurrent()) return;
      if (paginationSubscriptionRef.current === pagination) paginationSubscriptionRef.current = null;
      setLoadingMore(false);
    });
  }, [category, loading, loadingMore, nextCursor, refreshVersion, scope, search]);
  const fetchDetail = useCallback((entityId: string): Promise<V2AssetLibraryEntityDetail> => v2Api.assetLibraryEntity(entityId), []);

  return { entities, nextCursor, loading, loadingMore, error, refresh, loadMore, fetchDetail };
}
