import {
  useCallback,
  useEffect,
  useRef,
  type PointerEventHandler,
  type RefObject,
} from "react";

type SpotlightPoint = {
  clientX: number;
  clientY: number;
};

type CanvasPointerSpotlightControllerOptions = {
  getElement: () => HTMLElement | null;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (handle: number) => void;
};

export type CanvasPointerSpotlightController = {
  move: (clientX: number, clientY: number) => void;
  leave: () => void;
  dispose: () => void;
};

export type CanvasPointerSpotlightBindings<T extends HTMLElement> = {
  hostRef: RefObject<T | null>;
  onPointerMove: PointerEventHandler<T>;
  onPointerLeave: PointerEventHandler<T>;
  onPointerCancel: PointerEventHandler<T>;
};

export function createCanvasPointerSpotlightController({
  getElement,
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (handle) => cancelAnimationFrame(handle),
}: CanvasPointerSpotlightControllerOptions): CanvasPointerSpotlightController {
  let frameId: number | null = null;
  let latestPoint: SpotlightPoint | null = null;

  const hide = () => {
    getElement()?.removeAttribute("data-pointer-spotlight");
  };

  const cancelPendingFrame = () => {
    if (frameId === null) return;
    cancelFrame(frameId);
    frameId = null;
  };

  const writePosition = () => {
    frameId = null;
    const host = getElement();
    const point = latestPoint;
    if (!host || !point) return;

    const bounds = host.getBoundingClientRect();
    host.style.setProperty("--canvas-pointer-x", `${point.clientX - bounds.left}px`);
    host.style.setProperty("--canvas-pointer-y", `${point.clientY - bounds.top}px`);
    host.dataset.pointerSpotlight = "active";
  };

  return {
    move(clientX, clientY) {
      latestPoint = { clientX, clientY };
      if (frameId !== null) return;
      frameId = requestFrame(writePosition);
    },
    leave() {
      latestPoint = null;
      cancelPendingFrame();
      hide();
    },
    dispose() {
      latestPoint = null;
      cancelPendingFrame();
      hide();
    },
  };
}

export function useCanvasPointerSpotlight<T extends HTMLElement>(): CanvasPointerSpotlightBindings<T> {
  const hostRef = useRef<T>(null);
  const controllerRef = useRef<CanvasPointerSpotlightController | null>(null);

  if (controllerRef.current === null) {
    controllerRef.current = createCanvasPointerSpotlightController({
      getElement: () => hostRef.current,
    });
  }

  useEffect(() => {
    const controller = controllerRef.current;
    return () => controller?.dispose();
  }, []);

  const onPointerMove = useCallback<PointerEventHandler<T>>((event) => {
    controllerRef.current?.move(event.clientX, event.clientY);
  }, []);

  const onPointerLeave = useCallback<PointerEventHandler<T>>(() => {
    controllerRef.current?.leave();
  }, []);

  return {
    hostRef,
    onPointerMove,
    onPointerLeave,
    onPointerCancel: onPointerLeave,
  };
}
