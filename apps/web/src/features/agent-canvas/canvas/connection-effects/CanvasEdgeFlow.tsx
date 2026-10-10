import "./edge-flow.css";

/** Decorative strokes reuse the exact edge geometry; hit targets stay on BaseEdge. */
export function CanvasEdgeFlow({ path }: { path: string }) {
  return (
    <g className="canvas-edge-flow" aria-hidden="true" pointerEvents="none">
      <path className="canvas-edge-flow__halo" d={path} pathLength={100} />
      <path className="canvas-edge-flow__core" d={path} pathLength={100} />
      <path className="canvas-edge-flow__highlight" d={path} pathLength={100} />
    </g>
  );
}
