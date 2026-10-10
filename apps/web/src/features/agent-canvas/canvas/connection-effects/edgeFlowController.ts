export const EDGE_FLOW_DURATION_MS = 2400;
const EXIT_MS = 160;
const FLOW_SELECTOR = ".canvas-edge-flow";

// Two packets, a half-path apart. Keep their heads in phase, including when
// geometry/zoom changes. Full optical tail stays near 64 screen pixels.
export function edgeFlowMetrics(length: number, zoom: number) {
  const screenLength = Math.max(1, length * zoom);
  const dash = Math.min(20, 6400 / screenLength);
  return {
    dash,
    dasharray: `${dash} ${50 - dash}`,
    keyframes: [{ strokeDashoffset: `${dash}` }, { strokeDashoffset: `${dash - 100}` }],
  };
}

/** Every layer ends at `dash`, sharing the parent animation's head position.
 * The invisible prefix lets shorter strokes concentrate light near the head. */
export function edgeFlowLayerDasharray(dash: number, portion: number): string {
  const visible = dash * Math.min(1, Math.max(0, portion));
  return `0 ${dash - visible} ${visible} ${50 - dash}`;
}

type FlowEntry = { animation: Animation; dasharray: string; leavingAt: number | null };

/** One clock per canvas, no per-frame React updates. The observer also adopts
 * frozen SVG copies during dragging, which do not have React component effects.
 * SVG dash animation still paints; it is limited to selected edges and the
 * selected node's incident edges.
 */
export function createEdgeFlowController(root: HTMLElement, initialZoom: number) {
  const entries = new Map<SVGGElement, FlowEntry>();
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let zoom = initialZoom;
  // Keep widths in screen pixels without non-scaling-stroke: that SVG effect
  // also changes dash distances under zoom, breaking normalized head positions.
  root.style.setProperty("--edge-flow-zoom", `${zoom}`);
  let epoch: number | null = null;
  let hiddenAt: number | null = null;
  let frame: number | null = null;
  let exitTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  const now = () => Number(document.timeline.currentTime ?? performance.now());

  function clearEntries() {
    for (const { animation } of entries.values()) animation.cancel();
    entries.clear();
    epoch = null;
    hiddenAt = null;
  }

  function sync() {
    frame = null;
    if (disposed) return;
    if (reducedMotion.matches) { clearEntries(); return; }
    if (document.hidden) return;
    const time = now();
    const active = new Set(root.querySelectorAll<SVGGElement>(
      `.react-flow__edge:is(.is-node-related, .selected) ${FLOW_SELECTOR}`,
    ));

    for (const [element, entry] of entries) {
      if (active.has(element)) { entry.leavingAt = null; continue; }
      entry.leavingAt ??= time;
      if (!root.contains(element) || time - entry.leavingAt >= EXIT_MS) {
        entry.animation.cancel();
        entries.delete(element);
      }
    }
    if (!active.size && !entries.size) epoch = null;

    for (const element of active) {
      const path = element.querySelector("path");
      if (!path || typeof element.animate !== "function") continue;
      const length = path.getTotalLength();
      if (!Number.isFinite(length) || length <= 0) continue;
      const metrics = edgeFlowMetrics(length, zoom);
      const entry = entries.get(element);
      if (entry?.dasharray === metrics.dasharray) continue;
      element.style.strokeDasharray = metrics.dasharray;
      for (const layer of element.querySelectorAll<SVGPathElement>("[data-flow-length]")) {
        layer.style.strokeDasharray = edgeFlowLayerDasharray(metrics.dash, Number(layer.dataset.flowLength));
      }
      if (entry) {
        (entry.animation.effect as KeyframeEffect).setKeyframes(metrics.keyframes);
        entry.dasharray = metrics.dasharray;
      } else {
        epoch ??= time;
        const animation = element.animate(metrics.keyframes, {
          duration: EDGE_FLOW_DURATION_MS, iterations: Infinity, easing: "linear",
        });
        animation.startTime = epoch;
        entries.set(element, { animation, dasharray: metrics.dasharray, leavingAt: null });
      }
    }
    if (exitTimer !== null) clearTimeout(exitTimer);
    exitTimer = [...entries.values()].some((entry) => entry.leavingAt !== null)
      ? setTimeout(schedule, EXIT_MS) : null;
  }

  function schedule() {
    if (!disposed && frame === null) frame = requestAnimationFrame(sync);
  }

  function visibilityChanged() {
    const time = now();
    if (document.hidden) {
      hiddenAt = time;
      for (const { animation } of entries.values()) {
        animation.pause();
        animation.currentTime = time - (epoch ?? time);
      }
    } else {
      if (hiddenAt !== null && epoch !== null) epoch += time - hiddenAt;
      hiddenAt = null;
      for (const { animation } of entries.values()) {
        animation.play();
        animation.startTime = epoch;
      }
      schedule();
    }
  }

  const observer = new MutationObserver(schedule);
  observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "d"] });
  document.addEventListener("visibilitychange", visibilityChanged);
  reducedMotion.addEventListener("change", schedule);
  schedule();

  return {
    setZoom(nextZoom: number) {
      zoom = nextZoom;
      root.style.setProperty("--edge-flow-zoom", `${zoom}`);
      schedule();
    },
    dispose() {
      disposed = true;
      observer.disconnect();
      root.style.removeProperty("--edge-flow-zoom");
      document.removeEventListener("visibilitychange", visibilityChanged);
      reducedMotion.removeEventListener("change", schedule);
      if (frame !== null) cancelAnimationFrame(frame);
      if (exitTimer !== null) clearTimeout(exitTimer);
      clearEntries();
    },
  };
}
