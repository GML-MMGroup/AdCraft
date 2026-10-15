"""SceneScript to Blender Python script converter.

Converts a validated SceneScriptRoot into a self-contained Blender Python
script that builds the scene and renders an animation. The converter is a
pure function (SceneScript in -> str out) and can be unit-tested without
Blender.

The generated script uses only primitive geometry (cubes, spheres, cylinders,
cones) for low-fidelity previs. No external assets or textures are required.

See: docs/3d-previs/blender-integration-guide.md
"""

from __future__ import annotations

from typing import Any

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.held_items import held_keyframe_positions

# Imported rather than reimplemented: the draft pass must render exactly the
# frames ``extract_keyframes`` copies and ``control_passes`` aligns to, or a
# keyframe deliverable would silently miss frames the full pass produces.
from app.services.scene3d import character_pose, held_item_grip, object_motion
from app.services.scene3d import rotation_pivot
from app.services.scene3d.keyframes import _shot_keyframe_frames
from app.services.scene3d.rotation_pivot import needs_pivot_empty, rotation_pivot_for


def _esc(s: str) -> str:
    """Escape a string for use in a Python string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _vec(v: list[float]) -> str:
    """Format a 3D vector as a Python tuple literal."""
    return f"({v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f})"


# ---------------------------------------------------------------------------
# Asset builders (return Blender code fragments)
# ---------------------------------------------------------------------------


def _build_lowpoly_human(
    obj_id: str,
    color: str,
    height: float,
    scale: float,
    show_pose_marker: bool = False,
) -> str:
    """Build a low-poly human: head, torso, two arms, two legs.

    This used to be a cube with a sphere on top, which is a mannequin, not a
    person -- and it is what every character reference in the product was built
    from.  A 人物三视图 rendered from it documents the existence of a character
    and their colour and nothing else: no silhouette to hold on to, no shoulders
    to read, no way to tell a walk from a stance.  Binding that sheet into a
    video prompt would tell the model "the character is a magenta box", which is
    worse than sending nothing.

    So the figure now has the parts a silhouette is read from.  Proportions are
    a stylised 7.5-head figure scaled off the script's own `height`, so a 1.65 m
    character and a 1.9 m character differ the way two people do rather than the
    way two boxes do.  Flat-shaded primitives throughout: this is previs, and
    Eevee has to keep 480 frames inside a render timeout.
    """
    h = height * scale
    # Segment boundaries as a fraction of total height: feet at 0, crown at ~h.
    leg_h = 0.50 * h
    torso_h = 0.30 * h
    torso_bottom = leg_h
    torso_top = torso_bottom + torso_h
    neck_h = 0.03 * h
    head_r = 0.11 * h
    head_z = torso_top + neck_h + head_r * 0.85
    arm_h = 0.30 * h
    arm_z = torso_top - arm_h * 0.55
    limb_w = 0.055 * h
    torso_w = 0.30 * h
    torso_d = 0.16 * h

    def _limb(part: str, cx: float, cz: float, w: float, d: float, box_h: float) -> str:
        """One limb: a box of full height `box_h`, centred at (cx, 0, cz).

        Blender puts a primitive's origin at its own centre, so rotating the box
        directly would ORBIT the limb rather than swing it -- a foot 1 m below the hip
        would trace a circle instead of staying put, which is the same defect the
        prop rotation pivot fixed. So each limb hangs off an empty at its proximal
        (top) end, and the pose library rotates that.
        """
        return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=({cx:.4f}, 0, {cz:.4f}))
{part} = bpy.context.object
{part}.name = "{_esc(obj_id)}_{part}"
{part}.scale = ({w:.4f}, {d:.4f}, {box_h:.4f})
bpy.ops.object.empty_add(type='PLAIN_AXES', location=({cx:.4f}, 0, {cz + box_h / 2:.4f}))
{part}_pivot = bpy.context.object
{part}_pivot.name = "{_esc(obj_id)}_{part}_pivot"
{part}.parent = {part}_pivot
{part}.matrix_parent_inverse = {part}_pivot.matrix_world.inverted()"""

    def _leg(part: str, shin: str, cx: float) -> str:
        """One leg as thigh + shin, so it has a knee.

        A single box hinged at the hip cannot walk: a rigid leg's foot is at the
        same height going forward as coming back, so the swing leg passes through
        the floor. Splitting it is the whole point -- and the split is only
        visible if the shin is PARENTED to the knee empty rather than to the hip,
        so the knee angle is relative to the thigh the way a real knee is.

        The knee sits halfway down (`KNEE_FRACTION_OF_LEG`), which is the fraction
        the pose library's foot-lift arithmetic assumes. Moving one without the
        other would put the measured clearance and the rendered clearance apart.
        """
        shin_h = leg_h * character_pose.KNEE_FRACTION_OF_LEG
        thigh_h = leg_h - shin_h
        return f"""
{_limb(part, cx, leg_h - thigh_h / 2, limb_w, limb_w * 1.2, thigh_h)}
bpy.ops.mesh.primitive_cube_add(size=1, location=({cx:.4f}, 0, {shin_h / 2:.4f}))
{shin} = bpy.context.object
{shin}.name = "{_esc(obj_id)}_{shin}"
{shin}.scale = ({limb_w:.4f}, {limb_w * 1.2:.4f}, {shin_h:.4f})
bpy.ops.object.empty_add(type='PLAIN_AXES', location=({cx:.4f}, 0, {shin_h:.4f}))
{shin}_pivot = bpy.context.object
{shin}_pivot.name = "{_esc(obj_id)}_{shin}_pivot"
{shin}_pivot.parent = {part}_pivot
{shin}_pivot.matrix_parent_inverse = {part}_pivot.matrix_world.inverted()
{shin}.parent = {shin}_pivot
{shin}.matrix_parent_inverse = {shin}_pivot.matrix_world.inverted()"""

    face_marker = f"""
# Authored pose marker: legacy characters keep their previous appearance.
bpy.ops.mesh.primitive_uv_sphere_add(radius={head_r * 0.16:.4f}, location=(0, {head_r * 0.9:.4f}, {head_z + head_r * 0.08:.4f}))
nose = bpy.context.object
nose.name = "{_esc(obj_id)}_Nose"
nose.data.materials.append(mat_head)
nose.parent = head_pivot
nose.matrix_parent_inverse = head_pivot.matrix_world.inverted()
""" if show_pose_marker else ""

    return f"""
# Character: {_esc(obj_id)}
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {torso_bottom + torso_h / 2:.4f}))
body = bpy.context.object
body.name = "{_esc(obj_id)}_Body"
body.scale = ({torso_w:.4f}, {torso_d:.4f}, {torso_h:.4f})
mat_body = bpy.data.materials.new(name="{_esc(obj_id)}_BodyMat")
mat_body.use_nodes = True
mat_body.node_tree.nodes["Principled BSDF"].inputs[0].default_value = ({_hex_to_rgb(color)}, 1.0)
body.data.materials.append(mat_body)
{_leg("LegL", "ShinL", -0.075 * h)}
{_leg("LegR", "ShinR", 0.075 * h)}
{_limb("ArmL", -(torso_w / 2 + limb_w * 0.6), arm_z, limb_w * 0.8, limb_w * 0.8, arm_h)}
{_limb("ArmR", torso_w / 2 + limb_w * 0.6, arm_z, limb_w * 0.8, limb_w * 0.8, arm_h)}
bpy.ops.mesh.primitive_cylinder_add(radius={limb_w * 0.55:.4f}, depth={neck_h:.4f},
                                    location=(0, 0, {torso_top + neck_h / 2:.4f}))
neck = bpy.context.object
neck.name = "{_esc(obj_id)}_Neck"
bpy.ops.mesh.primitive_uv_sphere_add(radius={head_r:.4f}, location=(0, 0, {head_z:.4f}))
head = bpy.context.object
head.name = "{_esc(obj_id)}_Head"
# The head pivots at the neck, so a gesture tips it forward instead of rolling it.
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, {torso_top + neck_h:.4f}))
head_pivot = bpy.context.object
head_pivot.name = "{_esc(obj_id)}_Head_pivot"
head.parent = head_pivot
head.matrix_parent_inverse = head_pivot.matrix_world.inverted()
mat_head = bpy.data.materials.new(name="{_esc(obj_id)}_HeadMat")
mat_head.use_nodes = True
mat_head.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.9, 0.8, 0.7, 1.0)
head.data.materials.append(mat_head)
{face_marker}
"""


def _build_round_table(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cylinder_add(radius={0.6 * scale:.4f}, depth=0.05, location=(0, 0, 0.75))
top = bpy.context.object
top.name = "{_esc(obj_id)}_Top"
bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.75, location=(0, 0, 0.375))
leg = bpy.context.object
leg.name = "{_esc(obj_id)}_Leg"
"""


def _build_pillar(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cylinder_add(radius={0.3 * scale:.4f}, depth={4.2 * scale:.4f}, location=(0, 0, {2.1 * scale:.4f}))
pillar = bpy.context.object
pillar.name = "{_esc(obj_id)}"
"""


def _build_wall(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {2.5 * scale:.4f}))
wall = bpy.context.object
wall.name = "{_esc(obj_id)}"
wall.scale = ({6.0 * scale:.4f}, {0.3 * scale:.4f}, {5.0 * scale:.4f})
"""


def _build_floor(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.05))
floor = bpy.context.object
floor.name = "{_esc(obj_id)}"
floor.scale = ({15.0 * scale:.4f}, {15.0 * scale:.4f}, 0.1)
"""


def _build_gable_roof(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cone_add(vertices=4, radius1={4.0 * scale:.4f}, depth={3.0 * scale:.4f}, location=(0, 0, {5.5 * scale:.4f}))
roof = bpy.context.object
roof.name = "{_esc(obj_id)}"
roof.rotation_euler.z = math.radians(45)
"""


def _build_door(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {1.1 * scale:.4f}))
door = bpy.context.object
door.name = "{_esc(obj_id)}"
door.scale = ({1.0 * scale:.4f}, {0.15 * scale:.4f}, {2.2 * scale:.4f})
"""


def _build_lantern(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {2.8 * scale:.4f}))
lantern = bpy.context.object
lantern.name = "{_esc(obj_id)}"
lantern.scale = ({0.3 * scale:.4f}, {0.3 * scale:.4f}, {0.4 * scale:.4f})
"""


def _build_tree(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cylinder_add(radius={0.22 * scale:.4f}, depth={2.6 * scale:.4f}, location=(0, 0, {1.3 * scale:.4f}))
trunk = bpy.context.object
trunk.name = "{_esc(obj_id)}_Trunk"
bpy.ops.mesh.primitive_ico_sphere_add(radius={1.7 * scale:.4f}, subdivisions=1, location=(0, 0, {3.4 * scale:.4f}))
canopy = bpy.context.object
canopy.name = "{_esc(obj_id)}_Canopy"
"""


def _build_platform(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.4 * scale:.4f}))
platform = bpy.context.object
platform.name = "{_esc(obj_id)}"
platform.scale = ({5.0 * scale:.4f}, {5.0 * scale:.4f}, {0.4 * scale:.4f})
"""


def _build_stairs(obj_id: str, scale: float) -> str:
    steps = 5
    lines = [
        f"for _i in range({steps}):",
        f"    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.2 * scale:.4f} * (_i + 1)))",
        "    _step = bpy.context.object",
        f"    _step.name = \"{_esc(obj_id)}_Step%02d\" % _i",
        f"    _step.scale = ({2.4 * scale:.4f}, {0.9 * scale:.4f}, {0.2 * scale:.4f})",
        f"    _step.location.y = {0.9 * scale:.4f} * _i",
    ]
    return "\n" + "\n".join(lines) + "\n"


def _build_rock(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_ico_sphere_add(radius={0.9 * scale:.4f}, subdivisions=1, location=(0, 0, {0.6 * scale:.4f}))
rock = bpy.context.object
rock.name = "{_esc(obj_id)}"
rock.scale = ({1.4 * scale:.4f}, {1.1 * scale:.4f}, {0.8 * scale:.4f})
"""


def _build_crater(obj_id: str, scale: float) -> str:
    # Both parts sit ON the ground rather than being cut into it. A crater dug
    # below grade is invisible: the site plate is a solid box, so anything under
    # its top face is occluded and the result reads as a bare ring. The dish has
    # to be at grade to be seen at all.
    return f"""
bpy.ops.mesh.primitive_torus_add(major_radius={2.0 * scale:.4f}, minor_radius={0.4 * scale:.4f},
                                major_segments=16, minor_segments=6, location=(0, 0, {0.4 * scale:.4f}))
crater_rim = bpy.context.object
crater_rim.name = "{_esc(obj_id)}_rim"
bpy.ops.mesh.primitive_cylinder_add(radius={1.7 * scale:.4f}, depth={0.12 * scale:.4f}, location=(0, 0, {0.06 * scale:.4f}))
crater_floor = bpy.context.object
crater_floor.name = "{_esc(obj_id)}"
"""


def _build_fence(obj_id: str, scale: float) -> str:
    posts = 4
    lines = [
        f"for _i in range({posts}):",
        f"    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.8 * scale:.4f}))",
        "    _post = bpy.context.object",
        f"    _post.name = \"{_esc(obj_id)}_Post%02d\" % _i",
        f"    _post.scale = ({0.12 * scale:.4f}, {0.12 * scale:.4f}, {0.8 * scale:.4f})",
        f"    _post.location.y = {1.5 * scale:.4f} * (_i - 1.5)",
    ]
    return "\n" + "\n".join(lines) + "\n"


def _build_window(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {1.8 * scale:.4f}))
window = bpy.context.object
window.name = "{_esc(obj_id)}"
window.scale = ({1.4 * scale:.4f}, {0.12 * scale:.4f}, {1.6 * scale:.4f})
"""


def _build_flat_roof(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {5.2 * scale:.4f}))
roof = bpy.context.object
roof.name = "{_esc(obj_id)}"
roof.scale = ({6.4 * scale:.4f}, {5.2 * scale:.4f}, {0.25 * scale:.4f})
"""


def _build_rect_table(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.75 * scale:.4f}))
table = bpy.context.object
table.name = "{_esc(obj_id)}"
table.scale = ({1.5 * scale:.4f}, {0.9 * scale:.4f}, {0.05 * scale:.4f})
for _i, (_ox, _oy) in enumerate(((-0.65, -0.35), (0.65, -0.35), (-0.65, 0.35), (0.65, 0.35))):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(_ox * {scale:.4f}, _oy * {scale:.4f}, {0.36 * scale:.4f}))
    _leg = bpy.context.object
    _leg.name = "{_esc(obj_id)}_Leg%02d" % _i
    _leg.scale = ({0.08 * scale:.4f}, {0.08 * scale:.4f}, {0.36 * scale:.4f})
"""


def _build_chair(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.45 * scale:.4f}))
seat = bpy.context.object
seat.name = "{_esc(obj_id)}_Seat"
seat.scale = ({0.5 * scale:.4f}, {0.5 * scale:.4f}, {0.05 * scale:.4f})
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, {-0.24 * scale:.4f}, {0.9 * scale:.4f}))
back = bpy.context.object
back.name = "{_esc(obj_id)}_Back"
back.scale = ({0.5 * scale:.4f}, {0.05 * scale:.4f}, {0.45 * scale:.4f})
for _i, (_ox, _oy) in enumerate(((-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2), (0.2, 0.2))):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(_ox * {scale:.4f}, _oy * {scale:.4f}, {0.22 * scale:.4f}))
    _leg = bpy.context.object
    _leg.name = "{_esc(obj_id)}_Leg%02d" % _i
    _leg.scale = ({0.05 * scale:.4f}, {0.05 * scale:.4f}, {0.22 * scale:.4f})
"""


def _build_stool(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cylinder_add(radius={0.28 * scale:.4f}, depth=0.06, location=(0, 0, {0.5 * scale:.4f}))
seat = bpy.context.object
seat.name = "{_esc(obj_id)}_Seat"
bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth={0.5 * scale:.4f}, location=(0, 0, {0.25 * scale:.4f}))
leg = bpy.context.object
leg.name = "{_esc(obj_id)}_Leg"
"""


def _build_box(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.4 * scale:.4f}))
box = bpy.context.object
box.name = "{_esc(obj_id)}"
box.scale = ({0.8 * scale:.4f}, {0.8 * scale:.4f}, {0.8 * scale:.4f})
"""


def _build_crate(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.45 * scale:.4f}))
crate = bpy.context.object
crate.name = "{_esc(obj_id)}"
crate.scale = ({0.9 * scale:.4f}, {0.9 * scale:.4f}, {0.9 * scale:.4f})
"""


def _build_vase(obj_id: str, scale: float) -> str:
    # A vase is a tapered solid: primitive_cylinder_add takes a single `radius`,
    # so the top/bottom radii this builder means can only be expressed with
    # primitive_cone_add (radius1/radius2). Passing radius1/radius2 to the
    # cylinder operator raises "keyword unrecognized" inside bpy and took the
    # whole render down with it.
    return f"""
bpy.ops.mesh.primitive_cone_add(radius1={0.24 * scale:.4f}, radius2={0.14 * scale:.4f}, depth={0.6 * scale:.4f}, location=(0, 0, {0.3 * scale:.4f}))
vase = bpy.context.object
vase.name = "{_esc(obj_id)}"
"""


def _build_weapon(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {1.0 * scale:.4f}))
blade = bpy.context.object
blade.name = "{_esc(obj_id)}_Blade"
blade.scale = ({0.06 * scale:.4f}, {0.02 * scale:.4f}, {1.1 * scale:.4f})
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.32 * scale:.4f}))
grip = bpy.context.object
grip.name = "{_esc(obj_id)}_Grip"
grip.scale = ({0.05 * scale:.4f}, {0.05 * scale:.4f}, {0.28 * scale:.4f})
"""


def _build_scroll(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cylinder_add(radius={0.12 * scale:.4f}, depth={0.9 * scale:.4f}, location=(0, 0, {1.0 * scale:.4f}))
scroll = bpy.context.object
scroll.name = "{_esc(obj_id)}"
scroll.rotation_euler.x = math.radians(90)
"""


def _build_book(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {0.04 * scale:.4f}))
book = bpy.context.object
book.name = "{_esc(obj_id)}"
book.scale = ({0.34 * scale:.4f}, {0.26 * scale:.4f}, {0.08 * scale:.4f})
"""


def _build_cup(obj_id: str, scale: float) -> str:
    # Tapered, so primitive_cone_add -- see _build_vase for why the cylinder
    # operator's single `radius` cannot express a top/bottom pair.
    return f"""
bpy.ops.mesh.primitive_cone_add(radius1={0.09 * scale:.4f}, radius2={0.07 * scale:.4f}, depth={0.14 * scale:.4f}, location=(0, 0, {0.07 * scale:.4f}))
cup = bpy.context.object
cup.name = "{_esc(obj_id)}"
"""


def _build_generic_box(obj_id: str, scale: float, size: float = 0.5) -> str:
    return f"""
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, {size * scale / 2:.4f}))
box = bpy.context.object
box.name = "{_esc(obj_id)}"
box.scale = ({size * scale:.4f}, {size * scale:.4f}, {size * scale:.4f})
"""


def _build_chip(obj_id: str, scale: float) -> str:
    return f"""
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius={0.07 * scale:.4f}, depth={0.025 * scale:.4f}, location=(0, 0, {0.0125 * scale:.4f}))
chip = bpy.context.object
chip.name = "{_esc(obj_id)}_Disk"
"""


_ASSET_BUILDERS: dict[str, Any] = {
    "lowpoly_human": _build_lowpoly_human,
    "round_table": _build_round_table,
    "rect_table": _build_rect_table,
    "pillar": _build_pillar,
    "wall": _build_wall,
    "floor": _build_floor,
    "ground": _build_floor,
    "gable_roof": _build_gable_roof,
    "flat_roof": _build_flat_roof,
    "door": _build_door,
    "window": _build_window,
    "stairs": _build_stairs,
    "platform": _build_platform,
    "tree": _build_tree,
    "rock": _build_rock,

    "crater": _build_crater,
    "fence": _build_fence,
    "lantern": _build_lantern,
    "chair": _build_chair,
    "stool": _build_stool,
    "box": _build_box,
    "crate": _build_crate,
    "vase": _build_vase,
    "weapon": _build_weapon,
    "scroll": _build_scroll,
    "book": _build_book,
    "cup": _build_cup,
    "chip": _build_chip,
}


def _hex_to_rgb(hex_color: str) -> str:
    """Convert #RRGGBB to 'r, g, b' string."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "0.5, 0.5, 0.5"
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return f"{r:.4f}, {g:.4f}, {b:.4f}"


# ---------------------------------------------------------------------------
# Asset colours
# ---------------------------------------------------------------------------

# Every prop/environment kind had geometry but no material, so Blender fell
# back to its default viewport grey and the whole previs frame came out
# monochrome -- 0 chromatic pixels out of 518400 measured on an all-types
# render. A grey box is also exactly what a *degraded* asset looks like, which
# made ADR 0005's "never silent" guarantee hollow: the placeholder and the
# faithful render were indistinguishable on screen. Colour is assigned here
# rather than inside each builder so there is one source of truth and the
# degraded colour can be unmistakable.
_ASSET_COLORS: dict[str, str] = {
    "round_table": "#8B5A2B",
    "rect_table": "#A9743F",
    "pillar": "#C4B79B",
    "wall": "#CDBFA3",
    "floor": "#7A6748",
    "ground": "#6E7A45",
    "gable_roof": "#8C4A38",
    "flat_roof": "#5A5A62",
    "door": "#5C3A21",
    "window": "#A8CBD8",
    "stairs": "#96795A",
    "platform": "#8A7554",
    "tree": "#6B4A2A",
    "rock": "#82807A",
    "crater": "#6B5F52",
    "fence": "#7E6242",
    "lantern": "#E8B84B",
    "chair": "#7A5230",
    "stool": "#9C6B3F",
    "box": "#B08D57",
    "crate": "#8C6239",
    "vase": "#C86B8A",
    "weapon": "#9AA3AD",
    "scroll": "#E8DCC0",
    "book": "#8B3A3A",
    "cup": "#D9D8D0",
    "chip": "#32B7A5",
}

# A placeholder must never be mistaken for geometry. Magenta is the usual
# "missing asset" colour precisely because no natural surface is that colour.
_DEGRADED_ASSET_COLOR = "#FF2BD1"

# Multi-part assets whose parts mean different materials. Keyed by the part
# name suffix the builders assign, so a tree reads as a trunk under a canopy
# rather than one brown mass.
_PART_COLOR_OVERRIDES: dict[str, str] = {
    "_Trunk": "#6B4A2A",
    "_Canopy": "#4E7A3A",
    "_Blade": "#9AA3AD",
    "_Grip": "#4A3524",
}


def asset_color(obj_type: str, degraded: bool = False) -> str:
    """Colour a declared asset type renders in, as a ``#RRGGBB`` string."""

    if degraded:
        return _DEGRADED_ASSET_COLOR
    return _ASSET_COLORS.get(obj_type, "#B08D57")


def keyframe_render_frames(scene_script: SceneScriptRoot) -> list[int]:
    """Every frame the draft pass renders: each shot's 5 keyframes, unioned.

    A 6-shot, 4s/30fps scene renders 240 frames for the full animation but only
    ~24 for the draft (shots often share a 0% frame, and adjacent-shots'
    keyframes can coincide), which is the whole point of the draft pass.  The
    union is sorted so the generated loop is deterministic, and the frames are
    0-based SceneScript numbers, matching :func:`_shot_keyframe_frames`.
    """
    frames: set[int] = set()
    for shot in scene_script.shots:
        frames.update(_shot_keyframe_frames(shot))
    return sorted(frames)


def degraded_asset_ids(scene_script: SceneScriptRoot) -> tuple[str, ...]:
    """Return the environment/prop ids that will render as placeholder boxes.

    Mirrors the lookup in :func:`_build_asset` so the renderer can report the
    degradation without re-parsing the generated Blender script.
    """

    degraded: list[str] = []
    for group in (scene_script.environment or (), scene_script.props or ()):
        for asset in group:
            if asset.type not in _ASSET_BUILDERS:
                degraded.append(f"{asset.id}:{asset.type}")
    return tuple(degraded)


def _pivot_parent_code(obj_id: str, obj_type: str, position: list[float], scale: float) -> str:
    """Emit an empty at the asset's pivot and re-parent the wrapper under it.

    Rotation is applied to this empty instead of to the wrapper, which is what makes
    a keyframed pitch or roll turn the object on itself instead of sweeping it around
    its own base. A crate turning 360 deg drifted 123 px of silhouette travel before
    this; it drifts 8 px after, and that residual is just the cube's silhouette
    growing as |cos| + |sin|.

    The pivot empty sits at ``position + offset`` and the wrapper is re-expressed
    relative to it, so the asset's world position is unchanged -- only the point it
    turns about moves.

    Returns an empty string for kinds that turn about their base, so their generated
    script is byte-identical to before.
    """
    if not needs_pivot_empty(obj_type):
        return ""
    px, py, pz = rotation_pivot_for(obj_type)
    offset = [px * scale, py * scale, pz * scale]
    pivot_at = [position[i] + offset[i] for i in range(3)]
    return f"""
# Rotation pivot for {_esc(obj_id)} ({obj_type}): turn about this point, not the
# object's base. See rotation_pivot.py for why this is per-kind rather than a rule.
bpy.ops.object.empty_add(type="PLAIN_AXES", location={_vec(pivot_at)})
pivot_{_esc(obj_id)} = bpy.context.object
pivot_{_esc(obj_id)}.name = "{_esc(obj_id)}_pivot"
wrapper = bpy.data.objects["{_esc(obj_id)}"]
wrapper.parent = pivot_{_esc(obj_id)}
# Blender resolves a child's location against its parent, so the wrapper is now
# relative to the pivot: minus the offset puts it back where it was authored.
wrapper.location = {_vec([-o for o in offset])}
# Keyframed pivot angles replace the rest rotation; do not apply yaw twice.
wrapper.rotation_euler = (0, 0, 0)
"""


def _build_asset(obj_id: str, obj_type: str, position: list[float], rotation_y: float,
                 scale: float = 1.0,
                 color: str = "#8B4513", height: float = 1.7,
                 show_pose_marker: bool = False) -> str:
    """Build an asset at the given position with a wrapper empty."""
    builder = _ASSET_BUILDERS.get(obj_type)
    if builder is None:
        builder = _build_generic_box
        code = builder(obj_id, scale)
        # Leave an explicit trace in the generated script.  A placeholder box
        # must never be indistinguishable from a faithful render (ADR 0005):
        # the trace names it, the colour makes it obvious on screen.
        degraded_marker = (
            f"# PREVIS_DEGRADED_ASSET: {obj_id} ({obj_type}) -- "
            "no geometry for this type, rendered as a placeholder box"
        )
    elif obj_type == "lowpoly_human":
        code = builder(obj_id, color, height, scale, show_pose_marker=show_pose_marker)
        degraded_marker = ""
    else:
        code = builder(obj_id, scale)
        degraded_marker = ""

    base_rgb = _hex_to_rgb(asset_color(obj_type, degraded=bool(degraded_marker)))
    # Emitted as a literal so the generated script carries no dependency on
    # this module; the part overrides keep multi-part assets readable.
    overrides = ", ".join(
        f'"{suffix}": ({_hex_to_rgb(hex_value)})'
        for suffix, hex_value in _PART_COLOR_OVERRIDES.items()
    )

    return f"""
# Asset: {_esc(obj_id)} ({obj_type})
{degraded_marker}
bpy.ops.object.empty_add(type="PLAIN_AXES", location={_vec(position)})
wrapper = bpy.context.object
wrapper.name = "{_esc(obj_id)}"
wrapper.rotation_euler.z = -math.radians({rotation_y:.2f})
_parts_before = set(bpy.data.objects)
{code}
# Give every part a material. Parts that already have one (a character colours
# its own body and head) keep it, so this only reaches props and environment
# that would otherwise render in Blender's default grey.
_part_colors = {{{overrides}}}
_part_materials = {{}}
# Parent every newly created part to the wrapper. We diff bpy.data.objects
# instead of iterating bpy.context.selected_objects because each successive
# primitive_add deselects the previous part (e.g. adding the head sphere
# deselects the body cube), which otherwise left the first part unparented at
# the world origin (characters rendered as floating heads).
for _part in [o for o in bpy.data.objects if o not in _parts_before and o is not wrapper]:
    # Primitive builders often request the asset id for their mesh too.
    # Blender adds a numeric collision suffix; give that mesh an explicit name
    # and keep the canonical id on the wrapper used by motion keyframes.
    if (_part.name == "{_esc(obj_id)}" or
        (_part.name.startswith("{_esc(obj_id)}.") and
         _part.name[len("{_esc(obj_id)}."):].isdecimal())):
        _part.name = "{_esc(obj_id)}_Mesh"
    # A limb already hangs off its own proximal pivot so the pose library can swing
    # it. Re-parenting it to the wrapper here would flatten that chain and the limb
    # would orbit its own centre again, so only unparented parts are adopted --
    # the pivots themselves are new and get adopted, which is what carries the whole
    # rig along with the character.
    if _part.parent is not None:
        continue
    _part.parent = wrapper
    if _part.type != 'MESH' or _part.data.materials:
        continue
    _rgb = ({base_rgb})
    for _suffix, _override in _part_colors.items():
        if _part.name.endswith(_suffix):
            _rgb = _override
            break
    _mat = _part_materials.get(_rgb)
    if _mat is None:
        _mat = bpy.data.materials.new(name="{_esc(obj_id)}_Mat")
        _mat.use_nodes = True
        _mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (
            _rgb[0], _rgb[1], _rgb[2], 1.0,
        )
        _part_materials[_rgb] = _mat
    _part.data.materials.append(_mat)
wrapper.name = "{_esc(obj_id)}"
bpy.ops.object.select_all(action="DESELECT")
"""


# ---------------------------------------------------------------------------
# Main converter
# ---------------------------------------------------------------------------


def _last_frame(script: SceneScriptRoot) -> int:
    """The highest frame the script animates, so a walk cycle can be filled in.

    Shots, not ``scene.duration``: the preview derives its frame count the same way
    (``PrevisRenderEntry``), and a pose emitted past the last shot would be keyed on
    frames nobody renders.
    """
    candidates = [shot.end_frame for shot in script.shots]
    if candidates:
        return max(candidates)
    if script.characters:
        return max(kf.frame for char in script.characters for kf in char.keyframes)
    return 0


#: Blender limb names, mapped to the pose library's fields. The preview's POSE_FIELD
#: is the other half of this map; a joint rotated on one side only is a disagreement
#: nobody would notice in a still frame.
_LIMB_POSE_FIELDS = (
    ("LegL", "leg_l"),
    ("LegR", "leg_r"),
    ("ShinL", "knee_l"),
    ("ShinR", "knee_r"),
    ("ArmL", "arm_l"),
    ("ArmR", "arm_r"),
)

def _character_pose_code(char, script, total_frames: int) -> list[str]:
    """Keyframe the character's joints from the pose library.

    Without this the converter read ``position`` and ``rotation_y`` and ignored
    ``action`` entirely, so under the DEFAULT blender backend a ``walk`` rendered as a
    figure sliding along the ground with its limbs welded in place -- the "moonwalk"
    the preview no longer has. Silently: nothing in the script said so.

    Write the complete pose EVERY FRAME, including zero angles and held actions.
    Action selection is STEP: sparse keys would let Blender ease toward a future
    action before its boundary, and omitted zeros would leave old joint bends alive.
    Linear interpolation between adjacent samples preserves the pose at integer
    frames; subframes may blend across the single interval at an action boundary.

    The pivots themselves are created by the limb builders, which know where each
    limb's proximal end is; this only drives them.
    """
    if total_frames <= 0:
        return []

    leg_length = 0.5 * char.appearance.height * char.appearance.scale
    actions = [kf.action for kf in char.keyframes]
    positions = [list(kf.position) for kf in char.keyframes]
    frames = [kf.frame for kf in char.keyframes]
    poses = [
        pose.model_dump(exclude_none=True) if pose is not None else None
        for pose in (getattr(kf, "pose", None) for kf in char.keyframes)
    ]
    pose_channels = {field for pose in poses if pose is not None for field in pose}
    side_channels = [
        (limb, field) for limb, field in (("ArmL", "arm_l_side"), ("ArmR", "arm_r_side"))
        if field in pose_channels
    ]
    # Which hand is carrying something, from the scene's own `held_by` links. Same
    # reader the preview uses, so the arm that reaches and the item that is held
    # cannot disagree about which side that is.
    held_side = character_pose.held_sides_by_character(script).get(char.id)

    lines = [
        "# === POSE: " + _esc(char.id) + " ===",
        "# Actions: " + ", ".join(sorted({str(a) for a in actions})) +
        f"; leg {leg_length:.3f} m. Phase comes from distance travelled, so a",
        "# stationary character keeps both feet down.",
        "# The vertical bob rides an empty above the wrapper rather than the",
        "# wrapper's own location, which carries the authored position.",
    ]
    if held_side:
        lines.append(
            f"# Carrying something in the {held_side} hand: that arm pitches "
            f"{held_item_grip.hold_arm_pitch_degrees():.1f} deg "
            "forward so the hand reaches the grip the item is placed at. Without "
            "this the item floats beside an empty hand."
        )
    lines.extend([
        "bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))",
        f"bob_{_esc(char.id)} = bpy.context.object",
        f"bob_{_esc(char.id)}.name = {char.id + '_bob'!r}",
        f"bpy.data.objects[{char.id!r}].parent = bob_{_esc(char.id)}",
        "",
    ])
    for limb, _ in _LIMB_POSE_FIELDS:
        lines.append(f"_p_{_esc(char.id)}{limb} = bpy.data.objects[{char.id + '_' + limb + '_pivot'!r}]")
    lines.append(f"_p_{_esc(char.id)}Head = bpy.data.objects[{char.id + '_Head_pivot'!r}]")
    # Three's XYZ matrix order maps to Blender ZYX after reflecting Y/Z.
    # Single-axis legacy pitches are unchanged; only new compound channels opt in.
    for limb, _ in side_channels:
        lines.append(f"_p_{_esc(char.id)}{limb}.rotation_mode = 'ZYX'")
    if "head_yaw" in pose_channels:
        lines.append(f"_p_{_esc(char.id)}Head.rotation_mode = 'ZYX'")
    lines.append("")

    for frame in range(total_frames + 1):
        pose = character_pose.pose_at_frame(
            actions, positions, frames, frame, leg_length, holding=held_side,
            poses=poses,
        )
        bob = pose.get("bob", 0.0) * char.appearance.height * char.appearance.scale
        blender_frame = frame + 1
        lines.append(f"# frame {frame}")
        lines.append(
            f"bob_{_esc(char.id)}.location = (0, 0, {bob:.6f})"
        )
        lines.append(
            f"bob_{_esc(char.id)}.keyframe_insert(data_path='location', frame={blender_frame})"
        )
        for limb, field in _LIMB_POSE_FIELDS:
            # Preview coordinates swap Y/Z without a sign: this reflection reverses
            # X pitch. Hip/arm pitch is -pose; relative knee flexion is +pose, so
            # Blender's world shin angle is -(thigh - knee), matching the preview.
            angle = pose.get(field, 0.0) * (1 if field in {"knee_l", "knee_r"} else -1)
            lines.append(f"_p_{_esc(char.id)}{limb}.rotation_euler.x = {angle:.6f}")
            lines.append(
                f"_p_{_esc(char.id)}{limb}.keyframe_insert("
                f"data_path='rotation_euler', index=0, frame={blender_frame})"
            )
        head = -pose.get("head", 0.0)
        lines.append(f"_p_{_esc(char.id)}Head.rotation_euler.x = {head:.6f}")
        lines.append(
            f"_p_{_esc(char.id)}Head.keyframe_insert("
            f"data_path='rotation_euler', index=0, frame={blender_frame})"
        )
        for limb, field in side_channels:
            side = -pose.get(field, 0.0)
            lines.append(f"_p_{_esc(char.id)}{limb}.rotation_euler.y = {side:.6f}")
            lines.append(
                f"_p_{_esc(char.id)}{limb}.keyframe_insert("
                f"data_path='rotation_euler', index=1, frame={blender_frame})"
            )
        if "head_yaw" in pose_channels:
            yaw = pose.get("head_yaw", 0.0)
            lines.append(f"_p_{_esc(char.id)}Head.rotation_euler.z = {yaw:.6f}")
            lines.append(
                f"_p_{_esc(char.id)}Head.keyframe_insert("
                f"data_path='rotation_euler', index=2, frame={blender_frame})"
            )

    # Only this pass's bob/location and joint/X-rotation samples become LINEAR.
    # Do not touch authored wrapper curves, other channels, or other objects.
    pose_targets = [f"(bob_{_esc(char.id)}, 'location', (0, 1, 2))"]
    pose_targets.extend(
        f"(_p_{_esc(char.id)}{limb}, 'rotation_euler', (0,))"
        for limb in [name for name, _ in _LIMB_POSE_FIELDS] + ["Head"]
    )
    pose_targets.extend(
        f"(_p_{_esc(char.id)}{limb}, 'rotation_euler', (1,))"
        for limb, _ in side_channels
    )
    if "head_yaw" in pose_channels:
        pose_targets.append(f"(_p_{_esc(char.id)}Head, 'rotation_euler', (2,))")
    lines.extend([
        "# Linear sampled pose; authored wrapper interpolation stays untouched.",
        "for _pose_obj, _pose_path, _pose_indices in (",
        *[f"    {target}," for target in pose_targets],
        "):",
        "    if _pose_obj.animation_data and _pose_obj.animation_data.action:",
        "        _pose_action = _pose_obj.animation_data.action",
        "        _pose_curves = getattr(_pose_action, 'fcurves', None)",
        "        if _pose_curves is None:",
        "            _pose_curves = []",
        "            for _pose_layer in _pose_action.layers:",
        "                for _pose_strip in _pose_layer.strips:",
        "                    _pose_bag = _pose_strip.channelbag(_pose_obj.animation_data.action_slot)",
        "                    if _pose_bag is not None:",
        "                        _pose_curves.extend(_pose_bag.fcurves)",
        "        for _pose_curve in _pose_curves:",
        "            if (_pose_curve.data_path == _pose_path",
        "                    and _pose_curve.array_index in _pose_indices):",
        "                for _pose_key in _pose_curve.keyframe_points:",
        f"                    if 1 <= _pose_key.co[0] <= {total_frames + 1}:",
        "                        _pose_key.interpolation = 'LINEAR'",
    ])
    lines.append("")
    return lines


def _actor_motion_code(char, frame_rate: float, total_frames: int) -> list[str]:
    """Keyframe a non-human actor from the object-motion library.

    The converter had no equivalent of the preview's ``objectMotion.ts``, so a
    ``door_swing_open`` or a ``drive`` sat at its rest pose here -- the same silent
    gap the character pose had.

    The rotation lands on the actor's PIVOT empty rather than the wrapper, for the
    same reason the prop rotation does: a door that rotates about its own centre is a
    door spinning in place, not a hinge. The pivot comes from the same
    ``KIND_ROTATION_PIVOT`` table the props and the preview read.

    Unlike the human pose this is wall-clock phased, because a door opens once across
    its shot and a wheel turns whether or not it moves. Continuous motions are keyed
    every frame; the one-shot door is keyed at the ends plus a few samples, because
    its curve is a clamp, not a cycle.
    """
    if total_frames <= 0:
        return []

    actions = [kf.action for kf in char.keyframes]
    frames = [kf.frame for kf in char.keyframes]
    # The action in force when the actor's animation begins, which is what decides
    # its phase basis. A later action change re-bases it, so a door that opens then
    # holds does not restart.
    lines = [
        "# === ACTOR MOTION: " + _esc(char.id) + " (" + _esc(char.type) + ") ===",
        "# Actions: " + ", ".join(sorted({str(a) for a in actions})) +
        ". Phased by wall clock: a door opens once, a wheel turns regardless of travel.",
    ]
    needs_pivot = rotation_pivot.needs_pivot_empty(char.type)
    if needs_pivot:
        lines.append(
            f"# Rotation pivot for {_esc(char.id)} ({char.type}): about this point, "
            "not the actor's centre."
        )
    lines.append(f"_rot_{_esc(char.id)} = bpy.data.objects["
                 f"{char.id + '_pivot'!r} if {needs_pivot} else {char.id!r}]")
    lines.append("")

    for frame in range(total_frames + 1):
        action = character_pose.action_at_frame(actions, frames, frame)
        phase = object_motion.cycle_phase_for_frame(action, frame, frame_rate)
        motion = object_motion.object_motion_at(action, phase)
        rotation = motion.get("rotation")
        translation = motion.get("translation")
        if not rotation and not translation:
            continue
        blender_frame = frame + 1
        lines.append(f"# frame {frame} action={action} phase={phase:.4f}")
        if rotation:
            rx, ry, rz = rotation
            # Blender is Z-up and so is SceneScript, but the PREVIEW's three.js is
            # Y-up, so the axis indices swap: the preview's x is Blender's y.
            lines.append(
                f"_rot_{_esc(char.id)}.rotation_euler = "
                f"(math.radians({ry:.6f}), math.radians({rx:.6f}), math.radians({rz:.6f}))"
            )
            lines.append(
                f"_rot_{_esc(char.id)}.keyframe_insert(data_path='rotation_euler', frame={blender_frame})"
            )
        if translation:
            tx, ty, tz = translation
            base = char.keyframes[0].position
            lines.append(
                f"char_obj.location = "
                f"({base[0] + ty:.6f}, {base[1] + tx:.6f}, {base[2] + tz:.6f})"
            )
            lines.append(
                f"char_obj.keyframe_insert(data_path='location', frame={blender_frame})"
            )
    lines.append("")
    return lines


def scene_script_to_blender(
    scene_script: SceneScriptRoot,
    output_dir: str,
    include_control_passes: bool = False,
    keyframes_only: bool = False,
) -> str:
    """Convert a SceneScriptRoot into a complete Blender Python script.

    Args:
        scene_script: Validated SceneScript root.
        output_dir: Absolute directory path for rendered PNG frames.
        include_control_passes: When True, render geometric control passes
            (depth / normal / motion vectors) alongside the color pass,
            written to sibling subdirectories ``control_depth``,
            ``control_normal``, ``control_flow`` (ADR 0005 §4).
        keyframes_only: When True, render only each shot's keyframe frames
            (5 per shot) instead of the whole animation.  The scene graph is
            built identically, so the frames are the same images the full pass
            would produce at those instants -- just ~1/10th of them.

    Returns:
        Complete Blender Python script as a string.
    """
    s = scene_script
    total_frames = s.total_frames
    frame_rate = s.scene.frame_rate

    lines: list[str] = []
    lines.append("import bpy")
    lines.append("import math")
    lines.append("import os")
    lines.append("")
    lines.append("# === CLEAN SCENE ===")
    lines.append("bpy.ops.wm.read_factory_settings(use_empty=True)")
    lines.append("scene = bpy.context.scene")
    lines.append("scene.frame_start = 1")
    lines.append(f"scene.frame_end = {total_frames}")
    lines.append(f"scene.render.fps = {s.scene.frame_rate}")
    lines.append("")

    # World / lighting
    lines.append("# === WORLD / LIGHTING ===")
    lines.append("world = bpy.data.worlds.new('World')")
    lines.append("scene.world = world")
    if s.scene.lighting in ("warm", "soft"):
        lines.append("world.color = (0.15, 0.12, 0.10)")
    elif s.scene.lighting == "cool":
        lines.append("world.color = (0.10, 0.12, 0.15)")
    else:
        lines.append("world.color = (0.12, 0.12, 0.12)")
    lines.append("")
    lines.append("# Key light")
    lines.append("bpy.ops.object.light_add(type='AREA', location=(5, -5, 8))")
    lines.append("key_light = bpy.context.object")
    lines.append("key_light.data.energy = 1000")
    lines.append("key_light.data.size = 5")
    lines.append("")
    lines.append("# Fill light")
    lines.append("bpy.ops.object.light_add(type='AREA', location=(-5, -3, 5))")
    lines.append("fill_light = bpy.context.object")
    lines.append("fill_light.data.energy = 300")
    lines.append("fill_light.data.size = 3")
    lines.append("")

    # Environment objects
    if s.environment:
        lines.append("# === ENVIRONMENT OBJECTS ===")
        for env in s.environment:
            lines.append(_build_asset(
                obj_id=env.id,
                obj_type=env.type,
                position=env.position,
                rotation_y=env.rotation_y,
                scale=env.scale,
            ))
            # A structure that moves: same contract as props.
            if env.keyframes:
                lines.append(f"# Environment motion keyframes: {env.id}")
                lines.append(_pivot_parent_code(env.id, env.type, env.position, env.scale))
                lines.append(f'env_obj = bpy.data.objects["{_esc(env.id)}"]')
                # Rotation lands on the pivot empty when the kind declares one, so
                # the turn is about the object's own extent rather than its base.
                env_rot_target = (f"pivot_{_esc(env.id)}"
                                  if needs_pivot_empty(env.type) else "env_obj")
                for kf in env.keyframes:
                    rx, ry, rz = kf.rotation
                    lines.append(f"# frame {kf.frame}")
                    offset = rotation_pivot_for(env.type) if needs_pivot_empty(env.type) else (0, 0, 0)
                    live_position = [kf.position[i] + offset[i] * env.scale for i in range(3)]
                    lines.append(f"{env_rot_target}.location = {_vec(live_position)}")
                    lines.append(f"{env_rot_target}.rotation_mode = 'ZYX'")
                    lines.append(f"{env_rot_target}.rotation_euler = (-math.radians({rx:.4f}), -math.radians({rz:.4f}), -math.radians({ry:.4f}))")
                    lines.append(f"{env_rot_target}.keyframe_insert(data_path='location', frame={kf.frame + 1})")
                    lines.append(f"{env_rot_target}.keyframe_insert(data_path='rotation_euler', frame={kf.frame + 1})")
                    if kf.scale is not None and abs(kf.scale - env.scale) > 1e-9:
                        lines.append(f"env_obj.scale = ({kf.scale!r}, {kf.scale!r}, {kf.scale!r})")
                        lines.append(f"env_obj.keyframe_insert(data_path='scale', frame={kf.frame + 1})")
        lines.append("")

    # Props
    if s.props:
        lines.append("# === PROPS ===")
        for prop in s.props:
            lines.append(_build_asset(
                obj_id=prop.id,
                obj_type=prop.type,
                position=prop.position,
                rotation_y=prop.rotation_y,
                scale=prop.scale,
            ))
            # Held items (V0.2 §5): ride the holder's hand at the holder's own
            # keyframes — same frames, same interpolation basis as the
            # character, so preview ≡ render at every authored pose. A static
            # prop keeps its authored position untouched.
            if prop.held_by:
                holder = next((c for c in s.characters if c.id == prop.held_by), None)
                if holder is not None:
                    lines.append(f"# Held prop keyframes: {prop.id} (held by {holder.id})")
                    lines.append(f'prop_obj = bpy.data.objects["{_esc(prop.id)}"]')
                    for frame, hand_position in held_keyframe_positions(prop, holder):
                        lines.append(f"# frame {frame}")
                        lines.append(f"prop_obj.location = {_vec(hand_position)}")
                        lines.append(f"prop_obj.keyframe_insert(data_path='location', frame={frame + 1})")
            elif prop.keyframes:
                # Own motion: the prop moves itself. The held branch above is
                # mutually exclusive (the schema rejects a prop that is both),
                # so exactly one of these two ever emits keyframes — two
                # writers on one object is the ambiguity that validation
                # prevents.
                lines.append(f"# Prop motion keyframes: {prop.id}")
                lines.append(_pivot_parent_code(prop.id, prop.type, prop.position, prop.scale))
                lines.append(f'prop_obj = bpy.data.objects["{_esc(prop.id)}"]')
                # Rotation lands on the pivot empty when the kind declares one, so
                # the turn is about the object's own extent rather than its base.
                prop_rot_target = (f"pivot_{_esc(prop.id)}"
                                   if needs_pivot_empty(prop.type) else "prop_obj")
                for kf in prop.keyframes:
                    rx, ry, rz = kf.rotation
                    lines.append(f"# frame {kf.frame}")
                    offset = rotation_pivot_for(prop.type) if needs_pivot_empty(prop.type) else (0, 0, 0)
                    live_position = [kf.position[i] + offset[i] * prop.scale for i in range(3)]
                    lines.append(f"{prop_rot_target}.location = {_vec(live_position)}")
                    lines.append(f"{prop_rot_target}.rotation_mode = 'ZYX'")
                    lines.append(f"{prop_rot_target}.rotation_euler = (-math.radians({rx:.4f}), -math.radians({rz:.4f}), -math.radians({ry:.4f}))")
                    lines.append(f"{prop_rot_target}.keyframe_insert(data_path='location', frame={kf.frame + 1})")
                    lines.append(f"{prop_rot_target}.keyframe_insert(data_path='rotation_euler', frame={kf.frame + 1})")
                    if kf.scale is not None and abs(kf.scale - prop.scale) > 1e-9:
                        lines.append(f"prop_obj.scale = ({kf.scale!r}, {kf.scale!r}, {kf.scale!r})")
                        lines.append(f"prop_obj.keyframe_insert(data_path='scale', frame={kf.frame + 1})")
        lines.append("")

    # Characters
    if s.characters:
        lines.append("# === CHARACTERS ===")
        for char in s.characters:
            # A non-human actor is the SCHEMA'S type, not always a person. This used
            # to hardcode `lowpoly_human`, so a `door`-typed actor built a seven-box
            # figure with a head while the preview drew an actual door -- two
            # renderers, two different objects, and the disagreement only visible by
            # putting the frames side by side.
            is_human = char.type == "lowpoly_human"
            lines.append(_build_asset(
                obj_id=char.id,
                obj_type=char.type,
                position=char.keyframes[0].position,
                rotation_y=char.keyframes[0].rotation_y,
                scale=char.appearance.scale,
                color=char.appearance.color,
                height=char.appearance.height,
                show_pose_marker=any(getattr(kf, "pose", None) is not None for kf in char.keyframes),
            ))
            # Character keyframes
            lines.append(f"# Character keyframes: {char.id}")
            lines.append(f'char_obj = bpy.data.objects["{_esc(char.id)}"]')
            if is_human:
                lines.extend(
                    _character_pose_code(char, s, total_frames=_last_frame(s))
                )
            else:
                # A non-human actor needs the same pivot empty a prop gets, so its
                # rotation lands at the hinge instead of the actor's centre.
                lines.append(
                    _pivot_parent_code(
                        char.id, char.type, char.keyframes[0].position, char.appearance.scale
                    )
                )
                lines.extend(
                    _actor_motion_code(
                        char, frame_rate=s.scene.frame_rate, total_frames=_last_frame(s)
                    )
                )
            for kf in char.keyframes:
                lines.append(f"# frame {kf.frame}")
                lines.append(f"char_obj.location = {_vec(kf.position)}")
                lines.append(f"char_obj.rotation_euler.z = -math.radians({kf.rotation_y:.2f})")
                lines.append(f"char_obj.keyframe_insert(data_path='location', frame={kf.frame + 1})")
                lines.append(f"char_obj.keyframe_insert(data_path='rotation_euler', frame={kf.frame + 1})")
            lines.append("")

    # Cameras
    camera_names: list[str] = []
    if s.cameras:
        lines.append("# === CAMERAS ===")
        for cam in s.cameras:
            cam_name = cam.id
            target_name = f"{cam.id}_Focus"
            lines.append(f"bpy.ops.object.camera_add(location={_vec(cam.keyframes[0].position)})")
            lines.append("cam = bpy.context.object")
            lines.append(f"cam.name = '{_esc(cam_name)}'")
            lines.append(f"bpy.ops.object.empty_add(type='PLAIN_AXES', location={_vec(cam.keyframes[0].look_at)})")
            lines.append("target = bpy.context.object")
            lines.append(f"target.name = '{_esc(target_name)}'")
            lines.append("constraint = cam.constraints.new(type='TRACK_TO')")
            lines.append("constraint.target = target")
            lines.append("constraint.track_axis = 'TRACK_NEGATIVE_Z'")
            lines.append("constraint.up_axis = 'UP_Y'")
            # Camera keyframes
            for kf in cam.keyframes:
                lines.append(f"cam.location = {_vec(kf.position)}")
                lines.append(f"cam.keyframe_insert(data_path='location', frame={kf.frame + 1})")
                lines.append(f"target.location = {_vec(kf.look_at)}")
                lines.append(f"target.keyframe_insert(data_path='location', frame={kf.frame + 1})")
            camera_names.append(cam_name)
            lines.append("")

    # Shot markers / camera switching
    if s.shots and camera_names:
        lines.append("# === SHOT MARKERS (camera switching) ===")
        for shot in s.shots:
            frame = shot.start_frame + 1
            lines.append(f"marker = scene.timeline_markers.new('{_esc(shot.id)}', frame={frame})")
            lines.append(f"marker.camera = bpy.data.objects.get('{_esc(shot.camera)}')")
        # Set initial camera
        lines.append(f"scene.camera = bpy.data.objects.get('{_esc(s.shots[0].camera)}')")
        lines.append("")

    # Render settings
    lines.append("# === RENDER SETTINGS ===")
    # Eevee is a real-time renderer and renders low-poly flat-shaded previs
    # scenes in a few seconds; Cycles (GPU optional, CPU-bound by default)
    # made 240-frame jobs exceed the sync timeout on plain hardware.  The
    # look is equivalent for low-fidelity geometry; Cycles is still used
    # for the depth control pass when requested.
    lines.append("scene.render.engine = 'BLENDER_EEVEE'")
    lines.append("scene.render.resolution_x = 960")
    lines.append("scene.render.resolution_y = 540")
    lines.append("scene.render.image_settings.file_format = 'PNG'")
    lines.append(f"scene.render.filepath = r'{_esc(output_dir)}/frame_'")
    lines.append("")
    if keyframes_only:
        lines.extend(_keyframe_render_lines(output_dir, keyframe_render_frames(s)))
    else:
        lines.append("# === RENDER ANIMATION ===")
        lines.append("bpy.ops.render.render(animation=True)")
    lines.append("print('RENDER DONE')")

    if include_control_passes:
        # Depth sampling happens after the color-pass animation render,
        # once the scene graph is fully evaluated.
        lines.extend(_control_pass_lines(output_dir, total_frames, frame_rate))
    lines.append("")

    return "\n".join(lines)


def _keyframe_render_lines(output_dir: str, frames: list[int]) -> list[str]:
    """Blender lines rendering only the keyframe frames, one still at a time.

    ``bpy.ops.render.render(write_still=True)`` writes ``scene.render.filepath``
    verbatim, so the path is set per frame instead of relying on the animation
    pass's frame-number substitution.  The naming is chosen to be the same
    ``frame_<blender frame>.png`` the animation pass emits for the same instant
    (SceneScript frames are 0-based, Blender's are 1-based), so
    ``extract_keyframes`` reads a draft exactly as it reads a full render.
    """

    if not frames:
        # No shots means no keyframes; without a render the job would report
        # "0 frames" and the caller would learn nothing about why.  Say so
        # instead of emitting a loop that never executes.
        return ["print('RENDER DONE: no shots, nothing to render')"]
    quoted = ", ".join(str(frame) for frame in frames)
    return [
        "# === RENDER KEYFRAMES ONLY (draft previs) ===",
        "# 5 frames per shot instead of the whole animation: the keyframes are",
        "# what a video model binds as reference, so rendering the full sequence",
        "# buys nothing downstream and costs ~10x the wall-clock (ADR 0005 §4a).",
        f"_keyframe_frames = ({quoted},)" if len(frames) == 1 else f"_keyframe_frames = [{quoted}]",
        "for _f in _keyframe_frames:",
        "    scene.frame_set(_f + 1)",
        f"    scene.render.filepath = r'{_esc(output_dir)}/frame_' + str(_f + 1) + '.png'",
        "    bpy.ops.render.render(write_still=True)",
    ]


def _control_pass_lines(output_dir: str, total_frames: int, frame_rate: int) -> list[str]:
    """Blender script lines producing a depth control pass (Blender 5.x).

    Blender 5.x removed the compositor's Z/Normal/Vector pass sockets and
    the ``use_pass_*`` / ``use_motion_vectors`` settings (verified on
    Blender 5.2.1 LTS): the layer source node (``CompositorNodeRLayers``)
    exposes Image/Alpha only. The one reliable geometric signal available
    is **ray depth**, sampled per keyframe via the Cycles ray-data API
    (``scene.ray_data``). Normal and flow passes therefore degrade to
    "unavailable" in Blender 5.x — recorded honestly per ADR 0005 §4/§4a
    (queryable degradation, never silent); when a Blender version restores
    the pass sockets, this function regains them without changing the
    collection contract.

    Depth frames are written as PNGs into ``{output_dir}/control_depth``
    named ``depth_<N>.png`` (N = SceneScript frame number, 0-based),
    sampled at each shot's 5 keyframe frames.
    """
    depth_dir = f"{output_dir}/control_depth"
    normal_dir = f"{output_dir}/control_normal"
    flow_dir = f"{output_dir}/control_flow"
    return [
        "# === GEOMETRIC CONTROL PASSES (ADR 0005 §4, Blender 5.x depth-only) ===",
        f"os.makedirs(r'{_esc(depth_dir)}', exist_ok=True)",
        f"os.makedirs(r'{_esc(normal_dir)}', exist_ok=True)",
        f"os.makedirs(r'{_esc(flow_dir)}', exist_ok=True)",
        "import numpy as np",
        "def _shot_keyframe_frames(shots_by_range):",
        "    frames = []",
        "    for start, end in shots_by_range:",
        "        dur = end - start - 1",
        "        for pct in (0.0, 0.25, 0.5, 0.75, 1.0):",
        "            f = int(round(start + dur * pct))",
        "            f = max(start, min(end - 1, f))",
        "            if f not in frames:",
        "                frames.append(f)",
        "    return frames",
        "shots_by_range = [ (m.frame - 1, None) for m in scene.timeline_markers ]",
        "# Resolve shot end frames: last marker's end = frame_end; pairs otherwise.",
        "marks = sorted([ (m.frame - 1, m.name) for m in scene.timeline_markers ])",
        "shot_ranges = []",
        "for i, (start, _name) in enumerate(marks):",
        "    end = marks[i+1][0] if i+1 < len(marks) else scene.frame_end",
        "    shot_ranges.append((start, end))",
        "depth_frames = _shot_keyframe_frames(shot_ranges) or [0]",
        "for _f in depth_frames:",
        "    scene.frame_set(_f + 1)",
        "    deps = bpy.context.evaluated_depsgraph_get()",
        "    cam = scene.camera or next((c for c in bpy.data.objects if c.type == 'CAMERA'), None)",
        "    if cam is not None:",
        "        cam_eval = cam.evaluated_get(deps)",
        "        cam_pos = list(cam_eval.matrix_world.translation)",
        "        # Sample the ray cast at a coarse grid of image-space points.",
        "        n = 8",
        "        depth = np.zeros(n * n, dtype=np.float32)",
        "        # Blender 5.x removed ``Object.rotation_matrix``; the world",
        "        # matrix is the only orientation available on an evaluated object.",
        "        m = np.asarray(cam_eval.matrix_world.to_3x3(), dtype=np.float64).T",
        "        fwd = (m @ np.array([0, 0, -1.0])).tolist()",
        "        right = (m @ np.array([1.0, 0, 0])).tolist()",
        "        up = (m @ np.array([0, 1.0, 0])).tolist()",
        "        for i in range(n):",
        "            for j in range(n):",
        "                u = (i + 0.5) / n",
        "                v = (j + 0.5) / n",
        "                d = np.array(fwd) + (u - 0.5) * 2.0 * np.array(right) + (v - 0.5) * 2.0 * np.array(up)",
        "                d = d / np.linalg.norm(d)",
        "                hit, loc, _nrm, _idx, _obj, _mat = scene.ray_cast(deps, np.asarray(cam_pos, dtype=np.float64), np.asarray(d, dtype=np.float64), distance=1e6)",
        "                if hit:",
        "                    depth[j * n + i] = float(np.linalg.norm(np.array(loc) - np.array(cam_pos)))",
        "                else:",
        "                    depth[j * n + i] = 0.0",
        "        # Image.pixels is always RGBA (n*n*4 floats in 0..1), even for",
        "        # an image created with alpha=False.",
        "        max_d = float(depth.max()) if depth.max() > 0 else 1.0",
        "        norm = (depth / max_d).astype(np.float32).reshape(n, n, 1)",
        "        img = bpy.data.images.new('depth_%d' % _f, n, n, alpha=False)",
        "        img.pixels = np.repeat(norm, 4, axis=2).ravel().tolist()",
        "        img.save(filepath=r'" + depth_dir + "/depth_' + str(_f) + '.png')",
        "        bpy.data.images.remove(img)",
        "print('CONTROL PASS DEPTH: available (Cycles ray_cast grid, keyframe-sampled)')",
        "print('CONTROL PASS NORMAL: unavailable in Blender 5.x (compositor Z/Normal sockets removed)')",
        "print('CONTROL PASS FLOW: unavailable in Blender 5.x (motion-vector pass removed)')",
        "",
    ]
