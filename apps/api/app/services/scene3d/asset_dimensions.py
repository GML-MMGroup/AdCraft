"""What each asset kind ACTUALLY measures, in metres.

WHY THIS FILE EXISTS
The renderer and the preview both scale a kind's geometry by the authored
``scale``, but nobody — including the model that writes the SceneScript — knows
what that product is in metres. A `pillar` at ``scale: 4.5`` is a 19 m column
beside a 1.85 m person; a `platform` at ``scale: 5`` is a 25 x 2 x 25 m slab whose
top sits at z = 3 m, which puts every character (authored at z = 0) UNDERNEATH
it. That is not a taste problem: with 5 of 8 camera positions inside that slab,
the rendered frame is a flat brown wall and no amount of camera work fixes it.

None of it was noticed until the preview's camera actually moved
(`docs/plans/threejs-renderer-replacement.md` §6). Renders used to come out blank,
so these numbers were never checked. They are what the LLM wrote blind, under a
prompt that described the JSON shape and said nothing about size.

THE TABLE IS A MIRROR, NOT A SOURCE
The geometry itself lives in ``apps/web/src/features/agent-canvas/canvas/
sceneScriptGeometry.tsx``. This table is transcribed from it, and the two are held
together by ``sceneScriptGeometry.dimensions.test.ts``, which mounts every kind
and MEASURES the rendered bounding box rather than parsing the JSX. So an
error here fails a test instead of shipping a wrong number into a prompt.

Measurements are SceneScript space: metres, Z-up, at ``scale = 1``:

    width   extent along x (right)
    height  extent along z (up), from the ground
    depth   extent along y (forward)
    base    how far the geometry's underside floats above z = 0

``base`` is the field that hides the worst bug: a geometry whose ``base`` is
positive is a floating slab, and anything authored on the ground at z = 0 ends up
underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetDimensions:
    """Rendered size of one kind at ``scale = 1``, in metres."""

    width: float
    height: float
    depth: float
    base: float
    shape: str
    note: str = ""


#: Every kind ``PropType`` / ``EnvironmentType`` declares, plus ``lowpoly_human``.
#: A kind missing from here is a kind whose size the generator is told nothing
#: about — the completeness test treats that as a failure, not a default.
ASSET_DIMENSIONS: dict[str, AssetDimensions] = {
    # --- environment -------------------------------------------------------
    "ground": AssetDimensions(15.0, 0.1, 15.0, -0.1, "box", "site plate; scale 2 gives a 30 m square"),
    "floor": AssetDimensions(15.0, 0.1, 15.0, -0.1, "box"),
    "wall": AssetDimensions(6.0, 5.0, 0.3, 0.0, "box", "thin in depth: a WALL, not a block"),
    "pillar": AssetDimensions(0.6, 4.2, 0.6, 0.0, "cylinder", "scale 1 is 4.2 m — already a tall column"),
    "platform": AssetDimensions(5.0, 0.4, 5.0, 0.2, "box",
                                "FLOATS: the slab's underside is `base` above the ground"),
    "door": AssetDimensions(1.0, 2.2, 0.15, 0.0, "box", "about a person tall"),
    "window": AssetDimensions(1.4, 1.6, 0.12, 1.0, "box", "sill at `base` = 1 m"),
    "stairs": AssetDimensions(2.4, 1.0, 4.5, 0.1, "steps", "four treads climbing along depth"),
    "flat_roof": AssetDimensions(6.4, 0.25, 5.2, 5.075, "box", "sits on top of a 5 m wall"),
    "gable_roof": AssetDimensions(8.0, 3.0, 8.0, 4.0, "cone"),
    "tree": AssetDimensions(3.4, 5.1, 3.4, 0.0, "icosahedron"),
    "rock": AssetDimensions(2.52, 1.44, 1.98, -0.12, "icosahedron", "sits slightly buried"),
    "crater": AssetDimensions(4.8, 0.8, 4.8, 0.0, "dish",
                              "a shallow dish ringed by a raised rim, sitting ON the ground"),
    "fence": AssetDimensions(0.12, 0.8, 4.62, 0.4, "posts", "four posts spread over `depth`"),
    # --- props -------------------------------------------------------------
    "round_table": AssetDimensions(1.2, 0.775, 1.2, 0.0, "cylinder"),
    "rect_table": AssetDimensions(1.5, 0.05, 0.9, 0.725, "box", "a tabletop on legs; `base` is leg height"),
    "chair": AssetDimensions(0.5, 0.7, 0.515, 0.425, "cylinder", "`base` is seat height"),
    "stool": AssetDimensions(0.56, 0.53, 0.56, 0.0, "cylinder"),
    "lantern": AssetDimensions(0.3, 0.4, 0.3, 2.6, "cylinder", "HANGS: `base` is its hook height"),
    "box": AssetDimensions(0.8, 0.8, 0.8, 0.0, "box"),
    "crate": AssetDimensions(0.9, 0.9, 0.9, 0.0, "box"),
    "vase": AssetDimensions(0.28, 0.6, 0.28, 0.0, "cylinder"),
    "weapon": AssetDimensions(0.06, 1.37, 0.05, 0.18, "group", "a blade; scale 1.2 is a rifle"),
    "scroll": AssetDimensions(0.24, 0.9, 0.24, 0.55, "cylinder", "a rolled tube on a stand"),
    "book": AssetDimensions(0.34, 0.08, 0.26, 0.0, "box"),
    "cup": AssetDimensions(0.14, 0.14, 0.14, 0.0, "cylinder"),
    "chip": AssetDimensions(0.14, 0.025, 0.14, 0.0, "cylinder", "flat disc; base sits on the authored surface"),
    # --- characters --------------------------------------------------------
    "lowpoly_human": AssetDimensions(0.7, 1.8, 0.7, 0.0, "segments",
                                     "nine segments, knees included; `appearance.height` sets the real size"),
}

#: The size a SceneScript is implicitly written against. Every `scale` is
#: relative to this, so it is the unit the generator prompt reasons in.
REFERENCE_PERSON_HEIGHT = 1.75

#: The largest extent any kind may reach, as a multiple of the reference person.
#:
#: A single number rather than a per-kind taste table, because the failure it
#: prevents is always the same one: something big enough to dwarf the characters
#: standing in it. At 8 the jinghai recomposition -- the hand-tuned sample this was
#: checked against -- passes with room to spare (its tallest ratio is a `fence` at
#: 6.6x), while every value the doc calls out as absurd is rejected: a `pillar` at
#: 4.5 is 10.8x a person, a `wall` at 5 is 17.1x, a `platform` at 5 is 14.3x.
#:
#: 14 m is also simply a real ceiling for previs set dressing: taller than that and
#: the figure stops being a reference for the shot at all.
MAX_EXTENT_PERSON_HEIGHTS = 8.0

#: Kinds that ARE the ground, so no extent bound applies. A site plate is supposed
#: to be bigger than the people standing on it -- `ground` at scale 2 is a 30 m
#: square, which is the scene, not an object in it. Exempting them is why the rule
#: can be one number rather than a judgement per kind.
SITE_PLATE_KINDS = frozenset({"ground", "floor"})


def _largest_extent_at_scale_one(dims: AssetDimensions) -> float:
    return max(dims.width, dims.height, dims.depth)


def max_scale(kind: str) -> float | None:
    """The largest ``scale`` at which ``kind`` stays a plausible object.

    Derived from the rendered size rather than chosen per kind: a bound that let a
    ``cup`` reach 3 would also let a ``pillar`` reach 3, and a 12.6 m column beside
    a 1.85 m person is the bug this exists to catch. So the bound is whatever keeps
    the largest extent within the ceiling, which means small objects get a generous
    bound (correct -- a big cup hides nobody) and large ones get a tight one.

    ``None`` for a site plate or an unknown kind: no bound is better than a wrong
    one, and an unknown kind is already reported by the geometry completeness check.
    """
    dims = ASSET_DIMENSIONS.get(kind)
    if dims is None or kind in SITE_PLATE_KINDS:
        return None
    largest = _largest_extent_at_scale_one(dims)
    if largest <= 0:
        return None
    return (MAX_EXTENT_PERSON_HEIGHTS * REFERENCE_PERSON_HEIGHT) / largest


def scale_explanation(kind: str, scale: float) -> str | None:
    """Why ``scale`` is too large for ``kind``, in metres. ``None`` if it is fine.

    The message is the deliverable, not the rejection. The whole reason these values
    went unchecked is that the model writing the SceneScript had no idea what
    ``scale: 4.5`` meant for a ``pillar``; saying "scale 4.5 makes this 18.9 m tall,
    which is 10.8x a 1.75 m person" tells it what to write instead, where "le=50"
    told it nothing at all.
    """
    limit = max_scale(kind)
    dims = ASSET_DIMENSIONS.get(kind)
    if limit is None or dims is None or scale <= limit:
        return None
    # Not `rendered = rendered(...)`: that shadows the module-level function with a
    # local of the same name and the next line cannot find it.
    at_scale = rendered(kind, scale)
    assert at_scale is not None
    ceiling = MAX_EXTENT_PERSON_HEIGHTS * REFERENCE_PERSON_HEIGHT
    # Name the dimension that actually exceeds. Quoting the width for a pillar that
    # is too TALL reads as a contradiction -- "18.9 m tall, which is 1.5x a person"
    # -- and the author stops trusting the message.
    extents = {
        "wide": at_scale.width,
        "tall": at_scale.height,
        "deep": at_scale.depth,
    }
    worst_axis = max(extents, key=lambda axis: extents[axis])
    worst = extents[worst_axis]
    return (
        f"{kind} at scale {scale:g} renders {at_scale.width:g} m wide x "
        f"{at_scale.height:g} m tall x {at_scale.depth:g} m deep; the {worst_axis} "
        f"extent is {worst / REFERENCE_PERSON_HEIGHT:.1f}x a "
        f"{REFERENCE_PERSON_HEIGHT:g} m person. Set dressing may not exceed "
        f"{ceiling:g} m in any direction ({MAX_EXTENT_PERSON_HEIGHTS:g}x a person); "
        f"use scale {limit:.2f} or less for a {kind}."
    )


def kinds() -> list[str]:
    return sorted(ASSET_DIMENSIONS)


def rendered(kind: str, scale: float) -> AssetDimensions | None:
    """What ``kind`` measures at ``scale`` — the number a prompt needs."""
    base = ASSET_DIMENSIONS.get(kind)
    if base is None:
        return None
    return AssetDimensions(
        width=round(base.width * scale, 3),
        height=round(base.height * scale, 3),
        depth=round(base.depth * scale, 3),
        base=round(base.base * scale, 3),
        shape=base.shape,
        note=base.note,
    )


def floating_kinds() -> list[str]:
    """Kinds whose geometry floats, so anything at z = 0 is under them."""
    return [kind for kind, dims in ASSET_DIMENSIONS.items() if dims.base > 0]


def prompt_lines() -> list[str]:
    """One line per kind for the SceneScript generator prompt.

    Sized against a person rather than in bare multipliers, because "scale 4.5"
    reads as a modest number and is a 19 m column. A kind whose `base` is
    non-zero is called out, since that is the trap: authoring a character at
    z = 0 under a floating slab produces a frame that is entirely that slab.
    """
    lines: list[str] = []
    for kind in kinds():
        dims = ASSET_DIMENSIONS[kind]
        at_one = rendered(kind, 1.0)
        assert at_one is not None
        flag = ""
        if dims.base > 0:
            flag = f"  [FLOATS {dims.base:g} m above the ground — anything at z=0 is under it]"
        note = f"  ({dims.note})" if dims.note else ""
        # The limit, not just the size. `SceneProp.scale` and
        # `SceneEnvironmentObject.scale` reject anything past it, so a prompt that
        # gives the size but not the ceiling still lets the model write a value that
        # bounces off the schema — the exact blind-writing this table exists to stop.
        limit = max_scale(kind)
        ceiling = (
            f"; scale {limit:.2f} max"
            if limit is not None
            else "; no scale limit (this is the ground)"
        )
        lines.append(
            f"  {kind:<14} scale 1.0 = {at_one.width:g} m wide x {at_one.height:g} m tall "
            f"x {at_one.depth:g} m deep{ceiling}{note}{flag}"
        )
    return lines
