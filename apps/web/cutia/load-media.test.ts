import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadMedia } from "./load-media";

const source = { name: "BGM", url: "/api/v2/assets/music/content?v=version-1" };
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("editing source download", () => {
  it("assembles bounded ranges in order and retries only an interrupted part", async () => {
    vi.useFakeTimers();
    const chunkSize = 1024 * 1024;
    const bytes = new Uint8Array(chunkSize * 3 + 17);
    bytes[0] = 23; bytes[chunkSize] = 42; bytes[bytes.length - 1] = 99;
    let interrupted = false;
    const ranges: string[] = [];
    const progress = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (_url, options) => {
      const range = options.headers?.Range;
      ranges.push(range);
      const match = /^bytes=(\d+)-(\d+)$/.exec(range || "");
      if (!match) throw new TypeError("Failed to fetch");
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]), bytes.length - 1);
      if (start > 0 && !interrupted) { interrupted = true; throw new TypeError("Failed to fetch"); }
      return { ok: true, status: 206, headers: new Headers({ "Content-Range": `bytes ${start}-${end}/${bytes.length}` }),
        blob: async () => new Blob([bytes.slice(start, end + 1)], { type: "audio/wav" }) };
    }));
    const loading = downloadMedia(source, progress);
    await vi.runAllTimersAsync();
    const result = await loading;
    expect(result.size).toBe(bytes.length);
    expect(result.type).toBe("audio/wav");
    expect(Buffer.from(await result.arrayBuffer()).equals(Buffer.from(bytes))).toBe(true);
    expect(progress.mock.calls).toEqual([[chunkSize, bytes.length], [bytes.length, bytes.length]]);
    expect(ranges).toEqual([`bytes=0-${chunkSize - 1}`, `bytes=${chunkSize}-${2 * chunkSize - 1}`,
      `bytes=${2 * chunkSize}-${3 * chunkSize - 1}`, `bytes=${3 * chunkSize}-${4 * chunkSize - 1}`, `bytes=${chunkSize}-${2 * chunkSize - 1}`]);
  });

  it("recovers from an interrupted download without using a cached response", async () => {
    vi.useFakeTimers();
    const body = new Blob(["audio"]);
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({ ok: true, blob: async () => body });
    vi.stubGlobal("fetch", fetcher);
    const loading = downloadMedia(source);
    await vi.runAllTimersAsync();
    await expect(loading).resolves.toBe(body);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][1]).toMatchObject({ cache: "no-store", credentials: "same-origin" });
  });

  it("retries when the connection fails while reading the response body", async () => {
    vi.useFakeTimers();
    const body = new Blob(["complete"]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, blob: async () => { throw new TypeError("Failed to fetch"); } })
      .mockResolvedValue({ ok: true, blob: async () => body }));
    const loading = downloadMedia(source);
    await vi.runAllTimersAsync();
    await expect(loading).resolves.toBe(body);
  });

  it("reports the affected source after bounded retries", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetcher);
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    expect((await result).message).toContain("BGM");
    expect((await result).message).toContain("Failed to fetch");
    expect(fetcher).toHaveBeenCalledTimes(8);
  });

  it("does not retry a missing asset or request an external source", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    vi.stubGlobal("fetch", fetcher);
    await expect(downloadMedia(source)).rejects.toThrow(/BGM.*404/);
    expect(fetcher).toHaveBeenCalledOnce();
    await expect(downloadMedia({ ...source, url: "https://external.example/file" })).rejects.toThrow(/BGM/);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("recovers after a brief outage without exhausting retries in under a second", async () => {
    vi.useFakeTimers();
    const body = new Blob(["recovered"], { type: "audio/wav" });
    const fetcher = vi.fn();
    for (let index = 0; index < 5; index++) fetcher.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    fetcher.mockResolvedValue({ ok: true, status: 200, headers: new Headers(), blob: async () => body });
    vi.stubGlobal("fetch", fetcher);
    const started = Date.now();
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    expect(await result).toBe(body);
    expect(fetcher).toHaveBeenCalledTimes(6);
    expect(Date.now() - started).toBeGreaterThanOrEqual(15_000);
  });

  it("respects the server Retry-After delay", async () => {
    vi.useFakeTimers();
    const calls: number[] = [];
    const fetcher = vi.fn(async () => {
      calls.push(Date.now());
      if (calls.length === 1) return { ok: false, status: 503, headers: new Headers({ "Retry-After": "3" }) };
      return { ok: true, status: 200, headers: new Headers(), blob: async () => new Blob(["ready"]) };
    });
    vi.stubGlobal("fetch", fetcher);
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    expect((await result).size).toBe(5);
    expect(calls[1] - calls[0]).toBeGreaterThanOrEqual(3000);
  });

  it("aborts stalled requests and stops retrying within the download deadline", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise((_resolve, reject) => {
      signals.push(options.signal);
      options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    })));
    const started = Date.now();
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    expect((await result).message).toMatch(/BGM.*timed out/);
    expect(signals.length).toBeGreaterThan(1);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(Date.now() - started).toBeLessThanOrEqual(90_000);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("allows a large download to exceed 90 seconds while its ranges keep succeeding", async () => {
    vi.useFakeTimers();
    const chunkSize = 1024 * 1024;
    const total = chunkSize * 37 + 1;
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise((resolve, reject) => {
      const start = Number(/^bytes=(\d+)/.exec(options.headers.Range)![1]);
      const end = Math.min(start + chunkSize, total) - 1;
      const timer = setTimeout(() => resolve({ ok: true, status: 206,
        headers: new Headers({ "Content-Range": `bytes ${start}-${end}/${total}` }),
        blob: async () => new Blob([new Uint8Array(end - start + 1)]) }), 10_000);
      options.signal.addEventListener("abort", () => { clearTimeout(timer); reject(options.signal.reason); }, { once: true });
    })));
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    expect((await result).size).toBe(total);
  });

  it("rejects a truncated whole-file fallback and retries just that range", async () => {
    vi.useFakeTimers();
    const chunkSize = 1024 * 1024;
    const bytes = new Uint8Array(chunkSize + 17);
    bytes[chunkSize] = 42;
    let interrupted = false;
    const ranges: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url, options) => {
      ranges.push(options.headers.Range);
      const start = Number(/^bytes=(\d+)/.exec(options.headers.Range)![1]);
      if (start > 0 && !interrupted) {
        interrupted = true;
        return { ok: true, status: 200, headers: new Headers({ "Content-Length": "1" }), blob: async () => new Blob(["x"]) };
      }
      const end = Math.min(start + chunkSize, bytes.length) - 1;
      return { ok: true, status: 206, headers: new Headers({ "Content-Range": `bytes ${start}-${end}/${bytes.length}` }),
        blob: async () => new Blob([bytes.slice(start, end + 1)], { type: "audio/wav" }) };
    }));
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    const blob = await result;
    expect(blob.size).toBe(bytes.length);
    expect(Buffer.from(await blob.arrayBuffer()).equals(Buffer.from(bytes))).toBe(true);
    expect(ranges.filter(range => range.startsWith("bytes=0-"))).toHaveLength(1);
    expect(ranges).toHaveLength(3);
  });

  it("does not accept an HTML error page as a successful media download", async () => {
    vi.useFakeTimers();
    const body = new Blob(["audio"], { type: "audio/wav" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, status: 200,
      headers: new Headers({ "Content-Type": "text/html" }), blob: async () => new Blob(["<html>Unavailable</html>"]) })
      .mockResolvedValue({ ok: true, status: 200, headers: new Headers(), blob: async () => body }));
    const result = downloadMedia(source).catch(error => error);
    await vi.runAllTimersAsync();
    expect(await result).toBe(body);
  });
});
