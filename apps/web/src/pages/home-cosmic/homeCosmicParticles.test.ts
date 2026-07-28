import { describe, expect, it } from "vitest";
import {
  advanceParticlePositions,
  createParticlePositions,
  createStreakPositions,
  syncStreakPositions,
  type ParticleBounds,
} from "./homeCosmicParticles";

const bounds: ParticleBounds = {
  halfWidth: 20,
  halfHeight: 12,
  farZ: -100,
  nearZ: 2,
};

function deterministicRandom() {
  const values = [0, 0.25, 0.5, 0.75, 0.99];
  let cursor = 0;
  return () => values[cursor++ % values.length]!;
}

describe("home cosmic particles", () => {
  it("creates deterministic particles inside configured bounds", () => {
    const positions = createParticlePositions(
      5,
      bounds,
      deterministicRandom(),
    );

    expect(positions).toHaveLength(15);
    for (let index = 0; index < positions.length; index += 3) {
      expect(positions[index]).toBeGreaterThanOrEqual(-bounds.halfWidth);
      expect(positions[index]).toBeLessThanOrEqual(bounds.halfWidth);
      expect(positions[index + 1]).toBeGreaterThanOrEqual(-bounds.halfHeight);
      expect(positions[index + 1]).toBeLessThanOrEqual(bounds.halfHeight);
      expect(positions[index + 2]).toBeGreaterThanOrEqual(bounds.farZ);
      expect(positions[index + 2]).toBeLessThanOrEqual(bounds.nearZ);
    }
  });

  it("advances positions in place toward the camera", () => {
    const positions = new Float32Array([2, -3, -40]);
    const result = advanceParticlePositions(
      positions,
      0.5,
      12,
      bounds,
      deterministicRandom(),
    );

    expect(result).toBe(positions);
    expect(positions[0]).toBe(2);
    expect(positions[1]).toBe(-3);
    expect(positions[2]).toBe(-34);
  });

  it("recycles particles into the far depth band after passing the camera", () => {
    const positions = new Float32Array([0, 0, 1.8]);
    advanceParticlePositions(
      positions,
      0.5,
      12,
      bounds,
      deterministicRandom(),
    );

    expect(positions[0]).toBeGreaterThanOrEqual(-bounds.halfWidth);
    expect(positions[0]).toBeLessThanOrEqual(bounds.halfWidth);
    expect(positions[1]).toBeGreaterThanOrEqual(-bounds.halfHeight);
    expect(positions[1]).toBeLessThanOrEqual(bounds.halfHeight);
    expect(positions[2]).toBeGreaterThanOrEqual(bounds.farZ);
    expect(positions[2]).toBeLessThan(bounds.farZ + 16);
  });

  it("updates reusable streak segments from logical particle positions", () => {
    const particles = new Float32Array([
      1, 2, -20,
      -4, 5, -60,
    ]);
    const streaks = createStreakPositions(particles, 3);
    const sameBuffer = syncStreakPositions(particles, streaks, 8);

    expect(sameBuffer).toBe(streaks);
    expect(Array.from(streaks)).toEqual([
      1, 2, -20, 1, 2, -28,
      -4, 5, -60, -4, 5, -68,
    ]);
  });
});
