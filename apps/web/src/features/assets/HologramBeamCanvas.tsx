import { useEffect, useRef } from "react";

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

function canvasScale(width: number, height: number) {
  const pixelBudgetScale = Math.sqrt(2_200_000 / Math.max(1, width * height));
  return Math.max(0.6, Math.min(window.devicePixelRatio || 1, 1.25, pixelBudgetScale));
}

function drawBeam(context: CanvasRenderingContext2D, width: number, height: number) {
  const random = seededRandom(20_260_814);
  const apexX = width * 0.5;
  const apexY = height * 0.9;
  const topY = height * 0.515;
  const halfSpan = width * 0.39;

  context.clearRect(0, 0, width, height);
  context.save();
  context.globalCompositeOperation = "lighter";
  context.filter = "blur(1.8px)";

  for (let index = 0; index < 96; index += 1) {
    const side = random() * 2 - 1;
    const topX = apexX + side * halfSpan;
    const rayWidth = 2 + random() * 9;
    const depth = random() * height * 0.035;
    const bottomJitter = (random() - 0.5) * width * 0.05;

    context.beginPath();
    context.moveTo(apexX + bottomJitter - 4, apexY);
    context.lineTo(topX - rayWidth, topY + depth);
    context.lineTo(topX + rayWidth, topY + depth);
    context.lineTo(apexX + bottomJitter + 4, apexY);
    context.closePath();
    context.fillStyle = `rgb(101 207 236 / ${0.032 + random() * 0.052})`;
    context.fill();
  }

  context.filter = "none";
  context.lineWidth = 0.7;
  for (let index = 0; index < 24; index += 1) {
    const side = random() * 2 - 1;
    const topX = apexX + side * halfSpan;
    context.beginPath();
    context.moveTo(apexX + (random() - 0.5) * width * 0.03, apexY);
    context.lineTo(topX, topY + random() * height * 0.045);
    context.strokeStyle = `rgb(178 241 255 / ${0.1 + random() * 0.12})`;
    context.stroke();
  }

  for (let index = 0; index < 136; index += 1) {
    const progress = 0.06 + random() * 0.88;
    const halfWidth = halfSpan * progress;
    const y = apexY - (apexY - topY) * progress;
    const x = apexX + (random() * 2 - 1) * halfWidth;
    const radius = 0.35 + random() * 1.25;
    const edgeFade = 1 - Math.abs(x - apexX) / Math.max(1, halfWidth);

    context.beginPath();
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fillStyle = `rgb(174 241 255 / ${(0.04 + random() * 0.1) * edgeFade})`;
    context.fill();
  }

  context.setLineDash([width * 0.018, width * 0.022]);
  for (let index = 0; index < 15; index += 1) {
    const progress = 0.04 + index / 17;
    const y = apexY - (apexY - topY) * progress;
    const span = halfSpan * progress;
    context.beginPath();
    context.moveTo(apexX - span, y);
    context.lineTo(apexX + span, y);
    context.strokeStyle = `rgb(162 239 255 / ${0.052 + (1 - progress) * 0.065})`;
    context.stroke();
  }
  context.restore();
}

/** Draws a deterministic projection beam only after size changes, not per animation frame. */
export function HologramBeamCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const resize = () => {
      const width = Math.max(1, Math.round(canvas.clientWidth));
      const height = Math.max(1, Math.round(canvas.clientHeight));
      const scale = canvasScale(width, height);
      const context = canvas.getContext("2d");
      if (!context) return;

      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      context.setTransform(scale, 0, 0, scale, 0, 0);
      drawBeam(context, width, height);
    };

    const observer = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(resize);
    observer?.observe(canvas);
    resize();
    return () => observer?.disconnect();
  }, []);

  return <canvas ref={canvasRef} className="recommended-scenes-hologram__beam" aria-hidden="true" />;
}
