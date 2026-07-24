type QueryEntry<T> = {
  controller: AbortController;
  promise: Promise<T>;
  subscribers: number;
  settled: boolean;
};

export type QuerySubscription<T> = {
  promise: Promise<T>;
  release(): void;
};

export type SettledQueryResource<T> = {
  get(keyParts: unknown, fetcher: (signal: AbortSignal) => Promise<T>): Promise<T>;
  subscribe(keyParts: unknown, fetcher: (signal: AbortSignal) => Promise<T>): QuerySubscription<T>;
  invalidate(keyParts?: unknown): void;
  evict(keyParts: unknown): void;
  clear(): void;
};

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

export function createSettledQueryResource<T = unknown>(): SettledQueryResource<T> {
  const entries = new Map<string, QueryEntry<T>>();

  function createEntry(key: string, fetcher: (signal: AbortSignal) => Promise<T>) {
    const controller = new AbortController();
    const entry = {
      controller,
      promise: Promise.resolve(undefined as T),
      subscribers: 0,
      settled: false,
    } as QueryEntry<T>;
    let pending: Promise<T>;
    try {
      pending = Promise.resolve(fetcher(controller.signal));
    } catch (error) {
      pending = Promise.reject(error);
    }
    entry.promise = pending.then(
      (value) => {
        entry.settled = true;
        return value;
      },
      (error: unknown) => {
        if (entries.get(key) === entry) entries.delete(key);
        throw error;
      },
    );
    entries.set(key, entry);
    return entry;
  }

  function invalidate(keyParts?: unknown) {
    if (keyParts === undefined) {
      for (const entry of entries.values()) entry.controller.abort();
      entries.clear();
      return;
    }
    const key = stableQueryKey(keyParts);
    const entry = entries.get(key);
    if (!entry) return;
    entries.delete(key);
    entry.controller.abort();
  }

  return {
    get(keyParts, fetcher) {
      const key = stableQueryKey(keyParts);
      return (entries.get(key) ?? createEntry(key, fetcher)).promise;
    },
    subscribe(keyParts, fetcher) {
      const key = stableQueryKey(keyParts);
      const entry = entries.get(key) ?? createEntry(key, fetcher);
      entry.subscribers += 1;
      let released = false;
      return {
        promise: entry.promise,
        release() {
          if (released) return;
          released = true;
          entry.subscribers -= 1;
          if (entry.subscribers === 0 && !entry.settled && entries.get(key) === entry) {
            entries.delete(key);
            entry.controller.abort();
          }
        },
      };
    },
    invalidate,
    evict(keyParts) {
      entries.delete(stableQueryKey(keyParts));
    },
    clear() {
      for (const entry of entries.values()) entry.controller.abort();
      entries.clear();
    },
  };
}
