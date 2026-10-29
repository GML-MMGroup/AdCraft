const COMMON_RATIOS: ReadonlyArray<readonly [number, number]> = [
  [1, 1], [4, 3], [3, 4], [16, 9], [9, 16], [3, 2], [2, 3],
  [5, 4], [4, 5], [21, 9], [9, 21], [2, 1], [1, 2],
];

function gcd(left: number, right: number): number {
  return right === 0 ? left : gcd(right, left % right);
}

/**
 * The aspect ratio of a "WIDTHxHEIGHT" resolution, e.g. "2304x1728" -> "4:3".
 * Sizes a provider rounds to its pixel grid snap to the nearest common ratio.
 */
export function resolutionAspectRatio(value: string): string | null {
  const match = /^\s*(\d+)\s*[x×*]\s*(\d+)\s*$/i.exec(value);
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!width || !height) return null;
  const divisor = gcd(width, height);
  const exact = [width / divisor, height / divisor] as const;
  if (COMMON_RATIOS.some(([w, h]) => w === exact[0] && h === exact[1])) return `${exact[0]}:${exact[1]}`;
  const nearest = COMMON_RATIOS.find(([w, h]) => Math.abs(width / height - w / h) / (w / h) < 0.01);
  if (nearest) return `${nearest[0]}:${nearest[1]}`;
  return exact[0] <= 32 && exact[1] <= 32 ? `${exact[0]}:${exact[1]}` : null;
}
