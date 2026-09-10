import { describe, expect, it, vi } from "vitest";

import {
  CANVAS_EDGE_MAX_WORLD_WIDTH_PX,
  CANVAS_EDGE_MIN_WORLD_WIDTH_PX,
  CANVAS_EDGE_SCREEN_WIDTH_PX,
  canvasEdgeStrokeWidthForZoom,
  createCanvasEdgeZoomController,
} from "./canvasEdgeRendering.ts";

describe("canvas edge rendering", () => {
  it.each([
    [0.05, CANVAS_EDGE_MAX_WORLD_WIDTH_PX],
    [0.1, 9],
    [0.5, 1.8],
    [1, CANVAS_EDGE_SCREEN_WIDTH_PX],
    [2, CANVAS_EDGE_MIN_WORLD_WIDTH_PX],
  ])("maps zoom %s to a bounded world stroke width", (zoom, expected) => {
    expect(canvasEdgeStrokeWidthForZoom(zoom)).toBeCloseTo(expected);
  });

  it("coalesces viewport updates and writes only DOM styles", () => {
    const host = document.createElement("div");
    const callbacks: FrameRequestCallback[] = [];
    const controller = createCanvasEdgeZoomController({
      getElement: () => host,
      requestFrame: (callback) => {
        callbacks.push(callback);
        return callbacks.length;
      },
      cancelFrame: vi.fn(),
    });

    controller.setZoom(0.1);
    controller.setZoom(0.5);
    expect(callbacks).toHaveLength(1);
    callbacks[0](0);

    expect(host.style.getPropertyValue("--agent-canvas-edge-zoom")).toBe("0.5");
    expect(host.style.getPropertyValue("--agent-canvas-edge-stroke-width")).toBe("1.8px");
    controller.dispose();
  });
});
