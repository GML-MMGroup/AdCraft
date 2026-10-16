import "./edge-flow.css";

/** Decorative strokes reuse the exact edge geometry; hit targets stay on BaseEdge. */
export function CanvasEdgeFlow({ path }: { path: string }) {
  return (
    <g className="canvas-edge-flow" aria-hidden="true" pointerEvents="none">
      <path className="canvas-edge-flow__aura" data-flow-length={0.3} d={path} pathLength={100} />
      <path className="canvas-edge-flow__halo" data-flow-length={0.5} d={path} pathLength={100} />
      {/* Nested, head-aligned strokes form a tapered luminous tail along the
          actual curve, including loops. No large SVG blur/filter surface. */}
      {[1, 0.86, 0.72, 0.58, 0.44, 0.3].map((portion, index) => (
        <path
          key={portion}
          className={`canvas-edge-flow__trail canvas-edge-flow__trail--${index}`}
          data-flow-length={portion}
          d={path}
          pathLength={100}
        />
      ))}
      <path className="canvas-edge-flow__core" data-flow-length={0.2} d={path} pathLength={100} />
      <path className="canvas-edge-flow__highlight" data-flow-length={0.055} d={path} pathLength={100} />
    </g>
  );
}
