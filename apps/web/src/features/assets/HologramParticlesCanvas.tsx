import { useEffect, useRef } from "react";

interface Particle {
  alpha: number;
  drift: number;
  phase: number;
  radius: number;
  speed: number;
  x: number;
  y: number;
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

function createParticles(count: number): Particle[] {
  const random = seededRandom(7_314_020);
  return Array.from({ length: count }, () => ({
    alpha: 0.14 + random() * 0.42,
    drift: (random() - 0.5) * 0.009,
    phase: random() * Math.PI * 2,
    radius: 0.45 + random() * 1.15,
    speed: 0.000018 + random() * 0.000045,
    x: 0.12 + random() * 0.76,
    y: 0.52 + random() * 0.38,
  }));
}

function renderParticles(
  context: CanvasRenderingContext2D,
  particles: Particle[],
  width: number,
  height: number,
  timestamp: number,
  delta: number,
  animate: boolean,
) {
  context.clearRect(0, 0, width, height);
  context.save();
  context.globalCompositeOperation = "lighter";

  for (const particle of particles) {
    if (animate) {
      particle.y -= particle.speed * delta;
      particle.x += particle.drift * delta;
      if (particle.y < 0.48) {
        particle.y = 0.91;
        particle.x = 0.14 + ((particle.x + 0.37) % 0.72);
      }
    }

    const shimmer = 0.72 + Math.sin(timestamp * 0.0012 + particle.phase) * 0.28;
    context.beginPath();
    context.arc(particle.x * width, particle.y * height, particle.radius, 0, Math.PI * 2);
    context.fillStyle = `rgb(185 244 255 / ${particle.alpha * shimmer})`;
    context.fill();
  }

  context.restore();
}

/** Runs the only continuous hologram motion at a capped frame rate. */
export function HologramParticlesCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const lowPower = ((navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8) <= 4;
    const prefersReducedMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const frameInterval = 1000 / (lowPower ? 24 : 30);
    let particles = createParticles(lowPower ? 28 : 42);
    let width = 1;
    let height = 1;
    let context: CanvasRenderingContext2D | null = null;
    let animationFrame = 0;
    let lastFrame = 0;

    const resize = () => {
      width = Math.max(1, Math.round(canvas.clientWidth));
      height = Math.max(1, Math.round(canvas.clientHeight));
      const pixelBudgetScale = Math.sqrt(2_200_000 / Math.max(1, width * height));
      const scale = Math.max(0.6, Math.min(window.devicePixelRatio || 1, 1.25, pixelBudgetScale));
      context = canvas.getContext("2d");
      if (!context) return;

      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      context.setTransform(scale, 0, 0, scale, 0, 0);
      particles = createParticles(lowPower ? 28 : 42);
      renderParticles(context, particles, width, height, performance.now(), 0, false);
    };

    const observer = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(resize);
    observer?.observe(canvas);
    resize();

    const frame = (timestamp: number) => {
      animationFrame = window.requestAnimationFrame(frame);
      if (!context || document.hidden || timestamp - lastFrame < frameInterval) return;
      const delta = Math.min(lastFrame ? timestamp - lastFrame : frameInterval, 48);
      lastFrame = timestamp;
      renderParticles(context, particles, width, height, timestamp, delta, true);
    };

    if (!prefersReducedMotion) animationFrame = window.requestAnimationFrame(frame);
    return () => {
      observer?.disconnect();
      window.cancelAnimationFrame(animationFrame);
    };
  }, []);

  return <canvas ref={canvasRef} className="recommended-scenes-hologram__particles" aria-hidden="true" />;
}
