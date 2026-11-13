import type { CutiaMedia } from "../src/features/agent-canvas/editing/cutia/project";
import { t } from "./adapters/i18n";

class MediaHttpError extends Error {
  constructor(readonly status: number, readonly retryAfterMs = 0) { super(`HTTP ${status}`); }
}

const CHUNK_SIZE = 1024 * 1024;
const MAX_ATTEMPTS = 8;
const REQUEST_TIMEOUT_MS = 15_000;
const RANGE_RECOVERY_TIMEOUT_MS = 90_000;

function retryAfterMs(response: Response): number {
  const value = response.headers?.get("Retry-After");
  if (!value) return 0;
  const seconds = Number(value);
  const delay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(value) - Date.now();
  return Number.isFinite(delay) ? Math.max(0, delay) : 0;
}

/** Keep large assets within proxy limits and retry only the interrupted range. */
export async function downloadMedia(
  source: Pick<CutiaMedia, "name" | "url">,
  onProgress?: (loaded: number, total: number) => void,
  onRetry?: () => void,
): Promise<Blob> {
  const url = new URL(source.url, window.location.origin);
  if (url.origin !== window.location.origin) throw new Error(`${source.name}: ${t("Media must belong to this project.")}`);
  async function readRange(offset: number, total?: number, expectedEtag?: string | null): Promise<{ blob: Blob; total?: number; etag?: string | null }> {
    // Bound a stalled range, without cutting off large files that keep progressing.
    const deadline = Date.now() + RANGE_RECOVERY_TIMEOUT_MS;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(new DOMException("Media request timed out", "TimeoutError")),
        Math.max(1, Math.min(REQUEST_TIMEOUT_MS, deadline - Date.now())));
      try {
        if (Date.now() >= deadline) throw new Error("Media download timed out");
        const response = await fetch(url, {
          credentials: "same-origin", cache: "no-store", signal: controller.signal,
          headers: { Range: `bytes=${offset}-${offset + CHUNK_SIZE - 1}` },
        });
        if (!response.ok) throw new MediaHttpError(response.status, retryAfterMs(response));
        const contentType = response.headers?.get("Content-Type")?.split(";")[0].trim().toLowerCase();
        if (contentType === "text/html" || contentType === "application/json") throw new Error(`Unexpected media response (${contentType})`);
        const etag = response.headers?.get("ETag");
        if (expectedEtag && etag !== expectedEtag) throw new Error("Media version changed during download");
        const blob = await response.blob();
        // Servers without range support return the complete file.
        if (response.status !== 206) {
          const length = response.headers?.get("Content-Length");
          const encoded = response.headers?.get("Content-Encoding");
          if (blob.size === 0 || (total !== undefined && blob.size !== total)
            || (length != null && !encoded && Number(length) !== blob.size)) throw new Error("Incomplete media response");
          return { blob, etag };
        }
        const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get("Content-Range") || "");
        if (!range) throw new Error("Invalid media range response");
        const [, start, end, length] = range.map(Number);
        if (!Number.isSafeInteger(length) || start !== offset || end < start || end !== Math.min(offset + CHUNK_SIZE, length) - 1
          || blob.size !== end - start + 1 || (total !== undefined && total !== length)) {
          throw new Error("Incomplete media range response");
        }
        return { blob, total: length, etag };
      } catch (error) {
        clearTimeout(timer);
        controller.abort();
        const retryable = !(error instanceof MediaHttpError) || error.status >= 500 || error.status === 408 || error.status === 429;
        const remaining = deadline - Date.now();
        const delay = Math.max(Math.min(500 * 2 ** attempt, 10_000) + Math.floor(Math.random() * 250),
          error instanceof MediaHttpError ? error.retryAfterMs : 0);
        if (!retryable || attempt === MAX_ATTEMPTS - 1 || remaining <= delay) {
          const reason = error instanceof Error ? error.message : String(error);
          throw new Error(`${t("Unable to download media.")} ${source.name} (${reason})`, { cause: error });
        }
        onRetry?.();
        await new Promise(resolve => setTimeout(resolve, delay));
      } finally {
        clearTimeout(timer);
        controller.abort();
      }
    }
    throw new Error(`${t("Unable to download media.")} ${source.name}`);
  }
  const first = await readRange(0);
  if (first.total === undefined) { onProgress?.(first.blob.size, first.blob.size); return first.blob; }
  const total = first.total;
  const parts = [first.blob];
  let loaded = first.blob.size;
  onProgress?.(loaded, total);
  // Bound both request size and concurrency; preserve source byte order even
  // when later chunks finish first over a forwarded connection.
  for (let offset = CHUNK_SIZE; offset < total; offset += CHUNK_SIZE * 4) {
    const offsets = Array.from({ length: 4 }, (_, index) => offset + index * CHUNK_SIZE).filter(start => start < total);
    const batch = await Promise.all(offsets.map(start => readRange(start, total, first.etag)));
    const full = batch.find(part => part.total === undefined);
    if (full) { onProgress?.(full.blob.size, full.blob.size); return full.blob; }
    parts.push(...batch.map(part => part.blob));
    loaded += batch.reduce((sum, part) => sum + part.blob.size, 0);
    onProgress?.(loaded, total);
  }
  return new Blob(parts, { type: first.blob.type });
}
