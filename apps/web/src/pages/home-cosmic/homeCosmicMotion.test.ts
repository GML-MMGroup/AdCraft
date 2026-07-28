import { describe, expect, it } from "vitest";
import {
  applyHomeCosmicScrollDelta,
  createHomeCosmicMotionState,
  stepHomeCosmicMotion,
} from "./homeCosmicMotion";

describe("home cosmic motion", () => {
  it("turns forward for downward scroll and backward for upward scroll", () => {
    const initial = createHomeCosmicMotionState();
    const down = applyHomeCosmicScrollDelta(initial, 120);
    const up = applyHomeCosmicScrollDelta(initial, -120);

    expect(down.angularVelocity).toBeGreaterThan(initial.angularVelocity);
    expect(up.angularVelocity).toBeLessThan(0);
    expect(down.travelIntensity).toBeGreaterThan(0);
    expect(up.travelIntensity).toBeGreaterThan(0);
  });

  it("decays scroll impulse back to a positive idle rotation", () => {
    let state = applyHomeCosmicScrollDelta(
      createHomeCosmicMotionState(),
      900,
    );

    for (let index = 0; index < 600; index += 1) {
      state = stepHomeCosmicMotion(state, 1 / 60);
    }

    expect(state.angularVelocity).toBeGreaterThan(0);
    expect(state.angularVelocity).toBeLessThan(0.2);
    expect(state.travelIntensity).toBeLessThan(0.02);
    expect(Math.abs(state.scrollVelocity)).toBeLessThan(0.02);
  });

  it("bounds extreme wheel deltas and frame gaps", () => {
    const state = stepHomeCosmicMotion(
      applyHomeCosmicScrollDelta(
        createHomeCosmicMotionState(),
        100_000,
      ),
      2,
    );

    expect(Math.abs(state.angularVelocity)).toBeLessThanOrEqual(3.2);
    expect(state.travelIntensity).toBeLessThanOrEqual(1);
    expect(Math.abs(state.scrollVelocity)).toBeLessThanOrEqual(1_200);
  });

  it("wraps accumulated rotation without mutating the previous state", () => {
    const initial = {
      ...createHomeCosmicMotionState(),
      angleDeg: 359.99,
      angularVelocity: 3.2,
    };
    const next = stepHomeCosmicMotion(initial, 0.05);

    expect(next).not.toBe(initial);
    expect(initial.angleDeg).toBe(359.99);
    expect(next.angleDeg).toBeGreaterThanOrEqual(0);
    expect(next.angleDeg).toBeLessThan(360);
  });
});
