"""Where a held item's hand is, derived from the rig rather than typed in.

§2.2 of ``docs/plans/previs-asset-and-motion-gap.md``: the hand has no pose it can
grip with, so a weapon floats beside it.

Two things were wrong, and they are independent:

- ``HAND_HEIGHT_RATIO`` asks for a hand at 0.72 of the character's height while the
  rig hangs the hand at 0.49, so the item sat 26-43 cm above the fingers depending on
  how tall the character was. No pose existed that closed the gap.
- ``HAND_REACH_M`` was a fixed 0.32 m. The rig's arm lateral is PROPORTIONAL to
  height -- 0.34 m on a 1.85 m adult, 0.20 m on a 1.1 m child -- so the constant
  matched at exactly 1.75 m and put a child's weapon 60% further outboard than their
  hand. Nothing compared the two, because neither file said where the arm ended.

The arm is rigid and pivots at the shoulder, so the hand is on a circle of radius
``armLength`` about it. Pitching forward by ``theta`` puts the hand at
``shoulder - L*cos(theta)`` and ``L*sin(theta)`` forward. Both the target height and
the shoulder are proportional to height, so ``theta`` is the SAME for every figure --
which is why it is exported as one constant and not recomputed per character.

The numbers here reach the frontend through
``app.cli.generate_scene_script_preview_contract``, and
``test_held_item_grip.py`` asserts the preview and the converter put a held item on
the same point, which is the property that was missing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: The rig's proportions, mirrored from ``lowPolyHumanRig.ts``
#: (``CHARACTER_RIG_FRACTIONS``). These are the geometry the hand position has to
#: agree with; a change to either side without the other is what produced the defect.
RIG_FRACTIONS = {
    "leg": 0.5,
    "torso": 0.3,
    "neck": 0.03,
    "head_radius": 0.11,
    "arm": 0.3,
    "arm_hang": 0.55,
    "limb_width": 0.055,
    "torso_width": 0.3,
    "torso_depth": 0.16,
    "leg_spread": 0.075,
    "arm_outset": 0.6,
    "arm_width_factor": 0.8,
    "leg_depth_factor": 1.2,
    "head_seat": 0.85,
}

#: Hand height as a share of the character's height: chest level, which is where a
#: weapon is carried rather than dangling.
GRIP_HEIGHT_RATIO = 0.72

#: How far above the prop's own origin its GRIP sits, per unit of scale, per kind.
#:
#: A prop's origin is where it stands, not where it is held. A `weapon` carries its
#: grip 0.32 of its scale up and the blade a metre above that, so placing the origin
#: in the hand holds a sword by the blade -- which is what the first render of this
#: showed. Kinds absent from this table are assumed to be gripped at their origin,
#: which is the honest default: we know where a sword's handle is and do not know
#: where a held crate's handle is.
KIND_GRIP_RATIO = {
    "weapon": 0.32,
}


def grip_ratio_for(kind: str | None) -> float:
    """How far above its origin a held item's grip sits, per unit of scale."""
    if kind is None:
        return 0.0
    return KIND_GRIP_RATIO.get(kind, 0.0)


@dataclass(frozen=True)
class ArmGeometry:
    """One arm's chain, in metres, for a character of a given height."""

    height: float
    shoulder_height: float
    rest_hand_height: float
    length: float
    lateral: float

    @property
    def pitch_to_grip(self) -> float:
        """Forward pitch, radians, that puts the hand at the grip height."""
        ratio = (self.shoulder_height - self.height * GRIP_HEIGHT_RATIO) / self.length
        return math.acos(max(-1.0, min(1.0, ratio)))

    @property
    def grip_forward(self) -> float:
        """How far in front of the chest axis the gripping hand ends up."""
        return self.length * math.sin(self.pitch_to_grip)

    @property
    def grip_lateral(self) -> float:
        return self.lateral


def arm_geometry(height: float) -> ArmGeometry:
    f = RIG_FRACTIONS
    h = height
    torso_top = (f["leg"] + f["torso"]) * h
    length = f["arm"] * h
    shoulder = torso_top - length * f["arm_hang"] + length / 2
    lateral = f["torso_width"] * h / 2 + f["limb_width"] * h * f["arm_outset"]
    return ArmGeometry(
        height=h,
        shoulder_height=shoulder,
        rest_hand_height=shoulder - length,
        length=length,
        lateral=lateral,
    )


def hold_arm_pitch() -> float:
    """The forward arm pitch for the grip pose.

    Height-independent by construction: the shoulder and the target are both
    proportional to height, so the cosine ratio is the same number for everyone. It
    is computed rather than written down so that a change to the rig's arm hang or
    length moves it instead of silently leaving the pose aimed at the old shoulder.
    """
    return arm_geometry(1.0).pitch_to_grip


def hold_arm_pitch_degrees() -> float:
    return math.degrees(hold_arm_pitch())
