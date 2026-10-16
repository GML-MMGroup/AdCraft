"""Where a prop or environment keyframe turns, mirroring the frontend table.

The generated Blender script builds each asset as a wrapper empty at the object's
authored ``position`` with its parts parented underneath, then animates
``rotation_euler`` on that wrapper. The wrapper's origin is therefore the object's
**base**, so a keyframed pitch or roll sweeps the whole asset around that base
instead of turning it on itself -- the same defect the three.js preview had, and
the preview has to agree with this or ``preview == render`` stops holding.

The fix is an empty at the asset's pivot with the wrapper parented under it, so the
rotation lands on the pivot while the asset's world position is unchanged.

``KIND_ROTATION_PIVOT`` is duplicated from
``apps/web/src/features/agent-canvas/canvas/sceneScriptGeometry.tsx``, which is
where the preview reads it. That duplication follows the geometry builders, which
are duplicated the same way for the same reason -- one per language, no shared
runtime. ``test_rotation_pivot_mirrors_frontend`` fails if the two ever drift,
because drift here is a silent visual bug that no other gate would catch.

Coords are SceneScript's ``[x, y, z]`` = right, forward, up. An absent kind turns
about its authored position, which is correct for the ground-standing and flat
kinds where the base is the interesting point.
"""

from __future__ import annotations

KIND_ROTATION_PIVOT: dict[str, tuple[float, float, float]] = {
    # Hangs, so it turns about the point it hangs from -- its top.
    "lantern": (0.0, 0.0, 3.0),
    # Boxy, radially symmetric things that read as "spin on my own axis".
    "box": (0.0, 0.0, 0.4),
    "crate": (0.0, 0.0, 0.45),
    "vase": (0.0, 0.0, 0.3),
    "scroll": (0.0, 0.0, 1.0),
    "book": (0.0, 0.0, 0.04),
    "cup": (0.0, 0.0, 0.07),
    # A weapon is held, so it swings about the grip in the hand, not its tip.
    "weapon": (0.0, 0.0, 0.32),
    # Environment: turn about the middle of the panel.
    "wall": (0.0, 0.0, 2.5),
    "pillar": (0.0, 0.0, 2.1),
    "gable_roof": (0.0, 0.0, 5.5),
    "flat_roof": (0.0, 0.0, 5.2),
    "window": (0.0, 0.0, 1.8),
    "platform": (0.0, 0.0, 0.4),
    # A door is the case that proves this is not a centroid rule: its pivot is a
    # vertical edge at floor level, off to one side AND below its own middle.
    "door": (-0.5, 0.0, 0.0),
    # A rock tumbles about its own middle; a tree sways about its root (absent).
    "rock": (0.0, 0.0, 0.6),
}

# Sentinel for "no pivot": turns about the authored position.
_IDENTITY_PIVOT = (0.0, 0.0, 0.0)


def rotation_pivot_for(kind: str) -> tuple[float, float, float]:
    """A kind's pivot offset, or the origin when it declares none."""
    return KIND_ROTATION_PIVOT.get(kind, _IDENTITY_PIVOT)


def needs_pivot_empty(kind: str) -> bool:
    """Whether this kind needs the extra pivot empty at all.

    Most kinds turn about their base and need nothing emitted, so this keeps the
    generated script unchanged for them -- a converter output diff is the only way
    anyone reviews this file, and churn there costs real review attention.
    """
    return rotation_pivot_for(kind) != _IDENTITY_PIVOT