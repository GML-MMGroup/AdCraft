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
  });

  it("stages the hero as three cohesive lines without splitting the gilded text", () => {
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
    expect(
      lines.map((line) => line.style.getPropertyValue("--home-line-delay")),
    ).toEqual(["100ms", "190ms", "280ms"]);
    expect(title.querySelectorAll(".home-product-hero__wave-word")).toHaveLength(0);
    expect(lines[2]?.children).toHaveLength(0);
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
      /\.home-product-hero__title-line\s*\{[^}]*animation:[^;}]*home-hero-line-wave[^;}]*;[^}]*will-change:\s*transform,\s*opacity;/s,
    );
    expect(styles).toMatch(
      /@keyframes home-hero-line-wave\s*\{[\s\S]*?transform:\s*translate3d\(0,\s*[^,]+,\s*0\)[\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="pending"\][\s\S]*?opacity:\s*0;/,
    );
    expect(styles).toMatch(
      /\.home-reveal-section\[data-reveal-state="visible"\][\s\S]*?opacity:\s*1;/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.home-product-hero__title-line[\s\S]*?animation:\s*none !important;/,
    );
  });
});
