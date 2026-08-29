import { act } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { requestNativeVideoFirstFrame } from "./nativeVideoFirstFrame.ts";

afterEach(() => {
  document.body.replaceChildren();
});

describe("requestNativeVideoFirstFrame", () => {
  it("serializes first-frame seeks so mounted videos do not compete for range requests", async () => {
    const first = document.createElement("video");
    const second = document.createElement("video");
    Object.defineProperty(first, "duration", { configurable: true, value: 12 });
    Object.defineProperty(second, "duration", { configurable: true, value: 12 });
    document.body.append(first, second);

    const firstSeek = requestNativeVideoFirstFrame(first);
    const secondSeek = requestNativeVideoFirstFrame(second);

    expect(first.currentTime).toBeCloseTo(0.5);
    expect(second.currentTime).toBe(0);

    await act(async () => {
      first.dispatchEvent(new Event("seeked"));
      await firstSeek;
    });

    expect(second.currentTime).toBeCloseTo(0.5);

    await act(async () => {
      second.dispatchEvent(new Event("seeked"));
      await secondSeek;
    });
  });
});
