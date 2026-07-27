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
let assetLibraryRefreshEpoch = 0;

type PaginationOperation = {
  cursor: string;
  generation: number;
  promise: Promise<void>;
  release(): void;
};

function assetLibraryPageQuery(
  scope: V2AssetLibraryScope,
  category: V2AssetLibraryCategory,
  search: string,
  cursor: string | null,
) {
  return { scope, category, search, cursor, limit: 40 };
}

export function useV2AssetLibrary({ scope, category, search, enabled = true }: UseV2AssetLibraryOptions) {
  const [entities, setEntities] = useState<V2AssetLibraryEntitySummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestGenerationRef = useRef(0);
  const previousQueryRef = useRef<{ scope: V2AssetLibraryScope; category: V2AssetLibraryCategory; search: string; refresh: number } | null>(null);
  const paginationOperationRef = useRef<PaginationOperation | null>(null);
  const nextCursorRef = useRef<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(() => assetLibraryRefreshEpoch);

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
    nextCursorRef.current = null;
    const query = assetLibraryPageQuery(scope, category, search, null);
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
        nextCursorRef.current = response.next_cursor ?? null;
        setEntities(response.entities);
        setNextCursor(nextCursorRef.current);
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
      const pagination = paginationOperationRef.current;
      if (pagination?.generation === generation) {
        paginationOperationRef.current = null;
        pagination.release();
      }
      if (requestGenerationRef.current === generation) requestGenerationRef.current += 1;
    };
  }, [category, enabled, refreshVersion, scope, search]);

  const refresh = useCallback(() => {
    assetLibraryQueryResource.evict(assetLibraryPageQuery(scope, category, search, null));
    assetLibraryRefreshEpoch += 1;
    setRefreshVersion(assetLibraryRefreshEpoch);
  }, [category, scope, search]);
  const loadMore = useCallback(() => {
    const generation = requestGenerationRef.current;
    const activeOperation = paginationOperationRef.current;
    if (activeOperation?.generation === generation) return activeOperation.promise;
    if (activeOperation) {
      paginationOperationRef.current = null;
      activeOperation.release();
    }
    const cursor = nextCursorRef.current;
    if (!cursor || loading) return Promise.resolve();
    const request = assetLibraryPageQuery(scope, category, search, cursor);
    const query = { ...request, refresh: refreshVersion };
    let signal: AbortSignal | undefined;
    const subscription = assetLibraryQueryResource.subscribe(
      query,
      (nextSignal) => {
        signal = nextSignal;
        return v2Api.listAssetLibraryEntities(request, { signal: nextSignal });
      },
    );
    const operation: PaginationOperation = {
      cursor,
      generation,
      promise: Promise.resolve(),
      release: subscription.release,
    };
    paginationOperationRef.current = operation;
    const ownsOperation = () => requestGenerationRef.current === generation
      && paginationOperationRef.current === operation;
    const canApplyResult = () => !signal?.aborted
      && ownsOperation()
      && nextCursorRef.current === operation.cursor;
    setLoadingMore(true);
    setError(null);
    operation.promise = subscription.promise.then((response) => {
      if (!canApplyResult()) return;
      nextCursorRef.current = response.next_cursor ?? null;
      setEntities((current) => [...current, ...response.entities]);
      setNextCursor(nextCursorRef.current);
    }).catch((caught) => {
      if (!canApplyResult()) return;
      setError(caught instanceof Error ? caught.message : "Asset library request failed");
    }).finally(() => {
      subscription.evict();
      subscription.release();
      if (!ownsOperation()) return;
      paginationOperationRef.current = null;
      setLoadingMore(false);
    });
    return operation.promise;
  }, [category, loading, refreshVersion, scope, search]);
  const fetchDetail = useCallback((entityId: string): Promise<V2AssetLibraryEntityDetail> => v2Api.assetLibraryEntity(entityId), []);

  return { entities, nextCursor, loading, loadingMore, error, refresh, loadMore, fetchDetail };
}
