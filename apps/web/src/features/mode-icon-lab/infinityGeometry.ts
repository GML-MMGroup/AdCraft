import { infinityPoint } from "./infinityPath";

type Emit = (x: number, y: number, opacity: number, blue: number, size: number, phase: number, flow: number, offset: number) => void;

/** Continuous silver ribbon. Arc-length sampling avoids clumps at the turns;
 * the two crossing branches have distinct depth, without a central glow. */
export function drawInfinityParticles(random: () => number, normal: () => number, emit: Emit) {
  const curve = infinityPoint;
  const path: { x: number; y: number; nx: number; ny: number; t: number; length: number }[] = [];
  let length = 0;
  let previous = curve(0);
  for (let i = 1; i <= 1600; i++) {
    const t = i / 1600 * Math.PI * 2;
    const [x, y] = curve(t);
    length += Math.hypot(x - previous[0], y - previous[1]);
    const before = curve(t - 0.0001), after = curve(t + 0.0001);
    const dx = after[0] - before[0], dy = after[1] - before[1];
    const speed = Math.hypot(dx, dy);
    path.push({ x, y, nx: -dy / speed, ny: dx / speed, t, length });
    previous = [x, y];
  }
  for (let i = 0; i < 58000; i++) {
    const distance = random() * length;
    let low = 0, high = path.length - 1;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (path[middle].length < distance) low = middle + 1;
      else high = middle;
    }
    const { x, y, nx, ny, t } = path[low];
    const halfWidth = (0.014 + 0.019 * Math.sin(t) ** 2)
      * (1 + 0.28 * Math.sin(t + 0.7));
    const edge = i % 6 === 0;
    const dust = i % 17 === 0;
    const across = edge ? (random() < 0.5 ? -1 : 1) + normal() * 0.07 : normal() * 0.48;
    const offset = across * halfWidth * (dust ? 2.4 : 1);
    const behind = Math.cos(t) < 0;
    const [crossX, crossY] = curve(0);
    const crossing = Math.exp(-((x - crossX) ** 2 + (y - crossY) ** 2) / 0.008);
    const depth = behind ? 1 - crossing * 0.8 : 1;
    const opacity = dust ? 0.045 : edge ? 0.55 : 0.17 + random() * 0.24;
    const flowing = i % 4 === 0 && !edge && !dust;
    emit(x + nx * offset, y + ny * offset, opacity * (flowing ? 1 : depth), 0,
      dust ? 0.6 : edge ? 1.05 : 0.75 + random() * 0.75, distance / length, flowing ? t : -1, offset / halfWidth);
  }
}
