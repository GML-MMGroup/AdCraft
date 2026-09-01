import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StableMediaPreview } from "./StableMediaPreview.tsx";
import { __resetStableMediaCacheForTests } from "./stableMediaCache.ts";

describe("StableMediaPreview", () => {
  afterEach(() => {
    cleanup();
    __resetStableMediaCacheForTests();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shares one fetch when two mounted previews use the same AssetVersion", async () => {
    const createObjectURL = vi.fn(() => "blob:stable-image");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("image", { status: 200 }));
    const source = "/api/v2/assets/asset-1/content?v=version-1";

    render(
      <>
        <StableMediaPreview src={source} alt="first" />
        <StableMediaPreview src={source} alt="second" />
      </>,
    );

    await waitFor(() => expect(screen.getByAltText("first").getAttribute("src")).toBe("blob:stable-image"));
    expect(screen.getByAltText("second").getAttribute("src")).toBe("blob:stable-image");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("hydrates from Cache Storage without a network request", async () => {
    const createObjectURL = vi.fn(() => "blob:persisted-image");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const cache = {
      match: vi.fn().mockResolvedValue(new Response("cached image", { status: 200 })),
      keys: vi.fn().mockResolvedValue([]),
      put: vi.fn(),
      delete: vi.fn(),
    };
    vi.stubGlobal("caches", { open: vi.fn().mockResolvedValue(cache) });
    const fetchMock = vi.spyOn(globalThis, "fetch");

    render(<StableMediaPreview src="/api/v2/assets/asset-2/content?v=version-4" alt="persisted" />);

    await waitFor(() => expect(screen.getByAltText("persisted").getAttribute("src")).toBe("blob:persisted-image"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("defers lazy media until it enters the preload margin", async () => {
    const createObjectURL = vi.fn(() => "blob:lazy-image");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("image", { status: 200 }));
    let observe: ((entries: IntersectionObserverEntry[]) => void) | undefined;
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: (entries: IntersectionObserverEntry[]) => void) {
        observe = callback;
      }

      observe() {}

      disconnect() {}
    });
    render(<StableMediaPreview src="/api/v2/assets/asset-3/content?v=version-5" alt="lazy" loading="lazy" />);

    expect(fetchMock).not.toHaveBeenCalled();
    observe?.([{ isIntersecting: true } as IntersectionObserverEntry]);
    await waitFor(() => expect(screen.getByAltText("lazy").getAttribute("src")).toBe("blob:lazy-image"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("delays media hydration by the requested amount", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("image", { status: 200 }));
    const source = "/api/v2/assets/asset-4/content?v=version-6";

    render(<StableMediaPreview src={source} alt="deferred" deferMs={500} />);
    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(499);
    });
    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
