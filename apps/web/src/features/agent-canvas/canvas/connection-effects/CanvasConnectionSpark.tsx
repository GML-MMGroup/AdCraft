import { useEffect, useRef, type CSSProperties } from "react";
import type { XYPosition } from "@xyflow/react";
import { electricArcPath } from "./connectionGeometry";
import { useEnergyMotion } from "./useEnergyMotion";
export function CanvasConnectionSpark({ start, end, color, strength = 1 }: { start: XYPosition; end: XYPosition; color: string; strength?: number }) {
  const ref = useRef<SVGGElement>(null);
  const motion = useEnergyMotion();
  const { x: startX, y: startY } = start;
  const { x: endX, y: endY } = end;
  useEffect(() => {
    if (!motion) return;
    let frame = 0;
    const update = (time: number) => {
      const d = electricArcPath({ x: startX, y: startY }, { x: endX, y: endY }, time / 1000);
      ref.current?.querySelectorAll("path").forEach(path => path.setAttribute("d", d));
      frame = requestAnimationFrame(update);
    };
    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [startX, startY, endX, endY, motion]);
  const path = electricArcPath(start, end, 0);
  return <g ref={ref} className="canvas-connection-spark" opacity={strength} style={{ "--connection-color": color } as CSSProperties} aria-hidden="true">
    <path className="canvas-connection-spark__glow" d={path}/><path className="canvas-connection-spark__core" d={path}/>
    <circle className="canvas-connection-spark__halo" cx={end.x} cy={end.y} r="12"/>
  </g>;
}
