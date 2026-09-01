import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CanvasMediaPreview } from "./CanvasMediaPreview.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CanvasMediaPreview", () => {
  it("renders a direct browser-cacheable image without blob hydration", () => {
    const fetch = vi.fn();
    const createObjectURL = vi.fn(() => "blob:canvas-preview");
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(
      <CanvasMediaPreview
        src="/api/v2/assets/asset-1/renditions/preview-640.webp?v=version-1"
        alt="Campaign preview"
        sizes="(max-width: 480px) 100vw, 320px"
      />,
    );

    const image = screen.getByRole("img", { name: "Campaign preview" });

    expect(image.getAttribute("src")).toBe("/api/v2/assets/asset-1/renditions/preview-640.webp?v=version-1");
    expect(image.getAttribute("loading")).toBe("lazy");
    expect(image.getAttribute("decoding")).toBe("async");
    expect(image.getAttribute("sizes")).toBe("(max-width: 480px) 100vw, 320px");
    expect(image.getAttribute("draggable")).toBe("false");
    expect(fetch).not.toHaveBeenCalled();
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
