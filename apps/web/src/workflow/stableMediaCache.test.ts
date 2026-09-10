import { afterEach, describe, expect, it, vi } from "vitest";

import {
  __resetStableMediaCacheForTests,
  isStableMediaUrl,
  loadStableMedia,
  retainStableMedia,
} from "./stableMediaCache.ts";

describe("stable media cache", () => {
  afterEach(() => {
    __resetStableMediaCacheForTests();
    vi.restoreAllMocks();
  });

  it("only persists versioned media URLs", () => {
    expect(isStableMediaUrl("/api/v2/assets/a/content?v=v1")).toBe(true);
    expect(isStableMediaUrl("/api/v2/assets/a/content")).toBe(false);
    expect(isStableMediaUrl("blob:https://example.test/media")).toBe(false);
  });

  it("shares the in-flight request for one AssetVersion", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("image", { status: 200 }));
    const first = loadStableMedia("/api/v2/assets/a/content?v=v1");
    const second = loadStableMedia("/api/v2/assets/a/content?v=v1");

    const [firstUrl, secondUrl] = await Promise.all([first, second]);
    expect(firstUrl).toBe(secondUrl);
    expect(firstUrl).toMatch(/^blob:/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("uses a different cache key after the AssetVersion changes", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("image", { status: 200 }));
    await loadStableMedia("/api/v2/assets/version-change/content?v=v1");
    await loadStableMedia("/api/v2/assets/version-change/content?v=v2");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not revoke a retained media URL when the memory cache trims", async () => {
    let objectUrlIndex = 0;
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => `blob:media-${objectUrlIndex++}`),
      revokeObjectURL,
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("image", { status: 200 }));

    const firstSource = "/api/v2/assets/retained/content?v=version-0";
    await loadStableMedia(firstSource);
    const release = retainStableMedia(firstSource);
    for (let index = 1; index <= 300; index += 1) {
      await loadStableMedia(`/api/v2/assets/trimmed-${index}/content?v=version-${index}`);
    }

    expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:media-0");
    release();
    release();
  });
});
