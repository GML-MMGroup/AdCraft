"""What a NON-HUMAN actor does per frame, for the Blender converter.

The mirror of ``objectMotion.ts``, which the preview uses. The converter had no
equivalent at all, so a ``door_swing_open`` or a ``drive`` rendered as an actor
parked at its rest pose under the default backend -- the same silent gap the
character pose had.

Why this is separate from ``character_pose.py``: a pose presumes a body. Legs to
swing, a torso to lean, a head to tilt. A door, a wheel and a dropship have none
of those, and forcing them into a human's vocabulary would mean pretending a hinge
is a hip. So this produces a DELTA on the object's rest pose -- a rotation and a
translation -- and a human's walk is one special case of that.

Phase, not time: every function takes a phase in 0..1 so no curve here needs to
know about frames, and the caller derives the phase from what the action is.

The constants reach the frontend through
``app.cli.generate_scene_script_preview_contract`` and the curves are compared
against it phase by phase by ``test_object_motion_parity``.
"""

from __future__ import annotations

import math

#: How far one cycle carries a moving actor, in metres.
MOTION_STRIDE_METRES = {"drive": 12.0, "flyover": 60.0}

#: How long a door takes to swing open, in seconds.
DOOR_SWING_SECONDS = 3.0

#: One cycle of a continuous motion (spin, drive, flyover), in seconds.
CONTINUOUS_CYCLE_SECONDS = 2.0

#: How far a swinging door opens, radians. Past a right angle so the last frames
#: of the swing are still visibly moving.
DOOR_SWING_OPEN_RADIANS = 1.75

#: The actions this module can drive. A human action here would be a script bug:
#: the schema's validator rejects it, so a name outside this set means the object
#: is at rest and must render so.
NON_HUMAN_ACTIONS = ("door_swing_open", "spin", "drive", "flyover")


def is_non_human_action(action: str | None) -> bool:
    """True when this module can drive ``action``."""
    return action in NON_HUMAN_ACTIONS


def smoothstep(t: float) -> float:
    """Cubic smoothstep: 0 at 0 and 1 at 1, zero slope at both ends."""
    x = min(1.0, max(0.0, t))
    return x * x * (3.0 - 2.0 * x)


def object_motion_at(action: str | None, phase: float) -> dict[str, tuple[float, float, float]]:
    """The motion delta for ``action`` at ``phase``.

    Cyclic actions wrap at one cycle -- a wheel that stopped at phase 1 would read
    as broken, not as turning. One-shot actions clamp instead: wrapping a door would
    count a second cycle and swing the finished door shut again on the very next
    frame, which reads as a metronome.

    An unrecognised action returns no motion rather than raising: a script naming an
    action this build does not implement should render the object at its rest pose,
    which is visible and debuggable, rather than fail the frame over one actor.
    """
    if action == "door_swing_open":
        p = min(1.0, max(0.0, phase))
        return {"rotation": (0.0, smoothstep(p) * DOOR_SWING_OPEN_RADIANS, 0.0)}

    p = phase % 1.0
    if action == "spin":
        # Constant rate. A wheel that accelerates mid-frame reads as a bug rather
        # than as a vehicle starting up.
        return {"rotation": (p * math.pi * 2.0, 0.0, 0.0)}
    if action == "drive":
        return {"translation": (0.0, p * MOTION_STRIDE_METRES["drive"], 0.0)}
    if action == "flyover":
        # Crosses the frame laterally while holding height, which is what a flyover
        # reads as. Rise and fall is left to the camera work; a pass that also bobs
        # reads as a leaf, not an aircraft.
        return {"translation": (p * MOTION_STRIDE_METRES["flyover"], 0.0, 0.0)}
    return {}


def cycle_phase_for_frame(action: str | None, frame: float, frame_rate: float) -> float:
    """Cycle phase from a frame and the frame rate.

    Wall clock, not distance: a door opens once across its shot and a wheel turns
    continuously, and neither is defined by how far the object moved. Forcing them
    onto the distance-driven phase the human walk needs would make a parked wheel
    freeze and a moving one judder.
    """
    seconds = DOOR_SWING_SECONDS if action == "door_swing_open" else CONTINUOUS_CYCLE_SECONDS
    if not math.isfinite(seconds) or seconds <= 0 or frame_rate <= 0:
        return 0.0
    return frame / frame_rate / seconds
