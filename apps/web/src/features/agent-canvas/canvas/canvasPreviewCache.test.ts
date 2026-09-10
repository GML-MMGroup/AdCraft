import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearCanvasPreviewCache,
  getCanvasPreviewStatus,
  preloadCanvasPreview,
} from "./canvasPreviewCache.ts";

class MockImage {
  static instances: MockImage[] = [];
  src = "";
  decoding = "async";
  decode = vi.fn(async () => undefined);

  constructor() {
    MockImage.instances.push(this);
  }
}

describe("canvasPreviewCache", () => {
  afterEach(() => {
    clearCanvasPreviewCache();
    MockImage.instances = [];
    vi.unstubAllGlobals();
  });

  it("deduplicates concurrent versioned rendition preloads", async () => {
    vi.stubGlobal("Image", MockImage);
    const url = "/api/v2/assets/a/renditions/preview-640.webp?v=v1";

    const first = preloadCanvasPreview(url);
    const second = preloadCanvasPreview(url);
    await Promise.all([first, second]);

    expect(MockImage.instances).toHaveLength(1);
    expect(MockImage.instances[0]?.src).toBe(url);
    expect(getCanvasPreviewStatus(url)).toBe("ready");
  });

  it("treats a new version URL as a separate cache entry", async () => {
    vi.stubGlobal("Image", MockImage);
    await preloadCanvasPreview("/preview/a.webp?v=v1");
    await preloadCanvasPreview("/preview/a.webp?v=v2");

    expect(MockImage.instances).toHaveLength(2);
    expect(getCanvasPreviewStatus("/preview/a.webp?v=v1")).toBe("ready");
    expect(getCanvasPreviewStatus("/preview/a.webp?v=v2")).toBe("ready");
  });
});
