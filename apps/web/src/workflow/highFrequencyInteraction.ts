export type TransformOffset = {
  x: number;
  y: number;
};

type TransformElement = {
  style: {
    transform: string;
  };
};

type DomTransformSchedulerOptions = {
  getElement: () => TransformElement | null;
  getOffset: () => TransformOffset;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (handle: number) => void;
};

export function translate3dTransform(offset: TransformOffset) {
  return `translate3d(${offset.x}px, ${offset.y}px, 0)`;
}

export function writeElementTransform(element: TransformElement | null, offset: TransformOffset) {
  if (!element) return;
  element.style.transform = translate3dTransform(offset);
}

export function createDomTransformScheduler({
  getElement,
  getOffset,
  requestFrame = requestAnimationFrame,
  cancelFrame = cancelAnimationFrame,
}: DomTransformSchedulerOptions) {
  let frameId: number | null = null;

  const write = () => {
    frameId = null;
    writeElementTransform(getElement(), getOffset());
  };

  return {
    schedule() {
      if (frameId !== null) return;
      frameId = requestFrame(write);
    },
    cancel() {
      if (frameId === null) return;
      cancelFrame(frameId);
      frameId = null;
    },
  };
}
