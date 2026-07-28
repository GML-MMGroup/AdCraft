export interface HomeCosmicMotionState {
  angleDeg: number;
  angularVelocity: number;
  scrollVelocity: number;
  travelIntensity: number;
}

const IDLE_ANGULAR_VELOCITY = 0.06;
const MAX_ANGULAR_VELOCITY = 3.2;
const MAX_SCROLL_VELOCITY = 1_200;
const MAX_SCROLL_DELTA = 800;
const SCROLL_TO_ANGULAR_VELOCITY = 0.0024;
const SCROLL_TO_TRAVEL = 0.004;
const VELOCITY_DECAY_PER_SECOND = 4.4;
const SCROLL_DECAY_PER_SECOND = 5.8;
const TRAVEL_DECAY_PER_SECOND = 5.8;
const MAX_FRAME_SECONDS = 0.05;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function normalizedDelta(value: number) {
  if (!Number.isFinite(value)) return 0;
  return clamp(value, -MAX_SCROLL_DELTA, MAX_SCROLL_DELTA);
}

function wrapDegrees(value: number) {
  return ((value % 360) + 360) % 360;
}

export function createHomeCosmicMotionState(): HomeCosmicMotionState {
  return {
    angleDeg: 0,
    angularVelocity: IDLE_ANGULAR_VELOCITY,
    scrollVelocity: 0,
    travelIntensity: 0,
  };
}

export function applyHomeCosmicScrollDelta(
  state: HomeCosmicMotionState,
  deltaY: number,
): HomeCosmicMotionState {
  const scrollDelta = normalizedDelta(deltaY);

  return {
    ...state,
    angularVelocity: clamp(
      state.angularVelocity + scrollDelta * SCROLL_TO_ANGULAR_VELOCITY,
      -MAX_ANGULAR_VELOCITY,
      MAX_ANGULAR_VELOCITY,
    ),
    scrollVelocity: clamp(
      state.scrollVelocity + scrollDelta,
      -MAX_SCROLL_VELOCITY,
      MAX_SCROLL_VELOCITY,
    ),
    travelIntensity: clamp(
      state.travelIntensity + Math.abs(scrollDelta) * SCROLL_TO_TRAVEL,
      0,
      1,
    ),
  };
}

export function stepHomeCosmicMotion(
  state: HomeCosmicMotionState,
  deltaSeconds: number,
): HomeCosmicMotionState {
  const frameSeconds = clamp(
    Number.isFinite(deltaSeconds) ? deltaSeconds : 0,
    0,
    MAX_FRAME_SECONDS,
  );
  const velocityDecay = Math.exp(
    -VELOCITY_DECAY_PER_SECOND * frameSeconds,
  );
  const nextAngularVelocity = (
    IDLE_ANGULAR_VELOCITY
    + (state.angularVelocity - IDLE_ANGULAR_VELOCITY) * velocityDecay
  );

  return {
    angleDeg: wrapDegrees(
      state.angleDeg + nextAngularVelocity * frameSeconds,
    ),
    angularVelocity: clamp(
      nextAngularVelocity,
      -MAX_ANGULAR_VELOCITY,
      MAX_ANGULAR_VELOCITY,
    ),
    scrollVelocity: clamp(
      state.scrollVelocity
        * Math.exp(-SCROLL_DECAY_PER_SECOND * frameSeconds),
      -MAX_SCROLL_VELOCITY,
      MAX_SCROLL_VELOCITY,
    ),
    travelIntensity: clamp(
      state.travelIntensity
        * Math.exp(-TRAVEL_DECAY_PER_SECOND * frameSeconds),
      0,
      1,
    ),
  };
}
