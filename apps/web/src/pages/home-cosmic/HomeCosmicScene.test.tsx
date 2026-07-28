import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomeCosmicScene } from "./HomeCosmicScene";

const rendererMocks = vi.hoisted(() => ({
  create: vi.fn(),
  dispose: vi.fn(),
  renderFrame: vi.fn(),
  resize: vi.fn(),
}));

vi.mock("./homeCosmicRenderer", () => ({
  createHomeCosmicRenderer: rendererMocks.create,
}));

let animationFrameCallbacks: Map<number, FrameRequestCallback>;
let nextAnimationFrameId: number;

function runAnimationFrame(timestamp: number) {
  const callbacks = Array.from(animationFrameCallbacks.values());
  animationFrameCallbacks.clear();
  callbacks.forEach((callback) => callback(timestamp));
}

function setDocumentTheme(theme: "light" | "dark") {
  act(() => {
    document.documentElement.dataset.theme = theme;
  });
}

function setScrollY(value: number) {
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    value,
  });
}

function installMotionPreference(reduced: boolean) {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    addEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => listeners.add(listener),
    addListener: vi.fn(),
    dispatchEvent: vi.fn(),
    matches: reduced,
    media: "(prefers-reduced-motion: reduce)",
    onchange: null,
    removeEventListener: (
      _type: string,
      listener: (event: MediaQueryListEvent) => void,
    ) => listeners.delete(listener),
    removeListener: vi.fn(),
  })));
}

describe("HomeCosmicScene", () => {
  beforeEach(() => {
    animationFrameCallbacks = new Map();
    nextAnimationFrameId = 1;
    rendererMocks.create.mockReset();
    rendererMocks.dispose.mockReset();
    rendererMocks.renderFrame.mockReset();
    rendererMocks.resize.mockReset();
    rendererMocks.create.mockReturnValue({
      dispose: rendererMocks.dispose,
      renderFrame: rendererMocks.renderFrame,
      resize: rendererMocks.resize,
    });
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        const id = nextAnimationFrameId;
        nextAnimationFrameId += 1;
        animationFrameCallbacks.set(id, callback);
        return id;
      }),
    );
    vi.stubGlobal(
      "cancelAnimationFrame",
      vi.fn((id: number) => {
        animationFrameCallbacks.delete(id);
      }),
    );
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    setScrollY(0);
    setDocumentTheme("light");
    installMotionPreference(false);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    document.documentElement.dataset.theme = "light";
  });

  it("renders a decorative fixed image layer and canvas", () => {
    setDocumentTheme("dark");
    const view = render(<HomeCosmicScene />);
    const scene = view.container.querySelector(".home-cosmic-scene");
    const ring = view.container.querySelector(
      ".home-cosmic-scene__ring",
    );
    const canvas = view.container.querySelector(
      ".home-cosmic-scene__particles",
    );

    expect(scene?.getAttribute("aria-hidden")).toBe("true");
    expect(ring).not.toBeNull();
    expect(canvas).toBeInstanceOf(HTMLCanvasElement);
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(canvas?.getAttribute("tabindex")).toBe("-1");
  });

  it("does not mount or create cosmic media in light theme", async () => {
    const view = render(<HomeCosmicScene />);
    await act(async () => Promise.resolve());

    expect(
      view.container.querySelector(".home-cosmic-scene"),
    ).toBeNull();
    expect(
      view.container.querySelector(".home-cosmic-scene__ring"),
    ).toBeNull();
    expect(rendererMocks.create).not.toHaveBeenCalled();
    expect(animationFrameCallbacks.size).toBe(0);
  });

  it("starts rendering after the document changes to dark theme", async () => {
    const view = render(<HomeCosmicScene />);
    setDocumentTheme("dark");

    await waitFor(() => {
      expect(rendererMocks.create).toHaveBeenCalledOnce();
    });

    act(() => runAnimationFrame(16));
    expect(rendererMocks.renderFrame).toHaveBeenCalledOnce();
    expect(rendererMocks.resize).toHaveBeenCalled();
    expect(
      view.container
        .querySelector(".home-cosmic-scene")
        ?.classList.contains("is-active"),
    ).toBe(true);
  });

  it("unmounts cosmic media and disposes WebGL after switching to light", async () => {
    setDocumentTheme("dark");
    const view = render(<HomeCosmicScene />);
    await waitFor(() => {
      expect(rendererMocks.create).toHaveBeenCalledOnce();
    });

    setDocumentTheme("light");

    await waitFor(() => {
      expect(
        view.container.querySelector(".home-cosmic-scene"),
      ).toBeNull();
      expect(rendererMocks.dispose).toHaveBeenCalledOnce();
    });
    expect(animationFrameCallbacks.size).toBe(0);
  });

  it("uses scroll direction to update the ring transform", async () => {
    setDocumentTheme("dark");
    const view = render(<HomeCosmicScene />);
    await waitFor(() => {
      expect(rendererMocks.create).toHaveBeenCalledOnce();
    });

    act(() => runAnimationFrame(16));
    const ring = view.container.querySelector<HTMLElement>(
      ".home-cosmic-scene__ring",
    );
    const beforeScroll = ring?.style.transform;

    setScrollY(240);
    act(() => {
      window.dispatchEvent(new Event("scroll"));
      runAnimationFrame(32);
    });

    expect(ring?.style.transform).not.toBe(beforeScroll);
    expect(ring?.style.transform).toContain("rotate(");
  });

  it("keeps a static image and skips WebGL for reduced motion", async () => {
    installMotionPreference(true);
    setDocumentTheme("dark");
    const view = render(<HomeCosmicScene />);
    await act(async () => Promise.resolve());

    expect(rendererMocks.create).not.toHaveBeenCalled();
    expect(
      view.container
        .querySelector(".home-cosmic-scene")
        ?.classList.contains("is-static"),
    ).toBe(true);
  });

  it("pauses while hidden and resumes when visible", async () => {
    setDocumentTheme("dark");
    render(<HomeCosmicScene />);
    await waitFor(() => {
      expect(rendererMocks.create).toHaveBeenCalledOnce();
    });

    act(() => runAnimationFrame(16));
    expect(rendererMocks.renderFrame).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(animationFrameCallbacks.size).toBe(0);

    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
      runAnimationFrame(32);
    });
    expect(rendererMocks.renderFrame).toHaveBeenCalledTimes(2);
  });

  it("falls back to the image when WebGL initialization fails", async () => {
    rendererMocks.create.mockImplementation(() => {
      throw new Error("WebGL unavailable");
    });
    setDocumentTheme("dark");
    const view = render(<HomeCosmicScene />);

    await waitFor(() => {
      expect(
        view.container
          .querySelector(".home-cosmic-scene")
          ?.classList.contains("is-fallback"),
      ).toBe(true);
    });
    expect(animationFrameCallbacks.size).toBeGreaterThan(0);
  });

  it("falls back on context loss and disposes resources on unmount", async () => {
    let notifyContextLost: (() => void) | undefined;
    rendererMocks.create.mockImplementation(
      (_canvas: HTMLCanvasElement, onContextLost: () => void) => {
        notifyContextLost = onContextLost;
        return {
          dispose: rendererMocks.dispose,
          renderFrame: rendererMocks.renderFrame,
          resize: rendererMocks.resize,
        };
      },
    );
    setDocumentTheme("dark");
    const view = render(<HomeCosmicScene />);
    await waitFor(() => {
      expect(rendererMocks.create).toHaveBeenCalledOnce();
    });

    act(() => notifyContextLost?.());
    expect(
      view.container
        .querySelector(".home-cosmic-scene")
        ?.classList.contains("is-fallback"),
    ).toBe(true);

    view.unmount();
    expect(rendererMocks.dispose).toHaveBeenCalledOnce();
    expect(animationFrameCallbacks.size).toBe(0);
  });
});
