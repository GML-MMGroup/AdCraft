import { useEffect, useRef } from "react";

import { renderHologramBeam } from "./hologramBeamModel.ts";

function canvasScale(width: number, height: number) {
  const pixelBudgetScale = Math.sqrt(2_200_000 / Math.max(1, width * height));
  return Math.max(0.6, Math.min(window.devicePixelRatio || 1, 1.25, pixelBudgetScale));
}

/** Draws the cached projection once at mount and again only after a size change. */
export function HologramBeamCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let resizeTimer = 0;
    const resize = () => {
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const scale = canvasScale(width, height);
      const context = canvas.getContext("2d", { alpha: true });
      if (!context) return;

      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(scale, 0, 0, scale, 0, 0);
      renderHologramBeam(context, width, height);
    };
    const scheduleResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(resize, 100);
    };

    const observer = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(scheduleResize);
    observer?.observe(canvas);
    window.addEventListener("resize", scheduleResize, { passive: true });
    resize();

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", scheduleResize);
      window.clearTimeout(resizeTimer);
    };
  }, []);

  return <canvas ref={canvasRef} className="recommended-scenes-hologram__beam" aria-hidden="true" />;
}
