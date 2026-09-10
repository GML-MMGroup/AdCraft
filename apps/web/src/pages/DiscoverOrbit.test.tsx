import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoverOrbit } from "./DiscoverOrbit";

const items = [
  { title: "One", image: "/one.jpg" },
  { title: "Two", image: "/two.jpg" },
  { title: "Three", image: "/three.jpg" },
];
const originalHiddenDescriptor = Object.getOwnPropertyDescriptor(document, "hidden");
const originalInnerWidthDescriptor = Object.getOwnPropertyDescriptor(window, "innerWidth");

class IntersectionObserverMock {
  static instances: IntersectionObserverMock[] = [];
  readonly root = null;
  readonly rootMargin = "0px";
  readonly thresholds = [0];
  readonly observe = vi.fn((target: Element) => { this.target = target; });
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
  readonly takeRecords = vi.fn(() => []);
  target: Element | null = null;

  constructor(readonly callback: IntersectionObserverCallback) {
    IntersectionObserverMock.instances.push(this);
  }

  setIntersecting(isIntersecting: boolean) {
    if (!this.target) throw new Error("observer has no target");
    this.callback([{
      boundingClientRect: this.target.getBoundingClientRect(),
      intersectionRatio: isIntersecting ? 1 : 0,
      intersectionRect: this.target.getBoundingClientRect(),
      isIntersecting,
      rootBounds: null,
      target: this.target,
      time: 0,
    }], this as unknown as IntersectionObserver);
  }
}

describe("DiscoverOrbit motion activity", () => {
  let frames: Map<number, FrameRequestCallback>;
  let nextFrameId: number;
  let hidden: boolean;
  let reduced: boolean;
  let mediaListeners: Set<() => void>;
  let clock: number;

  beforeEach(() => {
    frames = new Map();
    nextFrameId = 1;
    hidden = false;
    reduced = false;
    clock = 0;
    mediaListeners = new Set();
    IntersectionObserverMock.instances = [];
    vi.stubGlobal("IntersectionObserver", IntersectionObserverMock);
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      const id = nextFrameId++;
      frames.set(id, callback);
      return id;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id: number) => frames.delete(id)));
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      get matches() { return query.includes("prefers-reduced-motion") ? reduced : window.innerWidth <= 820; },
      media: query,
      onchange: null,
      addEventListener: vi.fn((_type: string, listener: () => void) => mediaListeners.add(listener)),
      removeEventListener: vi.fn((_type: string, listener: () => void) => mediaListeners.delete(listener)),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: 821 });
    vi.spyOn(performance, "now").mockImplementation(() => clock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    if (originalHiddenDescriptor) Object.defineProperty(document, "hidden", originalHiddenDescriptor);
    if (originalInnerWidthDescriptor) Object.defineProperty(window, "innerWidth", originalInnerWidthDescriptor);
  });

  const renderOrbit = (onSelect = vi.fn()) => {
    const view = render(<DiscoverOrbit items={items} interactive onSelect={onSelect} />);
    const root = screen.getByRole("region");
    Object.defineProperty(root, "clientWidth", { configurable: true, value: window.innerWidth });
    return { ...view, root, onSelect };
  };

  const enterViewport = () => act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(true));

  const runFrame = (now: number) => act(() => {
    clock = now;
    const pending = [...frames.entries()];
    frames.clear();
    pending.forEach(([, callback]) => callback(now));
  });

  it("only consumes cancellable horizontal-dominant desktop wheel intent", () => {
    const { root } = renderOrbit();
    enterViewport();

    const vertical = new WheelEvent("wheel", { deltaX: 3, deltaY: 40, cancelable: true });
    const diagonal = new WheelEvent("wheel", { deltaX: 20, deltaY: 20, cancelable: true });
    const ctrl = new WheelEvent("wheel", { deltaX: 40, ctrlKey: true, cancelable: true });
    const meta = new WheelEvent("wheel", { deltaX: 40, metaKey: true, cancelable: true });
    const nonCancelable = new WheelEvent("wheel", { deltaX: 40, cancelable: false });
    [vertical, diagonal, ctrl, meta, nonCancelable].forEach((event) => root.dispatchEvent(event));
    expect([vertical, diagonal, ctrl, meta, nonCancelable].every((event) => !event.defaultPrevented)).toBe(true);

    const horizontal = new WheelEvent("wheel", { deltaX: 40, deltaY: 5, cancelable: true });
    root.dispatchEvent(horizontal);
    expect(horizontal.defaultPrevented).toBe(true);
  });

  it("normalizes line and page horizontal wheel deltas", () => {
    const displacementFor = (deltaX: number, deltaMode: number) => {
      const view = renderOrbit();
      enterViewport();
      const wheel = new WheelEvent("wheel", { deltaX, deltaMode, cancelable: true });
      view.root.dispatchEvent(wheel);
      runFrame(16);
      const displacement = view.root.querySelector<HTMLElement>(
        '[data-discover-track="upper"] [data-index="0"]',
      )?.style.getPropertyValue("--discover-track-x");
      expect(wheel.defaultPrevented).toBe(true);
      view.unmount();
      frames.clear();
      clock = 0;
      return displacement;
    };

    expect(displacementFor(1, WheelEvent.DOM_DELTA_LINE)).toBe(displacementFor(16, WheelEvent.DOM_DELTA_PIXEL));
    expect(displacementFor(1, WheelEvent.DOM_DELTA_PAGE)).toBe(displacementFor(821, WheelEvent.DOM_DELTA_PIXEL));
  });

  it("stays stopped until visible and intersecting, then owns one RAF and cancels on suspension", () => {
    const { root } = renderOrbit();
    expect(IntersectionObserverMock.instances).toHaveLength(1);
    expect(frames).toHaveLength(0);

    enterViewport();
    expect(frames).toHaveLength(1);
    runFrame(100);
    expect(frames).toHaveLength(1);

    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(false));
    expect(frames).toHaveLength(0);
    const card = root.querySelector<HTMLElement>('[data-index="0"]');
    const frozenStyle = card?.getAttribute("style");
    runFrame(10_000);
    expect(card?.getAttribute("style")).toBe(frozenStyle);

    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(true));
    expect(frames).toHaveLength(1);
    hidden = true;
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(frames).toHaveLength(0);
    hidden = false;
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(frames).toHaveLength(1);
  });

  it("uses compact behavior at 820px and restores desktop behavior at 821px", () => {
    window.innerWidth = 820;
    const onSelect = vi.fn();
    const { root } = renderOrbit(onSelect);
    const first = screen.getByRole("button", { name: "upper One" });

    fireEvent.click(first);
    expect(onSelect).toHaveBeenCalledOnce();
    const wheel = new WheelEvent("wheel", { deltaX: 30, cancelable: true });
    root.dispatchEvent(wheel);
    expect(wheel.defaultPrevented).toBe(false);
    const arrow = new KeyboardEvent("keydown", { key: "ArrowRight", cancelable: true });
    first.dispatchEvent(arrow);
    expect(arrow.defaultPrevented).toBe(false);
    expect(frames).toHaveLength(0);

    window.innerWidth = 821;
    act(() => mediaListeners.forEach((listener) => listener()));
    enterViewport();
    expect(frames).toHaveLength(1);
    const desktopWheel = new WheelEvent("wheel", { deltaX: 30, cancelable: true });
    root.dispatchEvent(desktopWheel);
    expect(desktopWheel.defaultPrevented).toBe(true);
  });

  it("disconnects its observer and cancels its frame on unmount", () => {
    const view = renderOrbit();
    const observer = IntersectionObserverMock.instances[0];
    enterViewport();
    expect(frames).toHaveLength(1);
    view.unmount();
    expect(observer.disconnect).toHaveBeenCalledOnce();
    expect(frames).toHaveLength(0);
  });

  it("does not schedule motion for static, reduced-motion, or one-item galleries", () => {
    const staticView = render(<DiscoverOrbit items={items} interactive={false} />);
    expect(frames).toHaveLength(0);
    staticView.unmount();

    reduced = true;
    const reducedView = render(<DiscoverOrbit items={items} interactive />);
    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(true));
    expect(frames).toHaveLength(0);
    reducedView.unmount();

    reduced = false;
    render(<DiscoverOrbit items={items.slice(0, 1)} interactive />);
    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(true));
    expect(frames).toHaveLength(0);
  });

  it("retains card DOM and floating phase across a long inactive wall-clock gap", () => {
    const { root } = renderOrbit();
    enterViewport();
    runFrame(100);
    const card = root.querySelector<HTMLElement>('[data-discover-track="upper"] [data-index="0"]');
    const originalCard = card;
    const before = Number.parseFloat(card?.style.getPropertyValue("--discover-track-y") ?? "0");

    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(false));
    clock = 100_000;
    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(true));
    runFrame(100_016);
    const after = Number.parseFloat(card?.style.getPropertyValue("--discover-track-y") ?? "0");

    expect(root.querySelector('[data-discover-track="upper"] [data-index="0"]')).toBe(originalCard);
    expect(Math.abs(after - before)).toBeLessThan(2);
    expect(frames).toHaveLength(1);
  });

  it("releases pointer capture and clears interaction when motion suspends", () => {
    const { root, unmount } = renderOrbit();
    const setPointerCapture = vi.fn();
    const releasePointerCapture = vi.fn();
    Object.assign(root, {
      setPointerCapture,
      releasePointerCapture,
      hasPointerCapture: () => true,
    });
    enterViewport();
    fireEvent.pointerDown(root, { button: 0, pointerId: 7, clientX: 100 });
    expect(setPointerCapture).toHaveBeenCalledWith(7);
    expect(root.getAttribute("data-paused")).toBe("true");

    act(() => IntersectionObserverMock.instances.at(-1)?.setIntersecting(false));
    expect(releasePointerCapture).toHaveBeenCalledWith(7);
    expect(root.getAttribute("data-paused")).toBe("false");
    expect(frames).toHaveLength(0);

    enterViewport();
    fireEvent.pointerDown(root, { button: 0, pointerId: 8, clientX: 120 });
    unmount();
    expect(releasePointerCapture).toHaveBeenCalledWith(8);
  });

  it("keeps one observer and one RAF after StrictMode effect remounting", () => {
    render(
      <StrictMode>
        <DiscoverOrbit items={items} interactive />
      </StrictMode>,
    );
    const connected = IntersectionObserverMock.instances.filter(
      (observer) => !observer.disconnect.mock.calls.length,
    );
    expect(connected).toHaveLength(1);
    act(() => connected[0]?.setIntersecting(true));
    expect(frames).toHaveLength(1);
  });
});
