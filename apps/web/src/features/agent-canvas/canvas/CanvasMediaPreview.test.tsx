import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CanvasMediaPreview } from "./CanvasMediaPreview.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CanvasMediaPreview", () => {
  it("hydrates versioned images through the shared stable media cache", async () => {
    const fetch = vi.fn(async () => new Response("image", { status: 200 }));
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

    await waitFor(() => expect(screen.getByRole("img", { name: "Campaign preview" }).getAttribute("src"))
      .toBe("blob:canvas-preview"));
    const image = screen.getByRole("img", { name: "Campaign preview" });

    expect(image.getAttribute("loading")).toBe("eager");
    expect(image.getAttribute("decoding")).toBe("async");
    expect(image.getAttribute("sizes")).toBe("(max-width: 480px) 100vw, 320px");
    expect(image.getAttribute("draggable")).toBe("false");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("keeps a warm versioned image immediately available after remount", async () => {
    const fetch = vi.fn(async () => new Response("image", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:warm-preview"), revokeObjectURL: vi.fn() });
    const source = "/api/v2/assets/asset-warm/renditions/preview-640.webp?v=version-warm";
    const view = render(<CanvasMediaPreview src={source} alt="Warm preview" />);

    await waitFor(() => expect(screen.getByRole("img", { name: "Warm preview" }).getAttribute("src"))
      .toBe("blob:warm-preview"));
    view.unmount();
    render(<CanvasMediaPreview src={source} alt="Warm preview" />);

    expect(screen.getByRole("img", { name: "Warm preview" }).getAttribute("src")).toBe("blob:warm-preview");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("uses eager loading and a stable canvas size by default", () => {
    render(
      <CanvasMediaPreview
        src="/api/v2/assets/asset-2/preview?v=version-2"
        alt="Canvas preview"
      />,
    );

    const image = screen.getByRole("img", { name: "Canvas preview" });
    expect(image.getAttribute("loading")).toBe("eager");
    expect(image.getAttribute("sizes")).toBe("360px");
  });

  it("renders immediately when no generation reveal token is present", () => {
    render(<CanvasMediaPreview src="/media/history.webp" alt="Historical preview" />);

    const image = screen.getByRole("img", { name: "Historical preview" });
    expect(image.classList.contains("agent-canvas-node__media--awaiting-generation-reveal")).toBe(false);
    expect(image.classList.contains("agent-canvas-node__media--generation-revealed")).toBe(false);
  });

  it("waits for native image load before revealing a generated result", () => {
    const onLoad = vi.fn();
    render(
      <CanvasMediaPreview
        src="/media/generated.webp"
        alt="Generated preview"
        revealToken="image-node:image-asset"
        onLoad={onLoad}
      />,
    );

    const image = screen.getByRole("img", { name: "Generated preview" });
    expect(image.classList.contains("agent-canvas-node__media--awaiting-generation-reveal")).toBe(true);
    expect(image.classList.contains("agent-canvas-node__media--generation-revealed")).toBe(false);

    fireEvent.load(image);

    expect(image.classList.contains("agent-canvas-node__media--awaiting-generation-reveal")).toBe(false);
    expect(image.classList.contains("agent-canvas-node__media--generation-revealed")).toBe(true);
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("waits again when the generation source or token changes", () => {
    const view = render(
      <CanvasMediaPreview
        src="/media/generated-a.webp"
        alt="Generated preview"
        revealToken="image-node:image-asset-a"
      />,
    );
    const image = screen.getByRole("img", { name: "Generated preview" });
    fireEvent.load(image);
    expect(image.classList.contains("agent-canvas-node__media--generation-revealed")).toBe(true);

    view.rerender(
      <CanvasMediaPreview
        src="/media/generated-b.webp"
        alt="Generated preview"
        revealToken="image-node:image-asset-a"
      />,
    );
    expect(image.classList.contains("agent-canvas-node__media--awaiting-generation-reveal")).toBe(true);

    fireEvent.load(image);
    view.rerender(
      <CanvasMediaPreview
        src="/media/generated-b.webp"
        alt="Generated preview"
        revealToken="image-node:image-asset-b"
      />,
    );
    expect(image.classList.contains("agent-canvas-node__media--awaiting-generation-reveal")).toBe(true);
  });
});
