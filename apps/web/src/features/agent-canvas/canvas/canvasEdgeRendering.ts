export const CANVAS_EDGE_SCREEN_WIDTH_PX = 0.9;
export const CANVAS_EDGE_MIN_WORLD_WIDTH_PX = 0.45;
export const CANVAS_EDGE_MAX_WORLD_WIDTH_PX = 18;

export function canvasEdgeStrokeWidthForZoom(zoom: number): number {
  const safeZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  const worldWidth = CANVAS_EDGE_SCREEN_WIDTH_PX / safeZoom;
  return Math.min(
    CANVAS_EDGE_MAX_WORLD_WIDTH_PX,
    Math.max(CANVAS_EDGE_MIN_WORLD_WIDTH_PX, worldWidth),
  );
}

export type CanvasEdgeZoomController = {
  setZoom: (zoom: number) => void;
  dispose: () => void;
};

type CanvasEdgeZoomControllerOptions = {
  getElement: () => HTMLElement | null;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (handle: number) => void;
};

export function createCanvasEdgeZoomController({
  getElement,
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (handle) => cancelAnimationFrame(handle),
}: CanvasEdgeZoomControllerOptions): CanvasEdgeZoomController {
  let frameId: number | null = null;
  let pendingZoom: number | null = null;

  const writeZoom = () => {
    frameId = null;
    const element = getElement();
    if (!element || pendingZoom === null) return;
    const zoom = pendingZoom;
    pendingZoom = null;
    element.style.setProperty("--agent-canvas-edge-zoom", `${zoom}`);
    element.style.setProperty(
      "--agent-canvas-edge-stroke-width",
      `${canvasEdgeStrokeWidthForZoom(zoom)}px`,
    );
  };

  return {
    setZoom(zoom) {
      pendingZoom = zoom;
      if (frameId !== null) return;
      frameId = requestFrame(writeZoom);
    },
    dispose() {
      pendingZoom = null;
      if (frameId !== null) {
        cancelFrame(frameId);
        frameId = null;
      }
    },
  };
}
