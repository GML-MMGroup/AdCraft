import { createParticleGeometry, type ParticleShape } from "./particleGeometry";
import { infinityPoint } from "./infinityPath";

const STRIDE = 10;
const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
};
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const fract = (value: number) => value - Math.floor(value);

/**
 * Draws the resting frame of the particle shader (no motion, no hover) with
 * Canvas 2D, for browsers where WebGL is unavailable or its context was lost.
 * Keep the colour maths in sync with `particleShaders.ts`.
 */
export function drawParticleFallback(canvas: HTMLCanvasElement, shapes: ParticleShape[], accented: boolean) {
  const context = canvas.getContext("2d");
  if (!context) return false;
  const bounds = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(bounds.width * dpr);
  canvas.height = Math.round(bounds.height * dpr);
  context.clearRect(0, 0, canvas.width, canvas.height);
  const accent = accented ? 1 : 0;
  const width = Math.floor(canvas.width / shapes.length);
  const extent = Math.min(width, canvas.height) * (shapes.length === 1 ? 0.96 : 0.86);
  const crossingOrigin = infinityPoint(0);

  shapes.forEach((shape, shapeIndex) => {
    const data = createParticleGeometry(shape);
    const left = shapeIndex * width;
    for (let offset = 0; offset < data.length; offset += STRIDE) {
      const x = data[offset]!;
      const y = data[offset + 1]!;
      const size = data[offset + 2]!;
      let red = data[offset + 3]!;
      let green = data[offset + 4]!;
      let blue = data[offset + 5]!;
      const alpha = data[offset + 6]!;
      const flow = data[offset + 8]!;
      let light = 1;
      let pointAccent = 0;
      if (shape === "butterfly") {
        const wing = smoothstep(0.025, 0.22, Math.abs(x));
        const seed = fract(Math.sin(x * 127.1 + y * 311.7) * 43758.5453);
        pointAccent = accent * wing * smoothstep(0.55, 0.82, seed);
        const amount = pointAccent * 0.66;
        red = mix(red, 0.025, amount);
        green = mix(green, 0.10, amount);
        blue = mix(blue, 0.86, amount);
        light += pointAccent * 0.40;
      } else if (flow >= 0) {
        pointAccent = accent;
        red = mix(red, 0.86, 0.82 * accent);
        green = mix(green, 0.57, 0.82 * accent);
        blue = mix(blue, 0.18, 0.82 * accent);
        const [cx, cy] = infinityPoint(flow);
        const dx = cx! - crossingOrigin[0]!;
        const dy = cy! - crossingOrigin[1]!;
        const behind = Math.cos(flow) >= 0 ? 0 : 1;
        light *= 1 - behind * Math.exp(-(dx * dx + dy * dy) / 0.008) * 0.8;
      }
      const opacity = Math.min(1, alpha * light);
      if (opacity <= 0.002) continue;
      const px = left + (1 + x * (extent / width)) * 0.5 * width;
      const py = (1 - y * (extent / canvas.height)) * 0.5 * canvas.height;
      // The shader fades each sprite from its centre; a smaller solid dot at
      // reduced alpha approximates that falloff.
      const radius = Math.max(0.5, size * (1 + pointAccent * 0.25) * dpr * 0.32);
      context.globalAlpha = opacity * 0.7;
      context.fillStyle = `rgb(${Math.round(Math.min(1, red * light) * 255)} ${Math.round(Math.min(1, green * light) * 255)} ${Math.round(Math.min(1, blue * light) * 255)})`;
      context.beginPath();
      context.arc(px, py, radius, 0, Math.PI * 2);
      context.fill();
    }
  });
  context.globalAlpha = 1;
  return true;
}
