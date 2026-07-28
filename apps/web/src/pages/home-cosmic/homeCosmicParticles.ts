export interface ParticleBounds {
  halfWidth: number;
  halfHeight: number;
  farZ: number;
  nearZ: number;
}

type RandomSource = () => number;

const MAX_PARTICLE_FRAME_SECONDS = 0.5;
const FAR_RECYCLE_BAND_RATIO = 0.15;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function sampleUnit(random: RandomSource) {
  const value = random();
  if (!Number.isFinite(value)) return 0.5;
  return clamp(value, 0, 1);
}

function sampleCentered(random: RandomSource, halfExtent: number) {
  return (sampleUnit(random) * 2 - 1) * halfExtent;
}

function resetParticle(
  positions: Float32Array,
  offset: number,
  bounds: ParticleBounds,
  random: RandomSource,
) {
  const depth = bounds.nearZ - bounds.farZ;
  positions[offset] = sampleCentered(random, bounds.halfWidth);
  positions[offset + 1] = sampleCentered(random, bounds.halfHeight);
  positions[offset + 2] = (
    bounds.farZ
    + sampleUnit(random) * depth * FAR_RECYCLE_BAND_RATIO
  );
}

export function createParticlePositions(
  count: number,
  bounds: ParticleBounds,
  random: RandomSource = Math.random,
) {
  const particleCount = Math.max(0, Math.floor(count));
  const positions = new Float32Array(particleCount * 3);
  const depth = bounds.nearZ - bounds.farZ;

  for (let offset = 0; offset < positions.length; offset += 3) {
    positions[offset] = sampleCentered(random, bounds.halfWidth);
    positions[offset + 1] = sampleCentered(random, bounds.halfHeight);
    positions[offset + 2] = (
      bounds.farZ + sampleUnit(random) * depth
    );
  }

  return positions;
}

export function advanceParticlePositions(
  positions: Float32Array,
  deltaSeconds: number,
  speed: number,
  bounds: ParticleBounds,
  random: RandomSource = Math.random,
) {
  const frameSeconds = clamp(
    Number.isFinite(deltaSeconds) ? deltaSeconds : 0,
    0,
    MAX_PARTICLE_FRAME_SECONDS,
  );
  const safeSpeed = Number.isFinite(speed) ? Math.max(0, speed) : 0;
  const travelDistance = frameSeconds * safeSpeed;

  for (let offset = 0; offset < positions.length; offset += 3) {
    positions[offset + 2] += travelDistance;
    if (positions[offset + 2] > bounds.nearZ) {
      resetParticle(positions, offset, bounds, random);
    }
  }

  return positions;
}

export function createStreakPositions(
  particlePositions: Float32Array,
  streakLength: number,
) {
  const streakPositions = new Float32Array(
    particlePositions.length * 2,
  );
  return syncStreakPositions(
    particlePositions,
    streakPositions,
    streakLength,
  );
}

export function syncStreakPositions(
  particlePositions: Float32Array,
  streakPositions: Float32Array,
  streakLength: number,
) {
  if (streakPositions.length !== particlePositions.length * 2) {
    throw new RangeError(
      "Streak position buffer must contain two vertices per particle.",
    );
  }

  const safeLength = Number.isFinite(streakLength)
    ? Math.max(0, streakLength)
    : 0;

  for (
    let particleOffset = 0, streakOffset = 0;
    particleOffset < particlePositions.length;
    particleOffset += 3, streakOffset += 6
  ) {
    const x = particlePositions[particleOffset];
    const y = particlePositions[particleOffset + 1];
    const z = particlePositions[particleOffset + 2];

    streakPositions[streakOffset] = x;
    streakPositions[streakOffset + 1] = y;
    streakPositions[streakOffset + 2] = z;
    streakPositions[streakOffset + 3] = x;
    streakPositions[streakOffset + 4] = y;
    streakPositions[streakOffset + 5] = z - safeLength;
  }

  return streakPositions;
}
