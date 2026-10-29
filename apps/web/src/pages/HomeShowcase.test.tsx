import { Profiler } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n/locale";
import { HomeShowcase } from "./HomeShowcase";

describe("HomeShowcase", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders the Home composition without functional controls in static mode", () => {
    const view = render(<HomeShowcase mode="static" hasIntroVideo productVideoUrl="/assets/home-hero-loop.mp4" />);

    expect(view.container.querySelector("video")).toBeNull();
    expect(view.container.querySelector(".home-product-hero__poster")?.getAttribute("src")).toBe("/assets/home-hero-poster.webp");
    expect(screen.queryByRole("button", { name: "Unmute" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "One Sentence Becomes an Ad film." })).toBeTruthy();
    expect(screen.getByTestId("home-hero-accent").textContent).toBe("Ad film.");
    expect(screen.getByTestId("home-hero-accent").querySelector("svg")).toBeNull();
    expect(screen.queryByRole("button", { name: /create your project/i })).toBeNull();
    expect(screen.queryByText("Preview Case")).toBeNull();
    expect(screen.queryByText("All")).toBeNull();
    expect(screen.queryByText("Pick up the latest creative thread.")).toBeNull();
    expect(screen.getByRole("heading", { name: "Recent Projects" }).parentElement?.querySelector("p")).toBeNull();
    expect(screen.queryByText("References, templates, and generated video ideas.")).toBeNull();
    expect(screen.getByRole("heading", { name: "Discover" }).parentElement?.querySelector("p")).toBeNull();
  });

  it("renders two linked Discover tracks and supports keyboard navigation", () => {
    const openPreview = vi.fn();
    const view = render(
      <HomeShowcase
        mode="interactive"
        interactions={{
          createProject: vi.fn(),
          openPreview,
          closePreview: vi.fn(),
        }}
      />,
    );

    const orbit = within(view.container).getByLabelText("Discover inspiration gallery");
    const upperTrack = orbit.querySelector("[data-discover-track=upper]");
    const lowerTrack = orbit.querySelector("[data-discover-track=lower]");
    const card = within(upperTrack as HTMLElement).getByRole("button", { name: "upper Scene Extension" });

    expect(orbit.getAttribute("aria-roledescription")).toBe("carousel");
    expect(screen.queryByRole("button", { name: "All" })).toBeNull();
    expect(upperTrack).toBeTruthy();
    expect(lowerTrack).toBeTruthy();
    expect(orbit.dataset.activeIndex).toContain("upper:3");
    expect(orbit.dataset.activeIndex).toContain("lower:2");
    expect(card.getAttribute("aria-current")).toBe("true");
    expect(card.classList.contains("is-selected")).toBe(false);
    expect(within(lowerTrack as HTMLElement).getByRole("button", { name: "lower Poster Motion" }).getAttribute("aria-current")).toBe("true");

    fireEvent.keyDown(card, { key: "ArrowRight" });
    expect(orbit.dataset.activeIndex).not.toContain("upper:3");
    expect(card.getAttribute("aria-current")).toBe("false");

    fireEvent.keyDown(card, { key: "ArrowLeft" });
    expect(orbit.dataset.activeIndex).toContain("upper:3");

    const lowerCard = within(lowerTrack as HTMLElement).getByRole("button", { name: "lower Product Aura" });
    fireEvent.click(lowerCard);
    expect(card.getAttribute("aria-current")).toBe("true");
    expect(card.classList.contains("is-selected")).toBe(false);
    expect(lowerCard.getAttribute("aria-current")).toBe("true");
    expect(lowerCard.classList.contains("is-selected")).toBe(true);
    expect(orbit.dataset.activeIndex).toContain("upper:3");
    expect(orbit.dataset.activeIndex).toContain("lower:4");

    fireEvent.click(card);
    expect(openPreview).toHaveBeenCalledTimes(1);
  });

  it.each(["canPlay", "playing"])("keeps the poster visible until the video emits %s", (event) => {
    const view = render(<HomeShowcase mode="interactive" hasIntroVideo productVideoUrl="/assets/home-hero-loop.mp4" />);
    const media = view.container.querySelector<HTMLElement>(".home-product-hero__media")!;
    const video = media.querySelector("video")!;

    expect(media.dataset.videoReady).toBe("false");
    expect(media.querySelector("img")?.getAttribute("src")).toBe("/assets/home-hero-poster.webp");
    expect(video.poster).toContain("/assets/home-hero-poster.webp");
    expect(video.autoplay).toBe(true);
    expect(video.loop).toBe(true);
    expect(video.muted).toBe(true);
    expect(video.playsInline).toBe(true);

    if (event === "canPlay") fireEvent.canPlay(video);
    else fireEvent.playing(video);
    expect(media.dataset.videoReady).toBe("true");
  });

  it("returns to the poster and removes the audio control on video failure", () => {
    const onError = vi.fn();
    const view = render(<HomeShowcase mode="interactive" hasIntroVideo productVideoUrl="/film.mp4" onProductVideoError={onError} />);
    const video = view.container.querySelector("video")!;
    fireEvent.canPlay(video);
    fireEvent.error(video);

    expect(onError).toHaveBeenCalledOnce();
    expect(view.container.querySelector("video")).toBeNull();
    expect(view.container.querySelector(".home-product-hero__poster")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Unmute" })).toBeNull();
  });

  it("recognizes a video failure that happened before its effects mounted", () => {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "error");
    Object.defineProperty(HTMLMediaElement.prototype, "error", {
      configurable: true,
      value: { code: 4, message: "Unsupported media" },
    });
    try {
      const view = render(<HomeShowcase mode="interactive" hasIntroVideo productVideoUrl="/film.mp4" />);
      expect(view.container.querySelector("video")).toBeNull();
      expect(view.container.querySelector(".home-product-hero__poster")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Unmute" })).toBeNull();
    } finally {
      if (descriptor) Object.defineProperty(HTMLMediaElement.prototype, "error", descriptor);
      else Reflect.deleteProperty(HTMLMediaElement.prototype, "error");
    }
  });

  it.each([
    ["en-US", "Unmute", "Mute"],
    ["zh-CN", "取消静音", "静音"],
  ] as const)("toggles audio with localized labels in %s and resumes paused playback", (locale, unmute, mute) => {
    const view = render(
      <LocaleProvider initialLocale={locale}>
        <HomeShowcase mode="interactive" hasIntroVideo productVideoUrl="/film.mp4" />
      </LocaleProvider>,
    );
    const video = view.container.querySelector("video")!;
    const button = screen.getByRole("button", { name: unmute });
    expect(button.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(button);
    expect(video.muted).toBe(false);
    expect(video.play).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: mute }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(button);
    expect(video.muted).toBe(true);
    expect(screen.getByRole("button", { name: unmute }).getAttribute("aria-pressed")).toBe("false");
  });

  it("pauses and mutes offscreen, then resumes muted when the hero returns", () => {
    let notifyIntersection: ((entries: IntersectionObserverEntry[]) => void) | undefined;
    let disconnect = vi.fn();
    class MockIntersectionObserver {
      constructor(private readonly callback: IntersectionObserverCallback) {}

      observe(target: Element) {
        if (target.classList.contains("home-product-hero")) {
          notifyIntersection = this.callback;
          disconnect = this.disconnect;
        }
      }

      disconnect = vi.fn();
    }
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

    const view = render(
      <HomeShowcase
        mode="interactive"
        hasIntroVideo
        productVideoUrl="/assets/home-hero-loop.mp4"
      />,
    );
    const hero = view.container.querySelector(".home-product-hero")!;
    const video = hero.querySelector("video")!;
    fireEvent.click(screen.getByRole("button", { name: "Unmute" }));
    expect(video.muted).toBe(false);

    act(() => {
      notifyIntersection?.([{ target: hero, isIntersecting: false } as IntersectionObserverEntry]);
    });
    expect(video.pause).toHaveBeenCalledOnce();
    expect(video.muted).toBe(true);
    expect(screen.getByRole("button", { name: "Unmute" }).getAttribute("aria-pressed")).toBe("false");

    vi.mocked(video.play).mockClear();
    act(() => {
      notifyIntersection?.([{ target: hero, isIntersecting: true } as IntersectionObserverEntry]);
    });
    expect(video.play).toHaveBeenCalledOnce();
    expect(video.muted).toBe(true);
    view.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it.each(["window", "container"])("updates scroll progress on the %s once per frame without rerendering", (scrollMode) => {
    let nextFrame: FrameRequestCallback | undefined;
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      nextFrame = callback;
      return 1;
    });
    const cancelFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", requestFrame);
    vi.stubGlobal("cancelAnimationFrame", cancelFrame);
    const onRender = vi.fn();
    const view = render(
      <div style={{ overflowY: scrollMode === "container" ? "auto" : "visible" }}>
        <Profiler id="hero" onRender={onRender}>
          <HomeShowcase mode="interactive" />
        </Profiler>
      </div>,
    );
    const hero = view.container.querySelector<HTMLElement>(".home-product-hero")!;
    const content = hero.querySelector<HTMLElement>(".home-product-hero__content")!;
    const scrollTarget = scrollMode === "container" ? hero.parentElement!.parentElement! : window;
    const rootTop = scrollMode === "container" ? 100 : 0;
    if (scrollTarget instanceof HTMLElement) {
      vi.spyOn(scrollTarget, "getBoundingClientRect").mockReturnValue(new DOMRect(0, rootTop, 1440, 900));
    }
    let scroll = 0;
    vi.spyOn(hero, "getBoundingClientRect").mockImplementation(() => new DOMRect(0, rootTop - scroll, 1440, 900));
    onRender.mockClear();
    expect(hero.style.getPropertyValue("--hero-progress")).toBe("0");

    scroll = 450;
    fireEvent.scroll(scrollTarget);
    fireEvent.scroll(scrollTarget);
    expect(requestFrame).toHaveBeenCalledOnce();
    act(() => nextFrame?.(0));
    expect(hero.style.getPropertyValue("--hero-progress")).toBe("0.5");
    expect(content.inert).toBe(false);

    scroll = 540;
    fireEvent.scroll(scrollTarget);
    act(() => nextFrame?.(16));
    expect(hero.style.getPropertyValue("--hero-progress")).toBe("0.6");
    expect(content.inert).toBe(true);

    scroll = 1200;
    fireEvent.scroll(scrollTarget);
    act(() => nextFrame?.(32));
    expect(hero.style.getPropertyValue("--hero-progress")).toBe("1");

    scroll = -100;
    fireEvent.scroll(scrollTarget);
    act(() => nextFrame?.(48));
    expect(hero.style.getPropertyValue("--hero-progress")).toBe("0");
    expect(content.inert).toBe(false);
    expect(onRender).not.toHaveBeenCalled();

    fireEvent.scroll(scrollTarget);
    view.unmount();
    expect(cancelFrame).toHaveBeenCalledWith(1);
    requestFrame.mockClear();
    fireEvent.scroll(scrollTarget);
    expect(requestFrame).not.toHaveBeenCalled();
  });

  it("uses only the poster and leaves text visible when reduced motion changes", () => {
    const query = new EventTarget() as EventTarget & { matches: boolean };
    query.matches = false;
    vi.stubGlobal("matchMedia", vi.fn(() => query));
    const view = render(<HomeShowcase mode="interactive" hasIntroVideo productVideoUrl="/film.mp4" heroMotionReady />);
    const hero = view.container.querySelector<HTMLElement>(".home-product-hero")!;
    const video = hero.querySelector("video")!;
    expect(video).toBeTruthy();

    act(() => {
      query.matches = true;
      query.dispatchEvent(new Event("change"));
    });
    expect(video.pause).toHaveBeenCalled();
    expect(hero.querySelector("video")).toBeNull();
    expect(hero.querySelector(".home-product-hero__poster")).toBeTruthy();
    expect(hero.classList.contains("is-motion-enabled")).toBe(false);
    expect(hero.style.getPropertyValue("--hero-progress")).toBe("0");
    expect(screen.queryByRole("button", { name: "Unmute" })).toBeNull();

    act(() => {
      query.matches = false;
      query.dispatchEvent(new Event("change"));
    });
    expect(hero.querySelector("video")?.muted).toBe(true);
    expect(hero.querySelector<HTMLElement>(".home-product-hero__media")?.dataset.videoReady).toBe("false");
  });
});
