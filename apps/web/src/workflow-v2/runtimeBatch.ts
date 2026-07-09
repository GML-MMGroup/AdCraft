export function createRuntimeEventBatcher<T>(flush: (events: T[]) => void) {
  let frameId: number | null = null;
  let pending: T[] = [];

  function run() {
    frameId = null;
    const events = pending;
    pending = [];
    if (events.length) flush(events);
  }

  return {
    push(event: T) {
      pending.push(event);
      if (frameId !== null) return;
      frameId = scheduleFrame(run);
    },
    clear() {
      pending = [];
      if (frameId !== null) {
        cancelFrame(frameId);
        frameId = null;
      }
    },
  };
}

function scheduleFrame(callback: FrameRequestCallback) {
  if (typeof requestAnimationFrame === "function") return requestAnimationFrame(callback);
  return window.setTimeout(() => callback(performance.now()), 16);
}

function cancelFrame(frameId: number) {
  if (typeof cancelAnimationFrame === "function") {
    cancelAnimationFrame(frameId);
    return;
  }
  window.clearTimeout(frameId);
}
