type SnapshotFetcher<T> = () => Promise<T>;

type SnapshotEntry<T> = {
  refreshQueued: boolean;
  promise: Promise<T>;
};

/**
 * Keeps one canonical runtime request per workflow in flight. Signals that
 * arrive during that request are folded into one trailing snapshot so the
 * caller observes state produced after the burst, without concurrent GETs.
 */
export function createV2RuntimeSnapshotCoordinator<T = unknown>() {
  const entries = new Map<string, SnapshotEntry<T>>();

  function request(
    workflowId: string,
    fetchSnapshot: SnapshotFetcher<T>,
    options: { queueRefresh?: boolean } = {},
  ): Promise<T> {
    const existing = entries.get(workflowId);
    if (existing) {
      if (options.queueRefresh !== false) existing.refreshQueued = true;
      return existing.promise;
    }

    const entry: SnapshotEntry<T> = {
      refreshQueued: false,
      promise: Promise.resolve(undefined as T),
    };
    entry.promise = (async () => {
      let latest: T;
      do {
        entry.refreshQueued = false;
        latest = await fetchSnapshot();
      } while (entry.refreshQueued);
      return latest!;
    })().finally(() => {
      if (entries.get(workflowId) === entry) entries.delete(workflowId);
    });
    entries.set(workflowId, entry);
    return entry.promise;
  }

  return {
    request,
    isPending(workflowId: string) {
      return entries.has(workflowId);
    },
    clear(workflowId?: string | null) {
      if (workflowId) {
        entries.delete(workflowId);
        return;
      }
      entries.clear();
    },
  };
}
