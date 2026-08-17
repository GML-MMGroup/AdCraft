interface BeamRay {
  alpha: number;
  bottom: number;
  depth: number;
  lineWidth: number;
  side: number;
  width: number;
}

interface BeamDust {
  alpha: number;
  drift: number;
  radius: number;
  side: number;
  t: number;
}

export interface HologramBeamGeometry {
  dust: BeamDust[];
  rays: BeamRay[];
}

function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

export function createHologramBeamGeometry(seed = 0x5c77a3d1): HologramBeamGeometry {
  const seeded = seededRandom(seed);
  const random = (min: number, max: number) => seeded() * (max - min) + min;

  return {
    rays: Array.from({ length: 108 }, () => ({
      side: random(-1, 1),
      width: random(0.002, 0.016),
      depth: random(-1, 1),
      bottom: random(-1, 1),
      alpha: random(0.005, 0.022),
      lineWidth: random(0.3, 0.7),
    })),
    dust: Array.from({ length: 150 }, () => ({
      side: random(-1, 1),
      t: Math.pow(seeded(), 0.78),
      radius: random(0.2, 1.05),
      alpha: random(0.025, 0.14),
      drift: random(-2.2, 2.2),
    })),
  };
}

const BEAM_GEOMETRY = createHologramBeamGeometry();

export function renderHologramBeam(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  geometry: HologramBeamGeometry = BEAM_GEOMETRY,
  energy = 1,
) {
  if (!width || !height) return;

  const apexX = width * 0.5;
  const apexY = height * 0.9;
  const topY = height * 0.515;
  const halfSpan = width * 0.39;

  context.clearRect(0, 0, width, height);
  context.globalCompositeOperation = "lighter";

  context.save();
  context.filter = "blur(2.2px)";
  for (const ray of geometry.rays) {
    const topX = apexX + ray.side * halfSpan;
    const rayTopY = topY + ray.depth * height * 0.055;
    const bottomX = apexX + ray.bottom * width * 0.014;
    const rayHalf = Math.max(0.7, ray.width * width);

    context.beginPath();
    context.moveTo(bottomX - width * 0.004, apexY);
    context.lineTo(topX - rayHalf, rayTopY);
    context.lineTo(topX + rayHalf, rayTopY);
    context.lineTo(bottomX + width * 0.004, apexY);
    context.closePath();
    context.fillStyle = `rgba(101, 207, 236, ${ray.alpha * energy})`;
    context.fill();
  }
  context.restore();

  context.save();
  context.lineCap = "round";
  for (let index = 0; index < geometry.rays.length; index += 4) {
    const ray = geometry.rays[index];
    context.beginPath();
    context.moveTo(apexX + ray.bottom * width * 0.012, apexY - 2);
    context.lineTo(
      apexX + ray.side * halfSpan,
      topY + ray.depth * height * 0.055,
    );
    context.strokeStyle = `rgba(169, 235, 250, ${(ray.alpha + 0.006) * energy})`;
    context.lineWidth = ray.lineWidth;
    context.stroke();
  }
  context.restore();

  context.save();
  for (const mote of geometry.dust) {
    const y = apexY + (topY - apexY) * mote.t;
    const span = halfSpan * mote.t;
    const x = apexX + mote.side * span + mote.drift;
    const edgeFade = Math.max(0, 1 - Math.pow(Math.abs(mote.side), 3));
    const alpha = mote.alpha * Math.sin(mote.t * Math.PI) * edgeFade * energy;

    context.beginPath();
    context.fillStyle = `rgba(175, 239, 252, ${alpha})`;
    context.arc(x, y, mote.radius, 0, Math.PI * 2);
    context.fill();
  }
  context.restore();

  context.save();
  for (let index = 0; index < 15; index += 1) {
    const offset = index * height * 0.0044;
    const length = halfSpan * (1.02 - index * 0.014);

    context.beginPath();
    context.moveTo(apexX - length, topY + offset);
    context.bezierCurveTo(
      apexX - length * 0.34,
      topY + offset - height * 0.003,
      apexX + length * 0.32,
      topY + offset + height * 0.003,
      apexX + length,
      topY + offset,
    );
    context.strokeStyle = `rgba(142, 226, 246, ${(0.04 - index * 0.0018) * energy})`;
    context.lineWidth = index % 5 === 0 ? 0.75 : 0.35;
    context.stroke();
  }
  context.restore();
}
