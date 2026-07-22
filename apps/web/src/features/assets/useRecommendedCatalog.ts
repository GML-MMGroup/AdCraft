import { useCallback, useEffect, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import type { V2RecommendedCatalogStatus } from "../../types-v2.ts";

const MAX_POLLS = 90;

export function useRecommendedCatalog(enabled: boolean) {
  const [status, setStatus] = useState<V2RecommendedCatalogStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollCountRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const next = await v2Api.recommendedCatalogStatus();
      setStatus(next);
      setError(null);
      return next;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Recommended catalog status failed";
      setError(message);
      return null;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled || !status || status.status !== "indexing" || pollCountRef.current >= MAX_POLLS) return;
    const timer = window.setTimeout(() => {
      pollCountRef.current += 1;
      void refresh();
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [enabled, refresh, status]);

  return { status, error, refresh };
}
