import { useEffect, useRef, useState } from "react";
import type { HomeCosmicRenderer } from "./homeCosmicRenderer";
import {
  applyHomeCosmicScrollDelta,
  createHomeCosmicMotionState,
  stepHomeCosmicMotion,
} from "./homeCosmicMotion";
import { useDocumentTheme } from "./useDocumentTheme";
import { useReducedMotion } from "./useReducedMotion";
import "./home-cosmic.css";

const WHEEL_SCROLL_DEDUPLICATION_MS = 72;

export function HomeCosmicScene() {
  const sceneRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const theme = useDocumentTheme();
  const reducedMotion = useReducedMotion();
  const [fallback, setFallback] = useState(false);
  const darkTheme = theme === "dark";
  const shouldAnimate = darkTheme && !reducedMotion;

  useEffect(() => {
    if (!shouldAnimate) {
      setFallback(false);
      return undefined;
    }

    const scene = sceneRef.current;
    const ring = ringRef.current;
    const canvas = canvasRef.current;
    if (!scene || !ring || !canvas) return undefined;

    let cancelled = false;
    let renderer: HomeCosmicRenderer | undefined;
    let resizeObserver: ResizeObserver | undefined;
    let frameId: number | undefined;
    let previousFrameTime: number | undefined;
    let previousScrollY = window.scrollY;
    let lastWheelTime = Number.NEGATIVE_INFINITY;
    let motion = createHomeCosmicMotionState();

    setFallback(false);

    const resizeRenderer = () => {
      if (!renderer) return;
      const bounds = scene.getBoundingClientRect();
      renderer.resize(
        bounds.width || window.innerWidth,
        bounds.height || window.innerHeight,
        window.devicePixelRatio || 1,
      );
    };

    const stopFrames = () => {
      if (frameId !== undefined) {
        cancelAnimationFrame(frameId);
        frameId = undefined;
      }
    };

    const renderFrame = (timestamp: number) => {
      frameId = undefined;
      const deltaSeconds = previousFrameTime === undefined
        ? 0
        : (timestamp - previousFrameTime) / 1_000;
      previousFrameTime = timestamp;
      motion = stepHomeCosmicMotion(motion, deltaSeconds);

      const scale = 1 + motion.travelIntensity * 0.035;
      ring.style.transform = (
        `translate3d(-50%, -50%, 0) `
        + `rotate(${motion.angleDeg.toFixed(3)}deg) `
        + `scale(${scale.toFixed(4)})`
      );
      renderer?.renderFrame(deltaSeconds, motion.travelIntensity);

      if (!document.hidden && !cancelled) {
        frameId = requestAnimationFrame(renderFrame);
      }
    };

    const startFrames = () => {
      if (
        frameId !== undefined
        || document.hidden
        || cancelled
      ) {
        return;
      }
      previousFrameTime = undefined;
      frameId = requestAnimationFrame(renderFrame);
    };

    const handleWheel = (event: WheelEvent) => {
      motion = applyHomeCosmicScrollDelta(motion, event.deltaY);
      lastWheelTime = performance.now();
      previousScrollY = window.scrollY;
    };

    const handleScroll = () => {
      const scrollY = window.scrollY;
      const deltaY = scrollY - previousScrollY;
      previousScrollY = scrollY;
      if (performance.now() - lastWheelTime > WHEEL_SCROLL_DEDUPLICATION_MS) {
        motion = applyHomeCosmicScrollDelta(motion, deltaY);
      }
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopFrames();
        previousFrameTime = undefined;
        return;
      }
      startFrames();
    };

    const handleContextLost = () => {
      if (cancelled) return;
      renderer?.dispose();
      renderer = undefined;
      setFallback(true);
    };

    window.addEventListener("wheel", handleWheel, { passive: true });
    window.addEventListener("scroll", handleScroll, { passive: true });
    document.addEventListener(
      "visibilitychange",
      handleVisibilityChange,
    );
    window.addEventListener("resize", resizeRenderer);
    startFrames();

    if (typeof ResizeObserver === "function") {
      resizeObserver = new ResizeObserver(resizeRenderer);
      resizeObserver.observe(scene);
    }

    void import("./homeCosmicRenderer")
      .then(({ createHomeCosmicRenderer }) => {
        if (cancelled) return;
        renderer = createHomeCosmicRenderer(
          canvas,
          handleContextLost,
        );
        resizeRenderer();
      })
      .catch(() => {
        if (!cancelled) setFallback(true);
      });

    return () => {
      cancelled = true;
      stopFrames();
      resizeObserver?.disconnect();
      window.removeEventListener("wheel", handleWheel);
      window.removeEventListener("scroll", handleScroll);
      document.removeEventListener(
        "visibilitychange",
        handleVisibilityChange,
      );
      window.removeEventListener("resize", resizeRenderer);
      renderer?.dispose();
    };
  }, [shouldAnimate]);

  if (!darkTheme) return null;

  const sceneClassName = [
    "home-cosmic-scene",
    "is-dark",
    shouldAnimate ? "is-active" : "",
    darkTheme && reducedMotion ? "is-static" : "",
    fallback ? "is-fallback" : "",
  ].filter(Boolean).join(" ");

  return (
    <div
      ref={sceneRef}
      className={sceneClassName}
      aria-hidden="true"
    >
      <div
        ref={ringRef}
        className="home-cosmic-scene__ring"
      />
      <canvas
        ref={canvasRef}
        className="home-cosmic-scene__particles"
        aria-hidden="true"
        tabIndex={-1}
      />
    </div>
  );
}
