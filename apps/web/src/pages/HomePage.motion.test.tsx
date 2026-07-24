import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
const originalFontsDescriptor = Object.getOwnPropertyDescriptor(document, "fonts");

vi.mock("../AppContextValue", () => ({
  useApp: () => ({ startNewProject }),
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

  it("stages one continuous character wave across the three title lines", () => {
    render(<HomePage navigate={vi.fn()} />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "One Sentence Becomes an Ad film.",
    });
    const lines = Array.from(
      title.querySelectorAll<HTMLElement>(".home-product-hero__title-line"),
    );

    expect(lines.map((line) => line.textContent)).toEqual([
      "One Sentence",
      "Becomes an",
      "Ad film.",
    ]);

    const characters = Array.from(
      title.querySelectorAll<HTMLElement>(".home-product-hero__character"),
    );
    expect(characters).toHaveLength(30);
    expect(
      characters.map((character) => character.dataset.characterIndex),
    ).toEqual(Array.from({ length: 30 }, (_, index) => String(index)));
    expect(
      characters.slice(0, 4).map((character) => (
        character.style.getPropertyValue("--home-character-delay")
      )),
    ).toEqual(["80ms", "108ms", "136ms", "164ms"]);
    expect(
      characters.at(-1)?.style.getPropertyValue("--home-character-delay"),
    ).toBe("892ms");
    expect(lines[2]?.querySelectorAll(".home-product-hero__accent-glyph")).toHaveLength(8);
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

  it("uses compositor-friendly entrance animations with reduced-motion coverage", () => {
    expect(styles).toMatch(
      /\.home-product-hero\.is-motion-ready\s+\.home-product-hero__character\s*\{[^}]*animation:[^;}]*home-hero-character-wave/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-character-wave\s*\{[\s\S]*?translate3d\(0,\s*12px,\s*0\)[\s\S]*?translate3d\(0,\s*-4px,\s*0\)[\s\S]*?translate3d\(0,\s*2px,\s*0\)/,
    );
    expect(styles).not.toMatch(/home-hero-line-wave/);
    expect(styles).not.toMatch(
      /\.home-product-hero__character\s*\{[^}]*will-change:/s,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="pending"\][\s\S]*?opacity:\s*0;/,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="visible"\][\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.home-product-hero__character[\s\S]*?animation:\s*none !important;[\s\S]*?opacity:\s*1 !important;/,
    );
  });
});
