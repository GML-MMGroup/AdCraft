import { useCallback, useEffect, useState } from "react";
import { v2Api } from "../../api/v2Client";
import { createRecentProjectsCache } from "./recentProjectsCache";

const recentProjectsCache = createRecentProjectsCache(v2Api.listProjectsWithEtag);

export function useRecentProjects() {
  const [projects, setProjects] = useState(() => recentProjectsCache.peek());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void recentProjectsCache.load(revision > 0).then((items) => {
      if (!active) return;
      setProjects(items);
      setError(false);
    }, () => {
      if (active) setError(true);
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [revision]);

  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  return { projects, loading, error, refresh };
}
