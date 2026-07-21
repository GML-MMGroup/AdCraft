import { useCallback, useEffect, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import type {
  V2AssetLibraryCategory,
  V2AssetLibraryEntityDetail,
  V2AssetLibraryEntitySummary,
  V2AssetLibraryScope,
} from "../../types-v2.ts";

type UseV2AssetLibraryOptions = {
  scope: V2AssetLibraryScope;
  category: V2AssetLibraryCategory;
  search: string;
  enabled?: boolean;
};

export function useV2AssetLibrary({ scope, category, search, enabled = true }: UseV2AssetLibraryOptions) {
  const [entities, setEntities] = useState<V2AssetLibraryEntitySummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const load = useCallback(async (cursor?: string | null, append = false) => {
    if (!enabled) return;
    const requestId = ++requestIdRef.current;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError(null);
    try {
      const response = await v2Api.listAssetLibraryEntities({ scope, category, search, cursor: cursor ?? null, limit: 40 });
      if (requestId !== requestIdRef.current) return;
      setEntities((current) => append ? [...current, ...response.entities] : response.entities);
      setNextCursor(response.next_cursor ?? null);
    } catch (caught) {
      if (requestId !== requestIdRef.current) return;
      setError(caught instanceof Error ? caught.message : "Asset library request failed");
      if (!append) {
        setEntities([]);
        setNextCursor(null);
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [category, enabled, scope, search]);

  useEffect(() => {
    void load();
    return () => { requestIdRef.current += 1; };
  }, [load]);

  const refresh = useCallback(() => load(), [load]);
  const loadMore = useCallback(() => {
    if (!nextCursor || loadingMore || loading) return Promise.resolve();
    return load(nextCursor, true);
  }, [load, loading, loadingMore, nextCursor]);
  const fetchDetail = useCallback((entityId: string): Promise<V2AssetLibraryEntityDetail> => v2Api.assetLibraryEntity(entityId), []);

  return { entities, nextCursor, loading, loadingMore, error, refresh, loadMore, fetchDetail };
}
