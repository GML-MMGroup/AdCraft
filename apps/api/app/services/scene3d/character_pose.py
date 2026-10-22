"""The character pose library for the Blender converter, and the constants behind it.

The preview already has a pose library (``characterPose.ts``) that turns an action
into joint angles. Until now the converter had none at all: it read
``kf.position`` and ``kf.rotation_y`` and ignored ``kf.action`` entirely, so under
the DEFAULT ``SCENE3D_RENDERER_BACKEND=blender`` a ``walk`` rendered as a figure
sliding along the ground with its limbs welded in place.

The curves are implemented twice, once per language, for the same reason the
geometry builders are: the two runtimes share nothing. What makes that safe is
that the CONSTANTS live here and reach the frontend through
``app.cli.generate_scene_script_preview_contract``, so neither side hand-maintains
a number, and ``test_character_pose_matches_preview`` compares the two
implementations' actual output phase by phase.

The curve itself, and why it is shaped this way, is documented in
``characterPose.ts``; the short version is that a sine slides the planted foot by
332% of the body's own travel, so the stance leg is linear and only the swing is
eased.
"""

from __future__ import annotations

from app.services.scene3d import held_item_grip

import math

# ---------------------------------------------------------------------------
# Constants. These reach the frontend through the contract generator.
# ---------------------------------------------------------------------------

#: Metres per stride cycle for the reference figure.
WALK_STRIDE_METRES = 1.4

#: The leg of the figure ``WALK_STRIDE_METRES`` was measured on: height 1.85.
REFERENCE_LEG_LENGTH_METRES = 0.925

#: How much of the cycle a leg spends with its foot on the ground.
STANCE_FRACTION = 0.5

#: Steepest leg swing allowed, radians (~36 degrees).
WALK_MAX_LEG_RADIANS = 0.62

#: Leg length assumed when no rig is available. Height 1.7, so 0.5 x 1.7.
DEFAULT_LEG_LENGTH_METRES = 0.85

#: Arms swing opposite the same-side leg, scaled by this fraction of it.
WALK_ARM_OVER_LEG = 0.75

#: A little counter-rotation, which is most of what makes a walk read as one.
WALK_TORSO_RADIANS = 0.06

#: A gesture keyframe tips the whole head group forward, on top of the pose's own.
GESTURE_HEAD_TILT_RADIANS = -0.26

#: Held poses. Radians unless noted.
STAND_LEG_SPREAD_RADIANS = 0.05
STAND_ARM_REST_RADIANS = 0.08
GESTURE_ARM_RAISE_RADIANS = 0.9
GESTURE_ARM_OUT_RADIANS = 0.35
GESTURE_TORSO_RADIANS = 0.12
GESTURE_HEAD_RADIANS = -0.2
SIT_THIGH_LIFT_RADIANS = 1.15
SIT_TORSO_RADIANS = 0.22
SIT_HEAD_RADIANS = 0.05
TALK_ARM_RADIANS = 0.35
TALK_TORSO_RADIANS = 0.04

#: The mouth opens for a talking character, as a fraction of the head radius.
TALK_MOUTH_RATIO = 0.5
MOUTH_CLOSED_RATIO = 0.08

#: Peak knee flexion during the swing half of a stride, radians (~34 degrees).
#:
#: A bend only, never a hyperextension: the sign is fixed so the preview and the
#: converter cannot disagree about which way a knee goes. Chosen for the lift it
#: produces rather than for looking right -- `walk_foot_lift_metres` is what
#: measures it, and the swing test asserts the clearance it actually achieves.
WALK_KNEE_BEND_RADIANS = 0.6

#: Knee flexion for `sit`, radians (~80 degrees). Paired with
#: `SIT_THIGH_LIFT_RADIANS` so the shin hangs down from a raised thigh, which is
#: what sitting looks like. A lifted thigh on its own is a kick.
SIT_KNEE_BEND_RADIANS = 1.4

#: Where the knee sits along the leg, as a fraction of leg length. Halfway, so the
#: thigh and shin are the same length and either can be the one that changes.
KNEE_FRACTION_OF_LEG = 0.5

#: Limb names, in the order the rig declares them. The converter must keyframe the
#: same six joints the preview rotates or the two renderers disagree.
LIMB_FIELDS = ("leg_l", "leg_r", "knee_l", "knee_r", "arm_l", "arm_r")

#: How far down the constant contract lives, so a caller can spot-check it.
POSE_FIELDS = (
    "leg_l",
    "leg_r",
    "knee_l",
    "knee_r",
    "arm_l",
    "arm_r",
    "torso",
    "head",
    "spine",
    "bob",
)


# ---------------------------------------------------------------------------
# The walk geometry
# ---------------------------------------------------------------------------


def walk_stride_metres(leg_length_metres: float = DEFAULT_LEG_LENGTH_METRES) -> float:
    """The stride a leg of this length covers.

    Proportional to the leg, because a stride is a reach: scaling it keeps
    ``stride / (4L)`` -- and therefore the leg angle -- the same for every figure,
    so a child takes shorter steps rather than swinging harder.

    Derived separately in two places it was the source of a measured defect: the
    phase advanced as if the stride were a constant while the geometry supported
    less, and a 1.1 m figure skated at 19% of its own travel.
    """
    length = leg_length_metres if leg_length_metres > 0 else DEFAULT_LEG_LENGTH_METRES
    proportional = WALK_STRIDE_METRES * length / REFERENCE_LEG_LENGTH_METRES
    reachable = 4.0 * length * math.sin(WALK_MAX_LEG_RADIANS)
    return min(proportional, reachable)


def walk_leg_amplitude(leg_length_metres: float = DEFAULT_LEG_LENGTH_METRES) -> float:
    """The leg angle a no-slide walk needs, for a given leg length.

    A planted foot does not move, so over one stance the hip must advance exactly
    as far as ``L*sin(theta)`` retreats: ``sin(A) = stride / (4L)``.
    """
    length = leg_length_metres if leg_length_metres > 0 else DEFAULT_LEG_LENGTH_METRES
    return math.asin(min(1.0, walk_stride_metres(leg_length_metres) / (4.0 * length)))


def walk_leg_shape(q: float, amplitude: float = 0.0) -> float:
    """Leg angle as a fraction of the amplitude, over one cycle.

    The sign is the whole of the no-slide property. A planted foot means
    ``hip - L*sin(theta)`` is constant, so ``L*sin(theta)`` must RISE as the hip
    advances: the leg starts at ``-A`` with the foot AHEAD of the hip at heel
    strike, and ends at ``+A`` with the foot behind it at toe off.

    Stance is linear in horizontal REACH, not angle: a linear angle makes
    ``sin(theta)`` nonlinear and the planted foot slides. Inverting that sine
    gives ``theta = asin(linear * sin(amplitude))``. Omitting amplitude retains
    the original normalized shape (the zero-amplitude limit) for existing callers.
    Swing remains the original raised cosine.
    """
    t = q % 1.0
    if t < STANCE_FRACTION:
        linear = -1.0 + (2.0 * t) / STANCE_FRACTION
        if amplitude == 0.0:
            return linear
        return math.asin(linear * math.sin(amplitude)) / amplitude
    swing = (t - STANCE_FRACTION) / (1.0 - STANCE_FRACTION)
    return 1.0 - 2.0 * (0.5 - 0.5 * math.cos(math.pi * swing))


def walk_knee_shape(phase: float) -> float:
    """Knee flexion as a fraction of `WALK_KNEE_BEND_RADIANS`, over one cycle.

    Zero for the whole of stance, and zero at both ends of swing. That is the
    whole design, and it is why the verified no-slide result survives a knee:
    a planted foot is a STRAIGHT leg, so the thigh carries the whole leg angle
    through stance exactly as the rigid leg did, and ``L*sin(theta)`` still rises
    at the rate the hip advances.

    The zeros at each end of swing are what put the foot down properly. A knee
    still bent at heel strike would land the character on its toe, and one still
    bent at toe off would tear the foot off the floor instead of pushing off.
    A raised cosine reaches zero with zero slope at both ends, so neither happens.
    """
    t = phase % 1.0
    if t < STANCE_FRACTION:
        return 0.0
    swing = (t - STANCE_FRACTION) / (1.0 - STANCE_FRACTION)
    # Over 2*pi, not pi: a single half-cosine RISES from 0 to 1 across the swing
    # and would be at full flexion exactly at heel strike, landing the character
    # on its toe with a knee that never straightens. This is the bump -- zero at
    # toe off, peak mid-swing, zero again at the next contact.
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * swing)


def walk_foot_lift_metres(
    cycle_phase: float,
    leg_length_metres: float = DEFAULT_LEG_LENGTH_METRES,
) -> float:
    """How high the swing foot clears the ground at ``cycle_phase``, in metres.

    The measurement the knee exists to make, so it is stated in metres rather
    than trusted as a look. The knee sits halfway down the leg, so bending it by
    ``kappa`` raises the foot by ``shin * (cos(phi) - cos(phi - kappa))`` -- the
    shin no longer hangs along the thigh's direction, and the slack it recovers
    is lift.

    Positive means clear of the ground. The walk is only a walk if this is
    positive over the swing, and the swing test asserts a floor on it.
    """
    length = leg_length_metres if leg_length_metres > 0 else DEFAULT_LEG_LENGTH_METRES
    shin = length * KNEE_FRACTION_OF_LEG
    knee = walk_knee_shape(cycle_phase) * WALK_KNEE_BEND_RADIANS
    if knee == 0.0:
        return 0.0
    amplitude = walk_leg_amplitude(length)
    thigh = amplitude * walk_leg_shape(cycle_phase, amplitude)
    return shin * (math.cos(thigh) - math.cos(thigh - knee))


def segment_pose_at(
    action: str | None,
    cycle_phase: float,
    leg_length_metres: float = DEFAULT_LEG_LENGTH_METRES,
    holding: str | None = None,
) -> dict[str, float]:
    """The pose for ``action`` at ``cyclePhase``, as radians per joint.

    Keys match ``POSE_FIELDS`` and use the converter's snake_case, so this can be
    dropped into keyframe calls without a translation layer.

    ``holding`` is ``"left"`` or ``"right"`` when the character is carrying
    something. It is a SCENE property derived from a prop's ``held_by``, not an
    action, so there is no second thing for a script author to keep in step with
    ``held_by`` -- two writers for one fact is the ambiguity
    ``_validate_held_and_keyframed`` exists to reject.

    The grip overrides the arms only. A character walking with a rifle still walks,
    and its legs and bob must not stop because it is armed.
    """
    pose = _pose_for_action(action, cycle_phase, leg_length_metres)
    if not holding:
        return pose
    pitch = held_item_grip.hold_arm_pitch()
    return {
        **pose,
        "arm_l": pitch if holding == "left" else pose["arm_l"],
        "arm_r": pitch if holding == "right" else pose["arm_r"],
    }


def _pose_for_action(
    action: str | None,
    cycle_phase: float,
    leg_length_metres: float,
) -> dict[str, float]:
    """The pose an action asks for, before any held-item override."""
    phase = cycle_phase % 1.0
    theta = phase * math.pi * 2.0
    sine = math.sin(theta)

    if action == "walk":
        amplitude = walk_leg_amplitude(leg_length_metres)
        left = walk_leg_shape(phase, amplitude)
        right = walk_leg_shape(phase + STANCE_FRACTION, amplitude)
        # Whichever leg is on the ground drives the hip. A rigid leg's reach is
        # shortest when it points straight down, so holding the hip still would lift
        # the planted foot by L*(1-cos A). Letting the hip follow puts the foot back
        # on the floor and, as a side effect, produces the real bob: two dips per
        # stride, one at each double contact.
        stance = left if phase < STANCE_FRACTION else right
        # The knee is zero through stance and bends only over the swing. Split out
        # because the stance leg has to stay exactly the straight leg the no-slide
        # argument was measured on: a planted foot IS a straight leg.
        return {
            "leg_l": amplitude * left,
            "leg_r": amplitude * right,
            "knee_l": WALK_KNEE_BEND_RADIANS * walk_knee_shape(phase),
            "knee_r": WALK_KNEE_BEND_RADIANS * walk_knee_shape(phase + STANCE_FRACTION),
            "arm_l": -amplitude * WALK_ARM_OVER_LEG * left,
            "arm_r": -amplitude * WALK_ARM_OVER_LEG * right,
            "bob": -0.5 * (1.0 - math.cos(amplitude * stance)),
            "torso": WALK_TORSO_RADIANS * sine,
            "head": -WALK_TORSO_RADIANS * sine * 0.5,
            "spine": 0.0,
        }
    if action == "gesture":
        return {
            "arm_r": GESTURE_ARM_RAISE_RADIANS,
            "arm_l": -GESTURE_ARM_OUT_RADIANS,
            "torso": GESTURE_TORSO_RADIANS,
            "head": GESTURE_HEAD_RADIANS + GESTURE_HEAD_TILT_RADIANS,
            "knee_l": 0.0,
            "knee_r": 0.0,
            "spine": 0.0,
        }
    if action == "talk":
        return {
            "arm_r": TALK_ARM_RADIANS,
            "arm_l": -TALK_ARM_RADIANS * 0.4,
            "torso": TALK_TORSO_RADIANS,
            "head": -TALK_TORSO_RADIANS,
            "knee_l": 0.0,
            "knee_r": 0.0,
            "spine": 0.0,
        }
    if action == "sit":
        return {
            "leg_l": SIT_THIGH_LIFT_RADIANS,
            "leg_r": SIT_THIGH_LIFT_RADIANS,
            "knee_l": SIT_KNEE_BEND_RADIANS,
            "knee_r": SIT_KNEE_BEND_RADIANS,
            "torso": SIT_TORSO_RADIANS,
            "head": SIT_HEAD_RADIANS,
            "spine": 0.0,
        }
    return {
        "leg_l": STAND_LEG_SPREAD_RADIANS,
        "leg_r": -STAND_LEG_SPREAD_RADIANS,
        "knee_l": 0.0,
        "knee_r": 0.0,
        "arm_l": STAND_ARM_REST_RADIANS,
        "arm_r": -STAND_ARM_REST_RADIANS,
        "spine": 0.0,
    }


# ---------------------------------------------------------------------------
# Where the animation is, which the pose depends on
# ---------------------------------------------------------------------------


def action_at_frame(actions: list[str | None], frames: list[int], frame: int) -> str:
    """The action in force at ``frame``: STEP, nearest keyframe at or before.

    Matches ``characterActionAtFrame``: a keyframe's action governs frames AT AND
    AFTER it, never before. Position and yaw interpolate while action steps, so a
    gesture that starts at frame 300 does not fade in on the way there.

    Sorted first, like ``travelled_metres``. The schema does not require keyframes
    in order, and an unsorted list silently pinned the figure to whatever action
    happened to be written first.
    """
    result = "stand"
    for keyframe_frame, action in sorted(zip(frames, actions), key=lambda pair: pair[0]):
        if keyframe_frame <= frame:
            result = action or "stand"
        else:
            break
    return result


def travelled_metres(positions: list[list[float]], frames: list[int], frame: int) -> float:
    """Path length up to ``frame``, on the same linear interpolation as the preview."""
    if len(positions) < 2:
        return 0.0
    ordered = sorted(zip(frames, positions), key=lambda pair: pair[0])
    if frame <= ordered[0][0]:
        return 0.0
    total = 0.0
    previous = ordered[0]
    for keyframe_frame, position in ordered[1:]:
        if frame >= keyframe_frame:
            segment = math.dist(position, previous[1])
            total += segment
            previous = (keyframe_frame, position)
            continue
        span = keyframe_frame - previous[0]
        if span <= 0:
            return total
        ratio = (frame - previous[0]) / span
        blended = [
            previous[1][axis] + (position[axis] - previous[1][axis]) * ratio
            for axis in range(3)
        ]
        return total + math.dist(blended, previous[1])
    return total


def pose_at_frame(
    actions: list[str | None],
    positions: list[list[float]],
    frames: list[int],
    frame: int,
    leg_length_metres: float,
    holding: str | None = None,
    poses: list[dict[str, float] | None] | None = None,
) -> dict[str, float]:
    """The pose for a character at an arbitrary frame.

    Phase comes from distance travelled, never from the wall clock, so a character
    whose keyframes hold it still never accumulates steps and a fast one takes more
    per second.
    """
    distance = travelled_metres(positions, frames, frame)
    if distance <= 0:
        phase = 0.0
    else:
        phase = distance / walk_stride_metres(leg_length_metres)
    base_pose = segment_pose_at(
        action_at_frame(actions, frames, frame), phase, leg_length_metres, holding
    )
    if poses is None:
        return base_pose
    return {**base_pose, **authored_pose_at_frame(poses, frames, frame)}


def authored_pose_at_frame(
    poses: list[dict[str, float] | None], frames: list[int], frame: int
) -> dict[str, float]:
    """Resolve each explicit joint track independently and without play state.

    A missing field does not reset another field's track. Zero is authored data;
    only None is absent. A future first sample must not change an earlier action.
    """
    fields = {
        field for pose in poses if pose is not None
        for field, value in pose.items() if value is not None
    }
    resolved: dict[str, float] = {}
    for field in fields:
        samples = sorted(
            ((sample_frame, pose[field])
             for sample_frame, pose in zip(frames, poses)
             if pose is not None and pose.get(field) is not None),
            key=lambda sample: sample[0],
        )
        if not samples or frame < samples[0][0]:
            continue
        # Last sample at this instant wins, including duplicate frame numbers.
        previous = samples[0]
        for current in samples[1:]:
            if current[0] <= frame:
                previous = current
                continue
            ratio = (frame - previous[0]) / (current[0] - previous[0])
            resolved[field] = previous[1] + (current[1] - previous[1]) * ratio
            break
        else:
            resolved[field] = previous[1]
    return resolved


def held_sides_by_character(script) -> dict[str, str]:
    """Which hand each character is carrying something in, from ``held_by``.

    ONE reader of ``held_by``, so the arms that reach and the item that is held are
    resolved together -- the same single-source rule the backend's
    ``_validate_held_and_keyframed`` enforces on precedence. When both hands carry
    something the right wins, because that is what the hand offset defaults to and
    picking the other would put the two on opposite sides.
    """
    sides: dict[str, str] = {}
    for prop in script.props:
        if prop.held_by:
            sides[prop.held_by] = prop.held_side or "right"
    return sides
