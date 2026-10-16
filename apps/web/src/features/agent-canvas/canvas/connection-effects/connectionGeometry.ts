import type { XYPosition } from "@xyflow/react";

/** A short, anchored filament; endpoints never jitter away from the socket. */
export function electricArcPath(start: XYPosition, end: XYPosition, seconds: number) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.hypot(dx, dy);
  if (length < 0.1) return `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
  const amplitude = Math.min(5, length * 0.16);
  return Array.from({ length: 19 }, (_, index) => {
    const t = index / 18;
    const wave = Math.sin(t * 23 - seconds * 22) + Math.sin(t * 47 + seconds * 31) * 0.32;
    const displacement = index === 0 || index === 18 ? 0 : wave * Math.sin(Math.PI * t) * amplitude;
    return `${index === 0 ? "M" : "L"} ${start.x + dx * t - dy / length * displacement} ${start.y + dy * t + dx / length * displacement}`;
  }).join(" ");
}

/** Two paths start at the inlet and travel around opposite halves of the card. */
export function borderPulsePaths(width: number, height: number, inletY: number, radius = 8) {
  const r = Math.min(radius, width / 2, height / 2);
  const y = Math.max(r, Math.min(height - r, inletY));
  const upper = `M 1 ${y} L 1 ${r} Q 1 1 ${r} 1 L ${width - r} 1 Q ${width - 1} 1 ${width - 1} ${r} L ${width - 1} ${y}`;
  const lower = `M 1 ${y} L 1 ${height - r} Q 1 ${height - 1} ${r} ${height - 1} L ${width - r} ${height - 1} Q ${width - 1} ${height - 1} ${width - 1} ${height - r} L ${width - 1} ${y}`;
  return [upper, lower];
}
