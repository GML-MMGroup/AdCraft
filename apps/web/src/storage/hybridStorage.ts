export type HybridStorageNamespace =
  | "workflowDrafts"
  | "canvasSnapshots"
  | "projectRecords"
  | "trashRecords"
  | "messageThreads"
  | "nodeRunCaches"
  | "videoPosterCache";

export type HybridStoragePointer = {
  storage: "indexeddb";
  namespace: HybridStorageNamespace;
  key: string;
  updated_at?: string;
};

const DB_NAME = "ad-workflow-hybrid-storage";
const DB_VERSION = 1;
const STORE_NAME = "records";
export const HYBRID_MEMORY_RECORD_LIMIT = 120;
export const HYBRID_STORAGE_ERROR_EVENT = "hybrid-storage:error";
const memoryRecords = new Map<string, unknown>();
let dbPromise: Promise<IDBDatabase | null> | null = null;

export type HybridStorageErrorDetail = {
  namespace?: HybridStorageNamespace;
  key?: string;
  operation: "indexeddb-write" | "indexeddb-delete" | "local-storage-write";
  message: string;
};

export function hybridStoragePointer(namespace: HybridStorageNamespace, key: string): HybridStoragePointer {
  return {
    storage: "indexeddb",
    namespace,
    key,
    updated_at: new Date().toISOString(),
  };
}

export function isHybridStoragePointer(value: unknown): value is HybridStoragePointer {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Partial<HybridStoragePointer>;
  return record.storage === "indexeddb" && isHybridNamespace(record.namespace) && typeof record.key === "string";
}

export function saveHybridRecordSync(namespace: HybridStorageNamespace, key: string, value: unknown) {
  const id = recordId(namespace, key);
  touchMemoryRecord(id, value);
  void putIndexedDbRecord(id, namespace, key, value);
}

export function loadHybridRecordSync<T>(namespace: HybridStorageNamespace, key: string): T | undefined {
  const id = recordId(namespace, key);
  if (!memoryRecords.has(id)) return undefined;
  const value = memoryRecords.get(id);
  touchMemoryRecord(id, value);
  return value as T | undefined;
}

export async function loadHybridRecord<T>(namespace: HybridStorageNamespace, key: string): Promise<T | undefined> {
  const id = recordId(namespace, key);
  if (memoryRecords.has(id)) {
    const value = memoryRecords.get(id);
    touchMemoryRecord(id, value);
    return value as T;
  }
  const value = await getIndexedDbRecord(id);
  if (value !== undefined) touchMemoryRecord(id, value);
  return value as T | undefined;
}

export function deleteHybridRecordSync(namespace: HybridStorageNamespace, key: string) {
  const id = recordId(namespace, key);
  memoryRecords.delete(id);
  void deleteIndexedDbRecord(id);
}

export function deleteHybridRecordsWhereSync(namespace: HybridStorageNamespace, predicate: (value: unknown, key: string) => boolean) {
  for (const [id, value] of [...memoryRecords.entries()]) {
    const parsed = parseRecordId(id);
    if (!parsed || parsed.namespace !== namespace) continue;
    if (predicate(value, parsed.key)) memoryRecords.delete(id);
  }
  void deleteIndexedDbRecordsWhere(namespace, predicate);
}

export function listHybridRecordsSync<T>(namespace: HybridStorageNamespace): Array<{ key: string; value: T }> {
  const records: Array<{ key: string; value: T }> = [];
  for (const [id, value] of memoryRecords.entries()) {
    const parsed = parseRecordId(id);
    if (!parsed || parsed.namespace !== namespace) continue;
    records.push({ key: parsed.key, value: value as T });
  }
  return records;
}

export function safeWriteJson(storage: Pick<Storage, "setItem">, key: string, value: unknown) {
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch (error) {
    dispatchHybridStorageError({
      key,
      operation: "local-storage-write",
      message: errorMessage(error, "Local storage write failed."),
    });
    return false;
  }
}

export function safeRemoveItem(storage: Pick<Storage, "removeItem">, key: string) {
  try {
    storage.removeItem(key);
  } catch {
    // Storage may be unavailable in private mode.
  }
}

function recordId(namespace: HybridStorageNamespace, key: string) {
  return `${namespace}:${key}`;
}

function parseRecordId(id: string) {
  const separatorIndex = id.indexOf(":");
  if (separatorIndex < 0) return null;
  const namespace = id.slice(0, separatorIndex);
  const key = id.slice(separatorIndex + 1);
  return isHybridNamespace(namespace) ? { namespace, key } : null;
}

function touchMemoryRecord(id: string, value: unknown) {
  if (memoryRecords.has(id)) memoryRecords.delete(id);
  memoryRecords.set(id, value);
  while (memoryRecords.size > HYBRID_MEMORY_RECORD_LIMIT) {
    const oldestKey = memoryRecords.keys().next().value;
    if (!oldestKey) break;
    memoryRecords.delete(oldestKey);
  }
}

function isHybridNamespace(value: unknown): value is HybridStorageNamespace {
  return (
    value === "workflowDrafts" ||
    value === "canvasSnapshots" ||
    value === "projectRecords" ||
    value === "trashRecords" ||
    value === "messageThreads" ||
    value === "nodeRunCaches" ||
    value === "videoPosterCache"
  );
}

async function putIndexedDbRecord(id: string, namespace: HybridStorageNamespace, key: string, value: unknown) {
  const db = await openDb();
  if (!db) {
    dispatchHybridStorageError({
      namespace,
      key,
      operation: "indexeddb-write",
      message: "IndexedDB is unavailable. Project changes are kept only in this browser tab.",
    });
    return;
  }
  const ok = await runTransaction(db, "readwrite", (store) => {
    store.put({
      id,
      namespace,
      key,
      value,
      updated_at: new Date().toISOString(),
    });
  });
  if (!ok) {
    dispatchHybridStorageError({
      namespace,
      key,
      operation: "indexeddb-write",
      message: "IndexedDB write failed. Project changes may not persist after refresh.",
    });
  }
}

async function getIndexedDbRecord(id: string) {
  const db = await openDb();
  if (!db) return undefined;
  return new Promise<unknown | undefined>((resolve) => {
    try {
      const transaction = db.transaction(STORE_NAME, "readonly");
      const request = transaction.objectStore(STORE_NAME).get(id);
      request.onsuccess = () => {
        const record = request.result as { value?: unknown } | undefined;
        resolve(record?.value);
      };
      request.onerror = () => resolve(undefined);
    } catch {
      resolve(undefined);
    }
  });
}

async function deleteIndexedDbRecord(id: string) {
  const db = await openDb();
  if (!db) return;
  const parsed = parseRecordId(id);
  const ok = await runTransaction(db, "readwrite", (store) => {
    store.delete(id);
  });
  if (!ok) {
    dispatchHybridStorageError({
      namespace: parsed?.namespace,
      key: parsed?.key,
      operation: "indexeddb-delete",
      message: "IndexedDB delete failed. Removed project data may remain in local storage.",
    });
  }
}

async function deleteIndexedDbRecordsWhere(namespace: HybridStorageNamespace, predicate: (value: unknown, key: string) => boolean) {
  const db = await openDb();
  if (!db) return;
  await new Promise<void>((resolve) => {
    try {
      const transaction = db.transaction(STORE_NAME, "readwrite");
      const store = transaction.objectStore(STORE_NAME);
      const request = store.openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return;
        const record = cursor.value as { id?: string; namespace?: string; key?: string; value?: unknown };
        if (record.namespace === namespace && typeof record.key === "string" && predicate(record.value, record.key)) {
          cursor.delete();
        }
        cursor.continue();
      };
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => resolve();
      transaction.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}

function openDb() {
  if (typeof indexedDB === "undefined") return Promise.resolve(null);
  if (dbPromise) return dbPromise;

  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: "id" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

function runTransaction(db: IDBDatabase, mode: IDBTransactionMode, operation: (store: IDBObjectStore) => void) {
  return new Promise<boolean>((resolve) => {
    try {
      const transaction = db.transaction(STORE_NAME, mode);
      operation(transaction.objectStore(STORE_NAME));
      transaction.oncomplete = () => resolve(true);
      transaction.onerror = () => resolve(false);
      transaction.onabort = () => resolve(false);
    } catch {
      resolve(false);
    }
  });
}

function dispatchHybridStorageError(detail: HybridStorageErrorDetail) {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function" || typeof CustomEvent === "undefined") return;
  window.dispatchEvent(new CustomEvent(HYBRID_STORAGE_ERROR_EVENT, { detail }));
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
