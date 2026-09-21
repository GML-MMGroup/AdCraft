import { drawInfinityParticles } from "./infinityGeometry";

export type ParticleShape = "butterfly" | "infinity";

// Each vertex: x, y, size, rgba, phase, flow parameter (-1 = fixed), ribbon offset.
export function createParticleGeometry(shape: ParticleShape): Float32Array {
  let seed = shape === "butterfly" ? 721 : 193;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const normal = () => Math.sqrt(-2 * Math.log(Math.max(random(), 0.00001))) * Math.cos(random() * Math.PI * 2);
  const vertices: number[] = [];
  const point = (x: number, y: number, strength: number, blue = 0, size = 0.7 + random() * 0.9, phase = 0, flow = -1, offset = 0) => {
    vertices.push(x, y, size, 0.83 - blue * 0.62, 0.87 - blue * 0.5, 0.91 + blue * 0.09, strength, phase, flow, offset);
  };

  if (shape === "butterfly") {
    // Cubic contours, running from the wing root to the tip and back.
    const curves = [
      [[0.015, 0.02], [0.12, 0.38], [0.49, 0.66], [0.66, 0.67]],
      [[0.66, 0.67], [0.82, 0.25], [0.62, -0.01], [0.08, -0.12]],
      [[0.045, -0.06], [0.35, 0.06], [0.68, -0.13], [0.48, -0.43]],
      [[0.48, -0.43], [0.32, -0.65], [0.08, -0.42], [0.025, -0.16]],
    ];
    const at = (curve: number[][], t: number) => {
      const s = 1 - t;
      return [0, 1].map(axis => s ** 3 * curve[0][axis] + 3 * s * s * t * curve[1][axis] + 3 * s * t * t * curve[2][axis] + t ** 3 * curve[3][axis]);
    };
    for (const side of [-1, 1]) {
      curves.forEach((curve, index) => {
        const rootY = index < 2 ? 0.0 : -0.12;
        for (let i = 0; i < 6500; i++) {
          const t = random();
          const edge = i % 5 === 0;
          const radius = edge ? 1 + normal() * 0.008 : Math.sqrt(random());
          const [x, y] = at(curve, t);
          const vein = Math.pow(Math.max(0, Math.cos(t * Math.PI * 16 + radius * 1.8)), 22);
          const ripple = Math.sin(radius * 48 + t * 13) * 0.5 + 0.5;
          point(side * (x * radius + normal() * 0.003), rootY + (y - rootY) * radius + normal() * 0.003,
            edge ? 0.65 : 0.14 + vein * 0.5 + ripple * 0.12, 0, edge ? 1.15 : 0.8 + random() * 1.0);
        }
      });
      for (let i = 0; i < 900; i++) {
        const t = random();
        point(side * (0.02 + t * 0.07 + normal() * 0.002), 0.19 + t * 0.16, 0.4, 0, 0.75);
      }
    }
    for (let i = 0; i < 2200; i++) {
      const y = random() * 0.55 - 0.32;
      point(normal() * (0.008 + 0.012 * Math.sin((y + 0.32) / 0.55 * Math.PI)), y, 0.55);
    }
    for (let i = 0; i < 1100; i++) {
      point(normal() * 0.4, normal() * 0.34, 0.045, 0, 0.6);
    }
  } else {
    drawInfinityParticles(random, normal, point);
  }
  return new Float32Array(vertices);
}
