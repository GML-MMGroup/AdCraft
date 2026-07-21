import { useCallback, useEffect, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import type { V2RecommendedCatalogStatus } from "../../types-v2.ts";

const WORKING_STATUSES = new Set(["downloading", "verifying", "installing"]);
const MAX_POLLS = 90;

export function useRecommendedCatalog(enabled: boolean) {
  const [status, setStatus] = useState<V2RecommendedCatalogStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const installRequestedRef = useRef(false);
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

  const install = useCallback(async () => {
    installRequestedRef.current = true;
    try {
      const next = await v2Api.installRecommendedCatalog();
      setStatus(next);
      setError(null);
      return next;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Recommended catalog install failed";
      setError(message);
      return null;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void (async () => {
      const next = await refresh();
      if (cancelled || !next) return;
      if (next.status === "not_installed" && !installRequestedRef.current) void install();
    })();
    return () => { cancelled = true; };
  }, [enabled, install, refresh]);

  useEffect(() => {
    if (!enabled || !status || !WORKING_STATUSES.has(status.status) || pollCountRef.current >= MAX_POLLS) return;
    const timer = window.setTimeout(() => {
      pollCountRef.current += 1;
      void refresh();
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [enabled, refresh, status]);

  return { status, error, refresh, install };
}
