type QueryEntry<T> = {
  controller: AbortController;
  promise: Promise<T>;
  subscribers: number;
  settled: boolean;
  settledAt: number | null;
};

export type QuerySubscription<T> = {
  promise: Promise<T>;
  /** Prevent future subscribers from reusing this exact entry without interrupting current subscribers. */
  evict(): void;
  release(): void;
};

export type SettledQueryResource<T> = {
  get(keyParts: unknown, fetcher: (signal: AbortSignal) => Promise<T>): Promise<T>;
  subscribe(keyParts: unknown, fetcher: (signal: AbortSignal) => Promise<T>): QuerySubscription<T>;
  /** Discard cached values and abort matching in-flight work. */
  invalidate(keyParts?: unknown): void;
  /** Abort all in-flight work while retaining settled cache entries. */
  cancelPending(): void;
  /** Prevent future reuse while allowing current subscribers to finish. */
  evict(keyParts: unknown): void;
  clear(): void;
};

export type SettledQueryResourceOptions = {
  maxEntries?: number;
  ttlMs?: number;
  now?: () => number;
};

const DEFAULT_MAX_ENTRIES = 100;
const DEFAULT_TTL_MS = 5 * 60 * 1000;

export function stableQueryKey(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number") return Number.isNaN(value) ? "number:NaN" : `number:${value}`;
  if (Array.isArray(value)) return `[${value.map(stableQueryKey).join(",")}]`;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableQueryKey(record[key])}`).join(",")}}`;
  }
  return `${typeof value}:${String(value)}`;
}

export function createSettledQueryResource<T = unknown>({
  maxEntries = DEFAULT_MAX_ENTRIES,
  ttlMs = DEFAULT_TTL_MS,
  now = Date.now,
}: SettledQueryResourceOptions = {}): SettledQueryResource<T> {
  const entries = new Map<string, QueryEntry<T>>();
  const pendingEntries = new Set<QueryEntry<T>>();
  const settledCapacity = Math.max(1, Math.floor(maxEntries));
  const settledTtlMs = Math.max(0, ttlMs);

  function evictEntry(key: string, entry: QueryEntry<T>) {
    if (entries.get(key) === entry) entries.delete(key);
  }

  function touchEntry(key: string, entry: QueryEntry<T>) {
    if (entries.get(key) !== entry) return;
    entries.delete(key);
    entries.set(key, entry);
  }

  function pruneExpired() {
    const currentTime = now();
    for (const [key, entry] of entries) {
      if (!entry.settled || entry.settledAt === null) continue;
      if (currentTime - entry.settledAt >= settledTtlMs) entries.delete(key);
    }
  }

  function enforceSettledCapacity() {
    let settledEntries = [...entries.values()].filter((entry) => entry.settled).length;
    while (settledEntries > settledCapacity) {
      const oldestSettled = [...entries].find(([, entry]) => entry.settled);
      if (!oldestSettled) return;
      entries.delete(oldestSettled[0]);
      settledEntries -= 1;
    }
  }

  function existingEntry(key: string) {
    const entry = entries.get(key);
    if (!entry) return undefined;
    if (entry.settled && entry.settledAt !== null && now() - entry.settledAt >= settledTtlMs) {
      entries.delete(key);
      return undefined;
    }
    touchEntry(key, entry);
    return entry;
  }

  function createEntry(key: string, fetcher: (signal: AbortSignal) => Promise<T>) {
    const controller = new AbortController();
    const entry = {
      controller,
      promise: Promise.resolve(undefined as T),
      subscribers: 0,
      settled: false,
      settledAt: null,
    } as QueryEntry<T>;
    let pending: Promise<T>;
    try {
      pending = Promise.resolve(fetcher(controller.signal));
    } catch (error) {
      pending = Promise.reject(error);
    }
    pendingEntries.add(entry);
    entry.promise = pending.then(
      (value) => {
        pendingEntries.delete(entry);
        entry.settled = true;
        entry.settledAt = now();
        touchEntry(key, entry);
        pruneExpired();
        enforceSettledCapacity();
        return value;
      },
      (error: unknown) => {
        pendingEntries.delete(entry);
        evictEntry(key, entry);
        throw error;
      },
    );
    entries.set(key, entry);
    return entry;
  }

  function invalidate(keyParts?: unknown) {
    if (keyParts === undefined) {
      for (const entry of pendingEntries) entry.controller.abort();
      entries.clear();
      return;
    }
    const key = stableQueryKey(keyParts);
    const entry = entries.get(key);
    if (!entry) return;
    entries.delete(key);
    entry.controller.abort();
  }

  function cancelPending() {
    for (const entry of pendingEntries) entry.controller.abort();
  }

  return {
    get(keyParts, fetcher) {
      const key = stableQueryKey(keyParts);
      pruneExpired();
      return (existingEntry(key) ?? createEntry(key, fetcher)).promise;
    },
    subscribe(keyParts, fetcher) {
      const key = stableQueryKey(keyParts);
      pruneExpired();
      const entry = existingEntry(key) ?? createEntry(key, fetcher);
      entry.subscribers += 1;
      let released = false;
      return {
        promise: entry.promise,
        evict() {
          evictEntry(key, entry);
        },
        release() {
          if (released) return;
          released = true;
          entry.subscribers -= 1;
          if (entry.subscribers === 0 && !entry.settled) {
            evictEntry(key, entry);
            entry.controller.abort();
          }
        },
      };
    },
    invalidate,
    cancelPending,
    evict(keyParts) {
      const key = stableQueryKey(keyParts);
      const entry = entries.get(key);
      if (!entry) return;
      entries.delete(key);
      if (!entry.settled && entry.subscribers === 0) entry.controller.abort();
    },
    clear() {
      for (const entry of pendingEntries) entry.controller.abort();
      entries.clear();
    },
  };
}
