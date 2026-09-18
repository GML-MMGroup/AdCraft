import {
  providerBalanceNoticeFromError,
  type ProviderBalanceNotice,
} from "./providerBalanceNotice.ts";

const SESSION_KEY = "adcraft.provider-balance-notices";

let notice: ProviderBalanceNotice | null = null;
const listeners = new Set<() => void>();

function readShownKeys(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((value): value is string => typeof value === "string"));
  } catch {
    return new Set();
  }
}

function writeShownKeys(keys: Set<string>): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify([...keys]));
  } catch {
    // Session persistence is best effort: a private browser mode still warns once.
  }
}

function emit(): void {
  listeners.forEach((listener) => listener());
}

/** Report one candidate notice; returns true when it was accepted for display. */
export function reportProviderBalanceNotice(
  candidate: ProviderBalanceNotice | null | undefined,
): boolean {
  if (!candidate) return false;
  const shown = readShownKeys();
  if (shown.has(candidate.dedupeKey)) return false;
  shown.add(candidate.dedupeKey);
  writeShownKeys(shown);
  if (notice !== null) return true;
  notice = candidate;
  emit();
  return true;
}

export function dismissProviderBalanceNotice(): void {
  if (notice === null) return;
  notice = null;
  emit();
}

export function subscribeProviderBalanceNotice(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function providerBalanceNoticeSnapshot(): ProviderBalanceNotice | null {
  return notice;
}

/** Test helper: clears both the active notice and the session-level memory. */
export function resetProviderBalanceNoticeStore(): void {
  notice = null;
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Ignore storage failures in tests and private browsing.
  }
  emit();
}

/** Report on behalf of any thrown canvas value without touching the caller flow. */
export function reportProviderBalanceError(error: unknown): void {
  reportProviderBalanceNotice(providerBalanceNoticeFromError(error));
}
