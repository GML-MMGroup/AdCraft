import type { CSSProperties } from "react";
import { useConnectionPulse } from "./connectionEffectContext";
import { borderPulsePaths } from "./connectionGeometry";
import { useEnergyMotion } from "./useEnergyMotion";
export function CanvasNodeConnectionPulse({ workflowId, nodeId, width, height }: { workflowId: string; nodeId: string; width: number; height: number }) {
  const pulse = useConnectionPulse(workflowId, nodeId);
  const motion = useEnergyMotion();
  if (!pulse || !motion) return null;
  return <svg key={pulse.id} className="canvas-connection-pulse" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" style={{ "--connection-color": pulse.color } as CSSProperties}>
    {borderPulsePaths(width, height, height / 2).map((path, index) => <g key={index}>
      <path className="canvas-connection-pulse__glow" d={path} pathLength="100"/>
      <path className="canvas-connection-pulse__core" d={path} pathLength="100"/>
    </g>)}
    <circle className="canvas-connection-pulse__ring" cx="0" cy={height / 2} r="8"/>
  </svg>;
}
