import { describe, expect, it, vi } from "vitest";

import { createCanvasPointerSpotlightController } from "./canvasPointerSpotlight.ts";

function createHost() {
  const host = document.createElement("div");
  host.getBoundingClientRect = () => ({
    bottom: 620,
    height: 600,
    left: 40,
    right: 840,
    top: 20,
    width: 800,
    x: 40,
    y: 20,
    toJSON: () => ({}),
  });
  return host;
}

describe("canvas pointer spotlight", () => {
  it("coalesces pointer movement and writes canvas-relative CSS coordinates", () => {
    const host = createHost();
    let pendingFrame: FrameRequestCallback | null = null;
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      pendingFrame = callback;
      return 17;
    });
    const controller = createCanvasPointerSpotlightController({
      getElement: () => host,
      requestFrame,
      cancelFrame: vi.fn(),
    });

    controller.move(140, 120);
    controller.move(260, 210);

    expect(requestFrame).toHaveBeenCalledTimes(1);
    expect(host.dataset.pointerSpotlight).toBeUndefined();

    expect(pendingFrame).not.toBeNull();
    (pendingFrame as FrameRequestCallback)(0);

    expect(host.style.getPropertyValue("--canvas-pointer-x")).toBe("220px");
    expect(host.style.getPropertyValue("--canvas-pointer-y")).toBe("190px");
    expect(host.dataset.pointerSpotlight).toBe("active");
  });

  it("cancels pending work and hides the spotlight when the pointer leaves", () => {
    const host = createHost();
    const cancelFrame = vi.fn();
    const controller = createCanvasPointerSpotlightController({
      getElement: () => host,
      requestFrame: vi.fn(() => 23),
      cancelFrame,
    });

    controller.move(180, 150);
    controller.leave();

    expect(cancelFrame).toHaveBeenCalledWith(23);
    expect(host.dataset.pointerSpotlight).toBeUndefined();
  });

  it("cleans up a visible spotlight without retaining pointer state", () => {
    const host = createHost();
    let pendingFrame: FrameRequestCallback | null = null;
    const controller = createCanvasPointerSpotlightController({
      getElement: () => host,
      requestFrame: (callback) => {
        pendingFrame = callback;
        return 31;
      },
      cancelFrame: vi.fn(),
    });

    controller.move(180, 150);
    expect(pendingFrame).not.toBeNull();
    (pendingFrame as FrameRequestCallback)(0);
    expect(host.dataset.pointerSpotlight).toBe("active");

    controller.dispose();

    expect(host.dataset.pointerSpotlight).toBeUndefined();
  });

  it("suspends pending and future spotlight work during canvas interaction", () => {
    const host = createHost();
    const getBoundingClientRect = vi.spyOn(host, "getBoundingClientRect");
    const cancelFrame = vi.fn();
    const requestFrame = vi.fn(() => 41);
    const controller = createCanvasPointerSpotlightController({
      getElement: () => host,
      requestFrame,
      cancelFrame,
    });

    controller.move(180, 150);
    controller.suspend();
    controller.move(240, 210);

    expect(cancelFrame).toHaveBeenCalledWith(41);
    expect(requestFrame).toHaveBeenCalledTimes(1);
    expect(getBoundingClientRect).not.toHaveBeenCalled();
    expect(host.dataset.pointerSpotlight).toBeUndefined();

    controller.resume();
    controller.move(260, 230);
    expect(requestFrame).toHaveBeenCalledTimes(2);
  });
});
