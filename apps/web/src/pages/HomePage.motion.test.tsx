import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

const startNewProject = vi.fn();
const styles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

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

  reveal(target: Element) {
    this.callback(
      [
        {
          boundingClientRect: target.getBoundingClientRect(),
          intersectionRatio: 0.4,
          intersectionRect: target.getBoundingClientRect(),
          isIntersecting: true,
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
  });

  it("stages the hero statement word by word without changing its accessible text", () => {
    render(<HomePage navigate={vi.fn()} />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "One Sentence Becomes an Ad film.",
    });
    const words = Array.from(
      title.querySelectorAll<HTMLElement>(".home-product-hero__wave-word"),
    );

    expect(words.map((word) => word.textContent)).toEqual([
      "One",
      "Sentence",
      "Becomes",
      "an",
      "Ad",
      "film.",
    ]);
    expect(
      words.map((word) => word.style.getPropertyValue("--home-wave-index")),
    ).toEqual(["0", "1", "2", "3", "4", "5"]);
    expect(
      words.map((word) => word.style.getPropertyValue("--home-wave-delay")),
    ).toEqual(["110ms", "178ms", "246ms", "314ms", "382ms", "450ms"]);
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
    act(() => recentObserver?.reveal(recentSection as Element));

    expect(recentSection?.getAttribute("data-reveal-state")).toBe("visible");
    expect(discoverSection?.getAttribute("data-reveal-state")).toBe("pending");
    expect(recentObserver?.disconnect).toHaveBeenCalledOnce();
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
      /\.home-product-hero__wave-word\s*\{[^}]*animation:[^;}]*home-hero-wave[^;}]*;[^}]*will-change:\s*transform,\s*opacity,\s*filter;/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-wave\s*\{[\s\S]*?transform:\s*translate3d\(0,\s*[^,]+,\s*0\)[\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="pending"\][\s\S]*?opacity:\s*0;/,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="visible"\][\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.home-product-hero__wave-word[\s\S]*?animation:\s*none !important;/,
    );
  });
});
