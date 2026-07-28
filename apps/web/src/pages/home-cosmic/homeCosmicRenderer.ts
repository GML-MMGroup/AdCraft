import * as THREE from "three";
import {
  advanceParticlePositions,
  createParticlePositions,
  createStreakPositions,
  syncStreakPositions,
  type ParticleBounds,
} from "./homeCosmicParticles";

export interface HomeCosmicRenderer {
  resize(
    width: number,
    height: number,
    devicePixelRatio: number,
  ): void;
  renderFrame(deltaSeconds: number, travelIntensity: number): void;
  dispose(): void;
}

interface PointLayer {
  positions: Float32Array;
  geometry: THREE.BufferGeometry;
  material: THREE.PointsMaterial;
  object: THREE.Points;
  bounds: ParticleBounds;
  idleSpeed: number;
  travelSpeed: number;
}

interface StreakLayer {
  particlePositions: Float32Array;
  streakPositions: Float32Array;
  geometry: THREE.BufferGeometry;
  material: THREE.LineBasicMaterial;
  object: THREE.LineSegments;
  bounds: ParticleBounds;
}

const FAR_BOUNDS: ParticleBounds = {
  halfWidth: 54,
  halfHeight: 31,
  farZ: -150,
  nearZ: 3,
};
const MIDDLE_BOUNDS: ParticleBounds = {
  halfWidth: 42,
  halfHeight: 24,
  farZ: -120,
  nearZ: 3,
};
const NEAR_BOUNDS: ParticleBounds = {
  halfWidth: 36,
  halfHeight: 20,
  farZ: -105,
  nearZ: 3,
};
const MAX_FRAME_SECONDS = 0.05;
const MAX_DEVICE_PIXEL_RATIO = 1.75;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function createPointLayer({
  count,
  bounds,
  color,
  opacity,
  size,
  idleSpeed,
  travelSpeed,
}: {
  count: number;
  bounds: ParticleBounds;
  color: number;
  opacity: number;
  size: number;
  idleSpeed: number;
  travelSpeed: number;
}): PointLayer {
  const positions = createParticlePositions(count, bounds);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(positions, 3),
  );
  const material = new THREE.PointsMaterial({
    blending: THREE.AdditiveBlending,
    color,
    depthWrite: false,
    opacity,
    size,
    sizeAttenuation: true,
    transparent: true,
  });
  const object = new THREE.Points(geometry, material);
  object.frustumCulled = false;

  return {
    positions,
    geometry,
    material,
    object,
    bounds,
    idleSpeed,
    travelSpeed,
  };
}

function createStreakLayer(): StreakLayer {
  const particlePositions = createParticlePositions(180, NEAR_BOUNDS);
  const streakPositions = createStreakPositions(particlePositions, 1.4);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(streakPositions, 3),
  );
  const material = new THREE.LineBasicMaterial({
    blending: THREE.AdditiveBlending,
    color: 0xf4f7ff,
    depthWrite: false,
    opacity: 0.46,
    transparent: true,
  });
  const object = new THREE.LineSegments(geometry, material);
  object.frustumCulled = false;

  return {
    particlePositions,
    streakPositions,
    geometry,
    material,
    object,
    bounds: NEAR_BOUNDS,
  };
}

function markPositionsDirty(geometry: THREE.BufferGeometry) {
  const position = geometry.getAttribute("position");
  if (position instanceof THREE.BufferAttribute) {
    position.needsUpdate = true;
  }
}

export function createHomeCosmicRenderer(
  canvas: HTMLCanvasElement,
  onContextLost: () => void,
): HomeCosmicRenderer {
  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: false,
    canvas,
    powerPreference: "high-performance",
    premultipliedAlpha: true,
  });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(68, 1, 0.1, 180);
  camera.position.z = 5;

  const farLayer = createPointLayer({
    bounds: FAR_BOUNDS,
    color: 0x96a2b8,
    count: 900,
    idleSpeed: 0.75,
    opacity: 0.42,
    size: 0.18,
    travelSpeed: 7,
  });
  const middleLayer = createPointLayer({
    bounds: MIDDLE_BOUNDS,
    color: 0xd8e2f2,
    count: 520,
    idleSpeed: 1.35,
    opacity: 0.58,
    size: 0.28,
    travelSpeed: 15,
  });
  const streakLayer = createStreakLayer();
  scene.add(farLayer.object, middleLayer.object, streakLayer.object);

  let disposed = false;

  const handleContextLost = (event: Event) => {
    event.preventDefault();
    if (!disposed) onContextLost();
  };
  canvas.addEventListener("webglcontextlost", handleContextLost);

  function resize(
    width: number,
    height: number,
    devicePixelRatio: number,
  ) {
    if (disposed) return;
    const safeWidth = Math.max(1, Math.round(width));
    const safeHeight = Math.max(1, Math.round(height));
    renderer.setPixelRatio(
      clamp(
        Number.isFinite(devicePixelRatio) ? devicePixelRatio : 1,
        1,
        MAX_DEVICE_PIXEL_RATIO,
      ),
    );
    renderer.setSize(safeWidth, safeHeight, false);
    camera.aspect = safeWidth / safeHeight;
    camera.updateProjectionMatrix();
  }

  function renderFrame(
    deltaSeconds: number,
    travelIntensity: number,
  ) {
    if (disposed) return;
    const frameSeconds = clamp(
      Number.isFinite(deltaSeconds) ? deltaSeconds : 0,
      0,
      MAX_FRAME_SECONDS,
    );
    const intensity = clamp(
      Number.isFinite(travelIntensity) ? travelIntensity : 0,
      0,
      1,
    );

    for (const layer of [farLayer, middleLayer]) {
      advanceParticlePositions(
        layer.positions,
        frameSeconds,
        layer.idleSpeed + layer.travelSpeed * intensity,
        layer.bounds,
      );
      markPositionsDirty(layer.geometry);
    }

    advanceParticlePositions(
      streakLayer.particlePositions,
      frameSeconds,
      2.4 + 34 * intensity,
      streakLayer.bounds,
    );
    syncStreakPositions(
      streakLayer.particlePositions,
      streakLayer.streakPositions,
      1.2 + 8.4 * intensity,
    );
    markPositionsDirty(streakLayer.geometry);

    farLayer.material.opacity = 0.42 + intensity * 0.12;
    middleLayer.material.opacity = 0.58 + intensity * 0.2;
    streakLayer.material.opacity = 0.38 + intensity * 0.46;
    farLayer.object.rotation.z += frameSeconds * 0.002;
    middleLayer.object.rotation.z -= frameSeconds * 0.003;

    renderer.render(scene, camera);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    canvas.removeEventListener("webglcontextlost", handleContextLost);
    scene.remove(farLayer.object, middleLayer.object, streakLayer.object);
    farLayer.geometry.dispose();
    farLayer.material.dispose();
    middleLayer.geometry.dispose();
    middleLayer.material.dispose();
    streakLayer.geometry.dispose();
    streakLayer.material.dispose();
    renderer.dispose();
  }

  return {
    resize,
    renderFrame,
    dispose,
  };
}
