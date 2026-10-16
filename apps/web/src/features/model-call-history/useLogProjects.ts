import { useCallback, useEffect, useRef, useState } from "react";
import { agentModelCallHistoryApi } from "../../api/agentModelCallHistoryApi";
import type { ProjectV2Status, ProjectV2Summary } from "../../types-v2";
import { READ_INTERVAL_MS } from "./useCallHistory";
import { useTranslation } from "../../i18n/useTranslation";

/** Metadata only, page-scoped. The owning directory is keyed by project status. */
export function useLogProjects(status: ProjectV2Status) {
  const t = useTranslation();
  const [items, setItems] = useState<ProjectV2Summary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [cooldown, setCooldown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const nextReadAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(async (cursor: string | null) => {
    if (request.current || Date.now() < nextReadAt.current) return;
    const controller = new AbortController();
    request.current = controller;
    nextReadAt.current = Date.now() + READ_INTERVAL_MS;
    setCooldown(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCooldown(false), READ_INTERVAL_MS);
    setLoading(true);
    setError(null);
    try {
      const page = await agentModelCallHistoryApi.projects(status, cursor, controller.signal);
      if (controller.signal.aborted) return;
      setItems(previous => [...new Map([
        ...(cursor ? previous : []), ...page.items,
      ].map(project => [project.project_id, project])).values()]);
      setNextCursor(page.next_cursor === cursor ? null : page.next_cursor);
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : t("Project directory could not be read. Retry."));
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    const initial = setTimeout(() => { void load(null); }, 200);
    return () => {
      clearTimeout(initial);
      clearTimeout(timer.current);
      request.current?.abort();
      request.current = null;
    };
  }, [load]);

  return { items, loading, error, cooldown, canLoadMore: nextCursor !== null,
    refresh: () => load(null),
    more: () => nextCursor ? load(nextCursor) : Promise.resolve() };
}
