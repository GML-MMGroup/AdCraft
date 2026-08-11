import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/pages/home.css"), "utf8");
const homeSource = readFileSync(
  resolve(process.cwd(), "src/pages/HomePage.tsx"),
  "utf8",
);
const originalFontsDescriptor = Object.getOwnPropertyDescriptor(document, "fonts");

vi.mock("../app/useHealth", () => ({
  useHealth: () => ({ startNewProject }),
}));

type IntersectionCallback = IntersectionObserverCallback;

class IntersectionObserverMock {
  static instances: IntersectionObserverMock[] = [];

  readonly callback: IntersectionCallback;
  readonly observe = vi.fn();
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
  readonly takeRecords = vi.fn(() => []);
  readonly root = null;
  readonly rootMargin = "0px";
  readonly thresholds = [0];

  constructor(callback: IntersectionCallback) {
    this.callback = callback;
    IntersectionObserverMock.instances.push(this);
  }

  setIntersection(
    target: Element,
    { isIntersecting, ratio }: { isIntersecting: boolean; ratio: number },
  ) {
    this.callback(
      [
        {
          boundingClientRect: target.getBoundingClientRect(),
          intersectionRatio: ratio,
          intersectionRect: target.getBoundingClientRect(),
          isIntersecting,
          rootBounds: null,
          target,
          time: 0,
        },
      ],
      this as unknown as IntersectionObserver,
    );
  }
}

describe("HomePage motion", () => {
  beforeEach(() => {
    startNewProject.mockReset();
    IntersectionObserverMock.instances = [];
    document.documentElement.dataset.theme = "light";
    vi.stubGlobal("IntersectionObserver", IntersectionObserverMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    if (originalFontsDescriptor) {
      Object.defineProperty(document, "fonts", originalFontsDescriptor);
    } else {
      Reflect.deleteProperty(document, "fonts");
    }
  });

  it("renders the title as three complete lines for the spotlight focus reveal", () => {
    render(<HomePage navigate={vi.fn()} />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "One Sentence Becomes an Ad film.",
    });
    const lines = Array.from(
      title.querySelectorAll<HTMLElement>(".home-product-hero__title-line"),
    );

    expect(lines.map((line) => line.textContent)).toEqual([
      "ONE SENTENCE",
      "BECOMES AN",
      "Ad film.",
    ]);

    expect(lines[2]?.getAttribute("data-accent-text")).toBe("Ad film.");
    expect(title.querySelectorAll(".home-product-hero__character")).toHaveLength(0);
  });

  it("starts the hero motion only after fonts and two paint frames are ready", async () => {
    let resolveFonts: (() => void) | undefined;
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: {
        ready: new Promise<void>((resolve) => {
          resolveFonts = resolve;
        }),
      },
    });
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      callback(0);
      return requestFrame.mock.calls.length;
    });
    vi.stubGlobal("requestAnimationFrame", requestFrame);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());

    render(<HomePage navigate={vi.fn()} />);

    const hero = screen
      .getByRole("heading", {
        level: 1,
        name: "One Sentence Becomes an Ad film.",
      })
      .closest("section");
    expect(hero?.classList.contains("is-motion-ready")).toBe(false);

    await act(async () => {
      resolveFonts?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(requestFrame).toHaveBeenCalledTimes(2);
    expect(hero?.classList.contains("is-motion-ready")).toBe(true);
  });

  it("reveals each content region once when it first enters the viewport", () => {
    render(<HomePage navigate={vi.fn()} />);

    const recentSection = screen
      .getByRole("heading", { level: 2, name: "Recent Projects" })
      .closest("section");
    const discoverSection = screen
      .getByRole("heading", { level: 2, name: "Discover" })
      .closest("section");

    expect(recentSection).not.toBeNull();
    expect(discoverSection).not.toBeNull();
    expect(recentSection?.getAttribute("data-reveal-state")).toBe("pending");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");
    expect(recentSection?.querySelectorAll(".recent-card[data-reveal-item]")).toHaveLength(4);
    expect(IntersectionObserverMock.instances).toHaveLength(2);

    const recentObserver = IntersectionObserverMock.instances[0];
    act(() => recentObserver?.setIntersection(
      recentSection as Element,
      { isIntersecting: true, ratio: 0.4 },
    ));

    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");
    expect(recentObserver?.disconnect).toHaveBeenCalledOnce();

    act(() => recentObserver?.setIntersection(
      recentSection as Element,
      { isIntersecting: false, ratio: 0 },
    ));
    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
  });

  it("replays Discover after it fully leaves and re-enters the viewport", () => {
    render(<HomePage navigate={vi.fn()} />);

    const discoverSection = screen
      .getByRole("heading", { level: 2, name: "Discover" })
      .closest("section");
    const discoverObserver = IntersectionObserverMock.instances[1];

    act(() => discoverObserver?.setIntersection(
      discoverSection as Element,
      { isIntersecting: true, ratio: 0.4 },
    ));
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("visible");

    act(() => discoverObserver?.setIntersection(
      discoverSection as Element,
      { isIntersecting: false, ratio: 0 },
    ));
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");

    act(() => discoverObserver?.setIntersection(
      discoverSection as Element,
      { isIntersecting: true, ratio: 0.4 },
    ));
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverObserver?.disconnect).not.toHaveBeenCalled();
  });

  it("shows content immediately when the user prefers reduced motion", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(prefers-reduced-motion: reduce)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );

    render(<HomePage navigate={vi.fn()} />);

    const recentSection = screen
      .getByRole("heading", { level: 2, name: "Recent Projects" })
      .closest("section");
    const discoverSection = screen
      .getByRole("heading", { level: 2, name: "Discover" })
      .closest("section");

    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(IntersectionObserverMock.instances).toHaveLength(0);
  });

  it("uses a non-linear spotlight focus entrance with reduced-motion coverage", () => {
    expect(styles).toMatch(
      /\.home-product-hero__title-line\s*\{[^}]*opacity:\s*0\.03;[^}]*filter:\s*blur\(20px\);[^}]*transform:\s*scale\(0\.968\);/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero__description\s*\{[^}]*opacity:\s*1;/s,
    );
    expect(styles).toMatch(
      /\.home-product-film\s*\{[^}]*opacity:\s*1;/s,
    );
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-ready\s+\.home-product-hero__title-line\s*\{[^}]*animation:[^;}]*home-hero-spotlight-focus/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-spotlight-focus\s*\{[\s\S]*?blur\(20px\)[\s\S]*?blur\(14px\)[\s\S]*?blur\(2px\)[\s\S]*?filter:\s*none;/,
    );
    expect(styles).toMatch(
      /\.home-product-hero__title-line\s*\{[^}]*will-change:\s*filter,\s*opacity,\s*transform;/s,
    );
    expect(styles).not.toMatch(
      /\.home-product-hero\.is-motion-ready\s+\.home-product-hero__(description|create-stage|film)\s*\{/,
    );
    expect(styles).not.toContain("home-hero-support-in");
    expect(styles).not.toContain("home-hero-media-in");
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="pending"\][\s\S]*?opacity:\s*0;/,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="visible"\][\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.home-product-hero__title-line[\s\S]*?animation:\s*none !important;[\s\S]*?opacity:\s*1 !important;[\s\S]*?filter:\s*none !important;/,
    );
  });

  it("does not mount an animated cosmic layer over the shared static background", () => {
    document.documentElement.dataset.theme = "dark";
    const view = render(<HomePage navigate={vi.fn()} />);

    expect(
      view.container.querySelectorAll(".home-cosmic-scene"),
    ).toHaveLength(0);
    expect(homeSource).not.toContain("HomeCosmicScene");
    expect(homeSource).not.toContain("home-cosmic");
  });

  it("does not load a WebGL renderer for the static Home background", () => {
    expect(homeSource).not.toMatch(/from\s+["']three["']/);
    expect(homeSource).not.toContain("homeCosmicRenderer");
  });
});
