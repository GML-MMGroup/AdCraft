import { useEffect, useState } from "react";

const FONT_READY_FALLBACK_MS = 700;

export function useHomeHeroMotionReady() {
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (typeof document === "undefined" || !("fonts" in document)) {
      setIsReady(true);
      return;
    }

    let cancelled = false;
    let startQueued = false;
    let firstFrame: number | undefined;
    let secondFrame: number | undefined;
    const usesAnimationFrame = typeof window.requestAnimationFrame === "function";
    const requestPaint = usesAnimationFrame
      ? window.requestAnimationFrame.bind(window)
      : (callback: FrameRequestCallback) => window.setTimeout(
          () => callback(performance.now()),
          16,
        );
    const cancelPaint = (handle: number | undefined) => {
      if (handle === undefined) return;
      if (usesAnimationFrame) {
        window.cancelAnimationFrame(handle);
      } else {
        window.clearTimeout(handle);
      }
    };

    const queueStart = () => {
      if (cancelled || startQueued) return;
      startQueued = true;
      window.clearTimeout(fallbackTimer);
      firstFrame = requestPaint(() => {
        secondFrame = requestPaint(() => {
          if (!cancelled) setIsReady(true);
        });
      });
    };

    const fallbackTimer = window.setTimeout(queueStart, FONT_READY_FALLBACK_MS);
    void document.fonts.ready.then(queueStart, queueStart);

    return () => {
      cancelled = true;
      window.clearTimeout(fallbackTimer);
      cancelPaint(firstFrame);
      cancelPaint(secondFrame);
    };
  }, []);

  return isReady;
}
