import { afterEach, describe, expect, it, vi } from "vitest";
import { createRoleVisualCache } from "./agentRoleVisualResource.ts";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const Artwork = () => null;
function setup() {
  const full = deferred<HTMLImageElement>();
  const small = deferred<HTMLImageElement>();
  const module = deferred<typeof Artwork>();
  const decode = vi.fn((source: string) => source === "small" ? small.promise : full.promise);
  const load = vi.fn(() => module.promise);
  let revision = "v1";
  const cache = createRoleVisualCache({
    asset: () => ({ source: revision, fallback: "small", revision }),
    decode, load, retryModule: vi.fn(),
  });
  return { cache, full, small, module, decode, load, setRevision: (value: string) => { revision = value; } };
}
const image = () => new Image();
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
afterEach(() => vi.useRealTimers());

describe("role visual resource cache", () => {
  it("shares bitmap decoding across modes and does not load an idle artwork", async () => {
    const { cache, full, decode, load } = setup();
    cache.prepare("scene_design", "bitmap");
    cache.prepare("scene_design", "bitmap");
    expect(decode).toHaveBeenCalledTimes(2);
    expect(load).not.toHaveBeenCalled();
    expect(cache.snapshot("scene_design", "bitmap").status).toBe("pending");
    full.resolve(image()); await flush();
    expect(cache.snapshot("scene_design", "bitmap").source).toBe("v1");
    expect(cache.snapshot("scene_design", "bitmap").status).toBe("ready");
    cache.prepare("scene_design", "animated");
    expect(decode).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("waits for decoded bitmap and artwork before publishing an animated identity", async () => {
    const { cache, full, module } = setup();
    cache.prepare("character_design", "animated");
    module.resolve(Artwork); await flush();
    expect(cache.snapshot("character_design", "animated").status).toBe("pending");
    full.resolve(image()); await flush();
    expect(cache.snapshot("character_design", "animated")).toMatchObject({ status: "ready", Artwork });
  });

  it("publishes decoded small fallback at budget then upgrades without another request", async () => {
    vi.useFakeTimers();
    const { cache, full, small, module, load } = setup();
    cache.prepare("scene_design", "animated");
    small.resolve(image()); await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(cache.snapshot("scene_design", "animated")).toMatchObject({ status: "fallback", source: "small" });
    full.resolve(image()); module.resolve(Artwork); await flush();
    expect(cache.snapshot("scene_design", "animated")).toMatchObject({ status: "ready", source: "v1", Artwork });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("contains decode failures and allows explicit retry without rerender retry loops", async () => {
    const { cache, full, small, module, load, decode } = setup();
    cache.prepare("scene_design", "animated");
    full.reject(new Error("offline")); small.reject(new Error("bad inline image"));
    module.reject(new Error("chunk failed")); await flush();
    expect(cache.snapshot("scene_design", "animated")).toMatchObject({ status: "fallback", source: null, fallbackKind: "generic" });
    cache.prepare("scene_design", "animated");
    expect(load).toHaveBeenCalledTimes(1);
    decode.mockImplementation(async () => image());
    load.mockImplementation(async () => Artwork);
    cache.retry("scene_design", "animated"); await flush();
    expect(load).toHaveBeenCalledTimes(2);
    expect(cache.snapshot("scene_design", "animated")).toMatchObject({ status: "ready", source: "v1", Artwork });
  });

  it("permits only one explicit bitmap retry per role revision", async () => {
    const { cache, full, small, decode } = setup();
    cache.prepare("scene_design", "bitmap");
    full.reject(new Error("offline")); small.reject(new Error("bad inline image")); await flush();
    decode.mockRejectedValue(new Error("still offline"));

    cache.retry("scene_design", "bitmap"); await flush();
    expect(cache.snapshot("scene_design", "bitmap")).toMatchObject({
      status: "fallback", retryAvailable: false,
    });
    expect(decode).toHaveBeenCalledTimes(4);

    cache.retry("scene_design", "bitmap"); await flush();
    expect(decode).toHaveBeenCalledTimes(4);
  });

  it("keeps a healthy animation ready when another subscriber retries bitmap mode", async () => {
    const { cache, full, module, load } = setup();
    cache.prepare("scene_design", "animated");
    full.resolve(image()); module.resolve(Artwork); await flush();
    cache.retry("scene_design", "bitmap"); await flush();
    expect(cache.snapshot("scene_design", "animated")).toMatchObject({ status: "ready", Artwork });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("replaces old revision entries and ignores their late completions", async () => {
    const { cache, full, setRevision } = setup();
    cache.prepare("scene_design", "bitmap");
    const old = cache.snapshot("scene_design", "bitmap");
    setRevision("v2");
    expect(cache.snapshot("scene_design", "bitmap")).not.toBe(old);
    full.resolve(image()); await flush();
    expect(cache.snapshot("scene_design", "bitmap").status).toBe("pending");
  });

  it("reports artwork render errors without invalidating the healthy bitmap", async () => {
    const { cache, full, module } = setup();
    cache.prepare("scene_design", "animated");
    full.resolve(image()); module.resolve(Artwork); await flush();
    cache.artworkFailed("scene_design", "render failed");
    expect(cache.snapshot("scene_design", "animated")).toMatchObject({ status: "fallback", error: "render failed", source: "v1" });
    expect(cache.snapshot("scene_design", "bitmap").status).toBe("ready");
  });
});
