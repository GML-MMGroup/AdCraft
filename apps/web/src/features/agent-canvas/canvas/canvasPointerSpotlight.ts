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
  suspend: () => void;
  resume: () => void;
  dispose: () => void;
};

export type CanvasPointerSpotlightBindings<T extends HTMLElement> = {
  hostRef: RefObject<T | null>;
  onPointerMove: PointerEventHandler<T>;
  onPointerLeave: PointerEventHandler<T>;
  onPointerCancel: PointerEventHandler<T>;
  suspend: () => void;
  resume: () => void;
};

export function createCanvasPointerSpotlightController({
  getElement,
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (handle) => cancelAnimationFrame(handle),
}: CanvasPointerSpotlightControllerOptions): CanvasPointerSpotlightController {
  let frameId: number | null = null;
  let latestPoint: SpotlightPoint | null = null;
  let suspended = false;

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
    if (suspended || !host || !point) return;

    const bounds = host.getBoundingClientRect();
    host.style.setProperty("--canvas-pointer-x", `${point.clientX - bounds.left}px`);
    host.style.setProperty("--canvas-pointer-y", `${point.clientY - bounds.top}px`);
    host.dataset.pointerSpotlight = "active";
  };

  return {
    move(clientX, clientY) {
      if (suspended) return;
      latestPoint = { clientX, clientY };
      if (frameId !== null) return;
      frameId = requestFrame(writePosition);
    },
    leave() {
      latestPoint = null;
      cancelPendingFrame();
      hide();
    },
    suspend() {
      suspended = true;
      latestPoint = null;
      cancelPendingFrame();
      hide();
    },
    resume() {
      suspended = false;
    },
    dispose() {
      suspended = true;
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
  const suspend = useCallback(() => {
    controllerRef.current?.suspend();
  }, []);
  const resume = useCallback(() => {
    controllerRef.current?.resume();
  }, []);

  return {
    hostRef,
    onPointerMove,
    onPointerLeave,
    onPointerCancel: onPointerLeave,
    suspend,
    resume,
  };
}
