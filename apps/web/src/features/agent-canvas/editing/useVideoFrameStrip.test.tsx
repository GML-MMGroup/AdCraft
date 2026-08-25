import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  frameCacheKey,
  frameSampleTimes,
  useVideoFrameStrip,
} from "./useVideoFrameStrip.ts";

describe("useVideoFrameStrip", () => {
  it("places frame requests at fixed-width cell midpoints", () => {
    expect(frameSampleTimes({
      start: 2,
      end: 8,
      renderedWidth: 480,
      targetFrameWidth: 80,
    })).toEqual([2.5, 3.5, 4.5, 5.5, 6.5, 7.5]);
  });

  it("rounds frame cache keys to centiseconds", () => {
    expect(frameCacheKey("asset-1", 2.504, 80, 45)).toBe("asset-1:2.50:80x45");
  });

  it("reuses cached samples for a later matching request", async () => {
    const request = {
      assetId: "asset-cache-reuse",
      mediaUrl: "https://cdn.example.test/video.mp4",
      previewUrl: "https://cdn.example.test/preview.jpg",
      sourceStart: 0,
      sourceEnd: 2,
      renderedWidth: 160,
      active: true,
    };
    const firstSampler = vi.fn(async (_url: string, seconds: number) => `blob:first-${seconds}`);
    const first = renderHook(() => useVideoFrameStrip(request, firstSampler));

    await waitFor(() => expect(first.result.current).toEqual([
      { sourceSeconds: 0.5, url: "blob:first-0.5", sampled: true },
      { sourceSeconds: 1.5, url: "blob:first-1.5", sampled: true },
    ]));
    first.unmount();

    const secondSampler = vi.fn(async () => "blob:unexpected");
    const second = renderHook(() => useVideoFrameStrip(request, secondSampler));

    expect(second.result.current).toEqual([
      { sourceSeconds: 0.5, url: "blob:first-0.5", sampled: true },
      { sourceSeconds: 1.5, url: "blob:first-1.5", sampled: true },
    ]);
    expect(secondSampler).not.toHaveBeenCalled();
  });

  it("keeps every requested frame on the preview when sampling fails", async () => {
    const previewUrl = "https://cdn.example.test/preview.jpg";
    const rejectingSampler = vi.fn(async () => {
      throw new Error("video decode failed");
    });
    const { result } = renderHook(() => useVideoFrameStrip({
      assetId: "asset-fallback",
      mediaUrl: "https://cdn.example.test/video.mp4",
      previewUrl,
      sourceStart: 2,
      sourceEnd: 8,
      renderedWidth: 480,
      active: true,
    }, rejectingSampler));

    await waitFor(() => expect(rejectingSampler).toHaveBeenCalledTimes(6));
    expect(result.current).toEqual([
      { sourceSeconds: 2.5, url: previewUrl, sampled: false },
      { sourceSeconds: 3.5, url: previewUrl, sampled: false },
      { sourceSeconds: 4.5, url: previewUrl, sampled: false },
      { sourceSeconds: 5.5, url: previewUrl, sampled: false },
      { sourceSeconds: 6.5, url: previewUrl, sampled: false },
      { sourceSeconds: 7.5, url: previewUrl, sampled: false },
    ]);
  });
});
