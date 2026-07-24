type QueryEntry<T> = {
  controller: AbortController;
  promise: Promise<T>;
};

export type SettledQueryResource<T> = {
  get(keyParts: unknown, fetcher: (signal: AbortSignal) => Promise<T>): Promise<T>;
  invalidate(keyParts?: unknown): void;
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
      const existing = entries.get(key);
      if (existing) return existing.promise;

      const controller = new AbortController();
      let pending: Promise<T>;
      try {
        pending = Promise.resolve(fetcher(controller.signal));
      } catch (error) {
        pending = Promise.reject(error);
      }
      const entry = { controller, promise: pending } as QueryEntry<T>;
      entry.promise = pending.catch((error: unknown) => {
        if (entries.get(key) === entry) entries.delete(key);
        throw error;
      });
      entries.set(key, entry);
      return entry.promise;
    },
    invalidate,
    clear() {
      for (const entry of entries.values()) entry.controller.abort();
      entries.clear();
    },
  };
}
