"""SceneScript: structured 3D previsualization scene description.

SceneScript is the canonical intermediate format between the LLM parser,
the frontend Three.js preview, and the backend Blender renderer. It is
defined as Pydantic models so that all consumers share a single validated
source of truth.

See: docs/adr/0005-3d-low-fidelity-previs.md
     docs/3d-previs/prompt-engineering-guide.md
"""

from __future__ import annotations

import math
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.scene3d import asset_dimensions

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

ShotType = Literal["wide", "medium", "closeup", "over_shoulder", "pov"]
CharacterAction = Literal["stand", "talk", "walk", "sit", "gesture"]
# Non-human actors. A door that swings open, a wheel that turns and a vehicle
# that crosses the frame are all "characters" in the only sense that matters to
# a previs: the scene acts through them. They are authored in `characters[]`
# rather than `props[]` because a prop is furniture (it has a position and
# nothing else happens) and these have a motion, which is what
# `keyframes[].action` drives. The human type stays first and stays the default.
NonHumanActorAction = Literal["door_swing_open", "spin", "drive", "flyover"]
SpeechMode = Literal["bound", "free"]
EnvironmentKind = Literal["indoor", "outdoor", "mixed"]
LightingPreset = Literal["warm", "cool", "neutral", "dramatic", "soft", "hard"]
# Open on purpose. The renderers build every prop/environment kind from one
# table already, so the set of buildable actors is exactly the union of those
# two enums — enumerating it here would go stale the moment a kind is added,
# and an unbuildable type already fails loudly as a magenta box reported by
# `unimplementedKinds`. The closed `Literal["lowpoly_human"]` this replaces is
# why "put the door in characters and open it" was not expressible at all.
CharacterType = Literal["lowpoly_human", "door", "crate", "box", "pillar"]

PropType = Literal[
    "round_table",
    "rect_table",
    "chair",
    "stool",
    "lantern",
    "box",
    "crate",
    "vase",
    "weapon",
    "scroll",
    "book",
    "cup",
    "chip",
]

# Which hand carries a held prop (Continuity State's prop dimension, V0.2 §5:
# "Scene 01 里女孩右手拿伞，Scene 02 变成左手" is the failure this declares).
HeldSide = Literal["left", "right"]

EnvironmentType = Literal[
    "wall",
    "pillar",
    "floor",
    "gable_roof",
    "flat_roof",
    "door",
    "window",
    "stairs",
    "platform",
    "tree",
    "rock",
    "crater",
    "fence",
    "ground",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COORD_MIN = -100.0
_COORD_MAX = 100.0
_ROTATION_MAX = 360.0
_RADIAN_THRESHOLD = 2.0 * math.pi  # ~6.28; values below this are likely radians

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_position(value: list[float], field_name: str) -> list[float]:
    if len(value) != 3:
        raise ValueError(f"{field_name} must have exactly 3 elements [x, y, z], got {len(value)}")
    for i, v in enumerate(value):
        if not (_COORD_MIN <= v <= _COORD_MAX):
            raise ValueError(
                f"{field_name}[{i}]={v} is outside realistic range [{_COORD_MIN}, {_COORD_MAX}]; "
                "1 unit = 1 meter"
            )
    return value


def _validate_rotation_y(value: float, field_name: str) -> float:
    if abs(value) > _ROTATION_MAX:
        raise ValueError(f"{field_name}={value} exceeds ±{_ROTATION_MAX} degrees")
    if 0 < abs(value) <= _RADIAN_THRESHOLD:
        raise ValueError(
            f"{field_name}={value} appears to be in radians; use degrees (e.g. 180, not 3.14)"
        )
    return value


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


MAX_APPEARANCE_PALETTE_COLORS = 4

#: Longest declared transition reading id (§13 第 5 问).
MAX_TRANSITION_INTENT_LENGTH = 64


def _is_hex_color(value: str) -> bool:
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


class CharacterAppearance(BaseModel):
    """Visual appearance of a low-poly character."""

    model_config = ConfigDict(extra="forbid")

    color: str = Field(default="#8B4513", description="Hex color for the character body")
    height: float = Field(default=1.7, ge=0.5, le=3.0, description="Height in meters")
    scale: float = Field(default=1.0, gt=0, le=5.0, description="Uniform scale multiplier")
    #: The declared wardrobe palette (V0.2 §5 服装). ``color`` is what the
    #: proxy body renders; ``palette`` is what the character's LOOK is
    #: declared to be, which is what the next scene must inherit. Within one
    #: script a character has one appearance so it cannot self-contradict;
    #: ACROSS the workflow's scene-3d nodes it can, and
    #: ``wardrobe_drift.check_cross_node_character_drift`` refuses to guess
    #: which is right. Optional: an author who never declares one keeps the
    #: old behaviour exactly.
    palette: tuple[str, ...] | None = Field(
        default=None,
        max_length=MAX_APPEARANCE_PALETTE_COLORS,
        description=(
            "Declared wardrobe palette (1-4 hex colors, e.g. '#2C3E50'). "
            "Cross-node consistency for the same bound asset is checked."
        ),
    )

    @field_validator("color", mode="before")
    @classmethod
    def _coerce_color(cls, value: object) -> str:
        # LLMs frequently emit a free-text description here; keep the
        # schema strict (color is rendered, not displayed) by defaulting
        # any non-hex value back to the default body color.
        if isinstance(value, str) and value.startswith("#") and len(value) in (4, 7):
            return value
        return "#8B4513"

    @field_validator("palette", mode="before")
    @classmethod
    def _coerce_palette(cls, value: object) -> object:
        # Same tolerance as ``color``: a free-text description in the palette
        # slot is dropped rather than failing the whole scene, but an
        # unparsable hex is NOT silently kept as a colour the drift gate
        # would later compare against.
        if not isinstance(value, (list, tuple)) or not value:
            return None
        kept: list[str] = []
        for entry in value:
            if (
                isinstance(entry, str)
                and entry.startswith("#")
                and len(entry) in (4, 7)
                and _is_hex_color(entry)
            ):
                kept.append(entry.upper())
        return tuple(kept[:MAX_APPEARANCE_PALETTE_COLORS]) if kept else None


class CharacterPose(BaseModel):
    """Optional authored joint angles, in radians, over the action pose.

    Each non-null field is its own sparse track. Before its first authored
    frame the action remains in charge; between authored values it interpolates
    linearly, then holds its last value. Authors explicitly write zero to release
    a raised limb. This is direct joint authoring, not an IK/contact solver.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    arm_l: float | None = Field(default=None, ge=-math.pi, le=math.pi)
    arm_r: float | None = Field(default=None, ge=-math.pi, le=math.pi)
    arm_l_side: float | None = Field(default=None, ge=-math.pi / 2, le=math.pi / 2)
    arm_r_side: float | None = Field(default=None, ge=-math.pi / 2, le=math.pi / 2)
    head: float | None = Field(default=None, ge=-math.pi / 2, le=math.pi / 2)
    head_yaw: float | None = Field(default=None, ge=-math.pi, le=math.pi)
    leg_l: float | None = Field(default=None, ge=-math.pi / 2, le=math.pi / 2)
    leg_r: float | None = Field(default=None, ge=-math.pi / 2, le=math.pi / 2)
    knee_l: float | None = Field(default=None, ge=0, le=2.4)
    knee_r: float | None = Field(default=None, ge=0, le=2.4)
    bob: float | None = Field(
        default=None, ge=-0.15, le=0.15,
        description="Vertical body offset as a fraction of character height",
    )


class CharacterKeyframe(BaseModel):
    """A single character keyframe: position, facing direction, and action."""

    model_config = ConfigDict(extra="forbid")

    frame: int = Field(ge=0, description="Frame number (0-based)")
    position: list[float] = Field(description="[x, y, z] position in meters")
    rotation_y: float = Field(description="Y-axis rotation in degrees (0=facing +Y)")
    # Human actions first, then the non-human ones. A keyframe on a character
    # whose `type` is not lowpoly_human must use a non-human action: a door
    # with action "walk" is authoring noise, and the renderers would each have
    # to decide what it means. `_validate_actor_actions` rejects it.
    action: CharacterAction | NonHumanActorAction = Field(
        default="stand", description="Character action at this keyframe"
    )
    pose: CharacterPose | None = Field(
        default=None,
        description="Optional sparse authored joint angles in radians; overrides action per field",
    )

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation_y")
    @classmethod
    def _check_rotation(cls, v: float) -> float:
        return _validate_rotation_y(v, "rotation_y")


class SceneCharacter(BaseModel):
    """A character in the scene with appearance and animation keyframes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, description="Unique character identifier")
    type: CharacterType = Field(default="lowpoly_human", description="Character asset type")
    character_asset_id: str | None = Field(default=None, max_length=160, description="Reference to bound character asset (P0, 2026-09-15)")
    appearance: CharacterAppearance = Field(default_factory=CharacterAppearance)
    keyframes: list[CharacterKeyframe] = Field(
        min_length=1, description="At least one keyframe (static characters need frame 0)"
    )

    @field_validator("appearance", mode="before")
    @classmethod
    def _coerce_appearance(cls, value: object) -> object:
        # LLMs frequently emit a free-text description (or a flat "style"
        # string) where the schema expects a color/height/scale object; the
        # renderer only consumes color/height/scale, so any other shape is
        # coerced to the default appearance instead of rejecting the whole
        # scene.  The user-facing description already lives in
        # scene.name / shot.description.
        if isinstance(value, dict):
            return value
        # Accept a pre-validated CharacterAppearance instance (e.g. when the
        # scene is constructed programmatically in Python) and serialise it.
        if isinstance(value, BaseModel):
            return value.model_dump()
        if isinstance(value, str) and not value.strip():
            return {}
        return {}


class PropKeyframe(BaseModel):
    """A single prop keyframe: where the prop is, at this frame.

    Separate from ``CharacterKeyframe`` even though the fields look alike, for
    one reason: a character's keyframe carries an ``action`` (a pose name) and
    a prop's carries a motion delta. Sharing the model would mean either props
    gaining a meaningless ``action`` or characters losing theirs.
    """

    model_config = ConfigDict(extra="forbid")

    frame: int = Field(ge=0, description="Frame number (0-based)")
    position: list[float] = Field(description="[x, y, z] position in meters")
    # Preview-axis [pitch, yaw, roll], matching the Three geometry contract.
    # SceneScript positions are Z-up, so Blender maps these axes/signs once;
    # treating the middle entry as Blender Y would pitch an authored yaw.
    rotation: list[float] = Field(
        default=[0.0, 0.0, 0.0],
        description="Rotation in degrees [pitch, yaw, roll] using the preview axes",
    )
    scale: float | None = Field(default=None, gt=0, le=50.0, description="Uniform scale at this frame")

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation")
    @classmethod
    def _check_rotation(cls, v: list[float]) -> list[float]:
        if len(v) != 3:
            raise ValueError("rotation must be [x, y, z] degrees")
        return [float(value) for value in v]

    @field_validator("scale")
    @classmethod
    def _check_scale(cls, v: float | None) -> float | None:
        if v is None:
            return None
        if not (0 < v <= 50):
            raise ValueError(
                f"scale={v} is outside the realistic range (0, 50]; a keyframe "
                "scale is a multiplier, so 1 means unchanged"
            )
        return v


class SceneProp(BaseModel):
    """A movable/interactive prop in the scene."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: PropType
    prop_asset_id: str | None = Field(default=None, max_length=160, description="Reference to bound prop asset (P0, 2026-09-15)")
    position: list[float] = Field(description="[x, y, z] in meters")
    scale: float = Field(default=1.0, gt=0, le=10.0)
    rotation_y: float = Field(default=0.0, description="Y-axis rotation in degrees")
    # Motion. Empty means the prop is furniture (the pre-existing behaviour,
    # byte for byte); any keyframe here overrides `position`/`rotation_y` while
    # that frame is current, which is what makes a wheel turn and a door swing.
    keyframes: list[PropKeyframe] = Field(
        default_factory=list,
        description="Empty = static. Non-empty = the prop moves along these.",
    )
    # Held items (V0.2 §5 Continuity State): a prop declared held follows its
    # holder's hand across every shot, so the item cannot vanish or switch
    # hands at a cut. The authored position becomes the prop's rest position
    # (used when unheld); renderers derive the live position from the holder.
    held_by: str | None = Field(
        default=None,
        max_length=64,
        description="Character id carrying this prop (held items follow the holder)",
    )
    held_side: HeldSide | None = Field(
        default=None,
        description="Which hand carries it (defaults to the right when held)",
    )

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation_y")
    @classmethod
    def _check_rotation(cls, v: float) -> float:
        return _validate_rotation_y(v, "rotation_y")

    @model_validator(mode="after")
    def _check_rendered_size(self) -> "SceneProp":
        # `le=10.0` above is a backstop for a fat-fingered number, not a plausibility
        # bound: a pillar at 10 is a 42 m column beside a 1.85 m person and the
        # global cap says nothing is wrong with it. The real limit is per kind and
        # derived from what the geometry actually measures (see
        # asset_dimensions.max_scale), and the message names the metres so whoever
        # wrote the scale can write a different one.
        explanation = asset_dimensions.scale_explanation(self.type, self.scale)
        if explanation:
            raise ValueError(explanation)
        return self


class SceneEnvironmentObject(BaseModel):
    """A fixed environmental structure (walls, pillars, floors, roofs)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: EnvironmentType
    scene_asset_id: str | None = Field(default=None, max_length=160, description="Reference to bound scene asset (P0, 2026-09-15)")
    position: list[float] = Field(description="[x, y, z] in meters")
    scale: float = Field(default=1.0, gt=0, le=50.0)
    rotation_y: float = Field(default=0.0, description="Y-axis rotation in degrees")
    # Same contract as SceneProp.keyframes: empty = still, non-empty = it moves.
    keyframes: list[PropKeyframe] = Field(
        default_factory=list,
        description="Empty = static. Non-empty = the structure moves along these.",
    )

    @field_validator("position")
    @classmethod
    def _check_position(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position")

    @field_validator("rotation_y")
    @classmethod
    def _check_rotation(cls, v: float) -> float:
        return _validate_rotation_y(v, "rotation_y")

    @model_validator(mode="after")
    def _check_rendered_size(self) -> "SceneEnvironmentObject":
        # Same contract as SceneProp, and this is where it bites hardest: `le=50.0`
        # admits a 250 m platform and a 210 m pillar, which is how the jinghai scene
        # came to have characters authored at z = 0 standing underneath a 25 m slab.
        # The per-kind bound is derived from the rendered size; `ground` and `floor`
        # are exempt because a site plate is the scene rather than an object in it.
        explanation = asset_dimensions.scale_explanation(self.type, self.scale)
        if explanation:
            raise ValueError(explanation)
        return self


class CameraKeyframe(BaseModel):
    """A single camera keyframe: position and look-at target."""

    model_config = ConfigDict(extra="forbid")

    frame: int = Field(ge=0)
    position: list[float] = Field(description="[x, y, z] camera position in meters")
    look_at: list[float] = Field(description="[x, y, z] point the camera looks at")

    @field_validator("position", "look_at")
    @classmethod
    def _check_positions(cls, v: list[float]) -> list[float]:
        return _validate_position(v, "position/look_at")


class SceneCamera(BaseModel):
    """A camera with shot type and animation keyframes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    shot_type: ShotType = Field(default="medium", description="Cinematographic shot type")
    #: Human-authored name for this camera, e.g. "飞船俯瞰". Rendered by the
    #: frontend as "机位05 | 飞船俯瞰" (see `shotLabels.cameraLabel`), because
    #: `id` is a machine identifier (`cam_5`) and `shot_type` is one of five
    #: enums — neither names a shot a reviewer could search for.
    #:
    #: Optional and additive, exactly like `SceneShot.transition_intent`: an
    #: author (or an LLM) that never declares one keeps the ordinal-only label,
    #: and every consumer must fall back to it. The frontend declares the mirror
    #: field in the hand-written `src/types/scene-script.ts` (not generated —
    #: the contract generator emits only enums and colours).
    display_name: str | None = Field(default=None, max_length=64)
    keyframes: list[CameraKeyframe] = Field(
        min_length=1, description="At least one keyframe (static cameras need frame 0)"
    )

    @field_validator("display_name", mode="before")
    @classmethod
    def _coerce_display_name(cls, value: object) -> object:
        # Same tolerance as `transition_intent`: a free-text sentence where a
        # name belongs would otherwise reject the whole scene, and a declaration
        # nobody can read is not a declaration. Blank means un-authored.
        if not isinstance(value, str):
            return None
        trimmed = value.strip()
        return trimmed[:64] if trimmed else None


class SceneShot(BaseModel):
    """A shot: a time range bound to a camera."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    camera: str = Field(description="Reference to a camera id")
    start_frame: int = Field(ge=0)
    end_frame: int = Field(description="Must be > start_frame")
    description: str = Field(default="", max_length=500)
    #: How this shot ENTERS (V0.2 §13 第 5 问): the id of the transition
    #: reading the author chose for the cut into this shot ("sound_bridge",
    #: "cut_after_line", an LLM-proposed id, ...).
    #:
    #: §13 asks whether the relation needs a connector LINE or suits a label,
    #: a status, a hint, or hiding. Answer here: a LABEL on the shot — the
    #: transitions are already authored as keyframes inside the script (a
    #: reading IS camera and character motion), so a line would be a second,
    #: disagreeing copy of the same information. What was missing is that the
    #: CHOICE was not recorded: "哪一镜以何种读法接入" had no answer that outlived
    #: the moment the author picked it. A label makes the relation queryable
    #: (and therefore checkable — see
    #: ``transition_intents.check_declared_intents``) without inventing a
    #: competing source of truth.
    #:
    #: Optional and additive: a script that never declares one renders and
    #: behaves exactly as before.
    transition_intent: str | None = Field(
        default=None,
        max_length=MAX_TRANSITION_INTENT_LENGTH,
        description="Reading id this shot enters with (V0.2 §13 第5问)",
    )

    @field_validator("transition_intent", mode="before")
    @classmethod
    def _coerce_transition_intent(cls, value: object) -> object:
        # Same tolerance as the colour fields: an LLM that emits a sentence
        # where an id belongs would otherwise reject the whole scene, and a
        # declaration the author cannot read is not a declaration.
        if not isinstance(value, str):
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        return trimmed[:MAX_TRANSITION_INTENT_LENGTH]

    @model_validator(mode="after")
    def _check_frame_range(self) -> SceneShot:
        if self.end_frame <= self.start_frame:
            raise ValueError(
                f"shot '{self.id}': end_frame ({self.end_frame}) must be > "
                f"start_frame ({self.start_frame})"
            )
        return self


class SpeechBinding(BaseModel):
    """Binds a character to a speech audio asset for timing alignment."""

    model_config = ConfigDict(extra="forbid")

    character: str = Field(description="Reference to a character id")
    speech_asset: str = Field(min_length=1, description="Reference to a speech_audio asset")
    mode: SpeechMode = Field(
        default="free",
        description="'bound': speech duration drives shot timing; 'free': independent",
    )


class SceneInfo(BaseModel):
    """Top-level scene metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    environment: EnvironmentKind = Field(default="indoor")
    lighting: LightingPreset = Field(default="warm")
    duration: float = Field(gt=0, le=600, description="Total duration in seconds")
    frame_rate: int = Field(default=30, ge=1, le=120, description="Frames per second")


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class SceneScriptRoot(BaseModel):
    """Root SceneScript document: the complete 3D previs scene description."""

    model_config = ConfigDict(extra="forbid")

    scene: SceneInfo
    characters: list[SceneCharacter] = Field(default_factory=list)
    props: list[SceneProp] = Field(default_factory=list)
    environment: list[SceneEnvironmentObject] = Field(default_factory=list)
    cameras: list[SceneCamera] = Field(default_factory=list)
    shots: list[SceneShot] = Field(default_factory=list)
    speech_bindings: list[SpeechBinding] = Field(default_factory=list)

    # -- derived properties -------------------------------------------------

    @property
    def total_frames(self) -> int:
        """Total frame count = duration * frame_rate, rounded up."""
        return math.ceil(self.scene.duration * self.scene.frame_rate)

    @property
    def character_ids(self) -> set[str]:
        return {c.id for c in self.characters}

    @property
    def camera_ids(self) -> set[str]:
        return {c.id for c in self.cameras}

    # -- cross-field validators --------------------------------------------

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> SceneScriptRoot:
        """All ids within each collection must be unique."""
        for collection_name, items in [
            ("characters", self.characters),
            ("props", self.props),
            ("environment", self.environment),
            ("cameras", self.cameras),
            ("shots", self.shots),
        ]:
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                dupes = [x for x in ids if ids.count(x) > 1]
                raise ValueError(f"duplicate {collection_name} ids: {sorted(set(dupes))}")
        return self

    @model_validator(mode="after")
    def _validate_camera_references(self) -> SceneScriptRoot:
        """Every shot's camera must reference an existing camera."""
        for shot in self.shots:
            if shot.camera not in self.camera_ids:
                raise ValueError(
                    f"shot '{shot.id}' references camera '{shot.camera}' which does not exist; "
                    f"available: {sorted(self.camera_ids)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_speech_references(self) -> SceneScriptRoot:
        """Every speech_binding's character must reference an existing character."""
        for binding in self.speech_bindings:
            if binding.character not in self.character_ids:
                raise ValueError(
                    f"speech_binding references character '{binding.character}' which does not exist; "
                    f"available: {sorted(self.character_ids)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_held_references(self) -> SceneScriptRoot:
        """Every held prop's holder must reference an existing character.

        Fail closed like speech_bindings: a held item whose holder does not
        exist would silently stop following anyone, and "the prop is in her
        hand" is exactly the claim the Continuity State layer must not drop.
        """
        for prop in self.props:
            if prop.held_by is None:
                continue
            if prop.held_by not in self.character_ids:
                raise ValueError(
                    f"prop '{prop.id}' is held by character '{prop.held_by}' which does "
                    f"not exist; available: {sorted(self.character_ids)}"
                )
        return self

    @model_validator(mode="after")
    def _validate_actor_actions(self) -> SceneScriptRoot:
        """A character's actions must match the body it declared.

        Fail closed, and for a specific reason: a door authored with
        ``action: "walk"`` has no legs, and every consumer would have to invent
        its own meaning for it — the renderer, the pose library, the summary.
        One validator naming it is the difference between a loud error and two
        renderers quietly disagreeing about what a door walking looks like.

        The rule is simple: a lowpoly_human may use either family (a human
        figure sliding along a path is a legitimate move), and anything else may
        only use the non-human family.
        """
        human_actions = set(get_args(CharacterAction))
        nonhuman_actions = set(get_args(NonHumanActorAction))
        for character in self.characters:
            allowed = (
                human_actions | nonhuman_actions
                if character.type == "lowpoly_human"
                else nonhuman_actions
            )
            for keyframe in character.keyframes:
                if character.type != "lowpoly_human" and keyframe.pose is not None:
                    raise ValueError(
                        f"character '{character.id}' has type '{character.type}' but declares "
                        "human joint pose angles"
                    )
                if keyframe.action not in allowed:
                    raise ValueError(
                        f"character '{character.id}' has type "
                        f"'{character.type}' but keyframe {keyframe.frame} declares "
                        f"action '{keyframe.action}', which that body cannot perform; "
                        f"allowed: {sorted(allowed)}"
                    )
        return self

    @model_validator(mode="after")
    def _validate_shot_ranges(self) -> SceneScriptRoot:
        """Shots must not overlap and must be within total frame count."""
        if not self.shots:
            return self

        total = self.total_frames
        sorted_shots = sorted(self.shots, key=lambda s: s.start_frame)

        for shot in sorted_shots:
            if shot.end_frame > total:
                raise ValueError(
                    f"shot '{shot.id}': end_frame ({shot.end_frame}) exceeds total frames "
                    f"({total}) = duration ({self.scene.duration}s) × frame_rate "
                    f"({self.scene.frame_rate})"
                )

        for i in range(len(sorted_shots) - 1):
            current = sorted_shots[i]
            next_shot = sorted_shots[i + 1]
            if current.end_frame > next_shot.start_frame:
                raise ValueError(
                    f"shots overlap: '{current.id}' (ends frame {current.end_frame}) and "
                    f"'{next_shot.id}' (starts frame {next_shot.start_frame})"
                )
        return self

    @model_validator(mode="after")
    def _validate_keyframe_bounds(self) -> SceneScriptRoot:
        """Character and camera keyframes must be within total frame count."""
        total = self.total_frames
        for char in self.characters:
            for kf in char.keyframes:
                if kf.frame > total:
                    raise ValueError(
                        f"character '{char.id}' keyframe at frame {kf.frame} exceeds "
                        f"total frames ({total})"
                    )
        for cam in self.cameras:
            for kf in cam.keyframes:
                if kf.frame > total:
                    raise ValueError(
                        f"camera '{cam.id}' keyframe at frame {kf.frame} exceeds "
                        f"total frames ({total})"
                    )
        # Props and environment are checked here too. It used to be that they
        # had no keyframes at all, so there was nothing to check; now that they
        # do, an out-of-range keyframe would render as a prop that never moves
        # (the renderer clamps to the last frame it has) while the script claims
        # a motion past the end. Same failure, same message, same rule.
        for prop in self.props:
            for kf in prop.keyframes:
                if kf.frame > total:
                    raise ValueError(
                        f"prop '{prop.id}' keyframe at frame {kf.frame} exceeds "
                        f"total frames ({total})"
                    )
        for env in self.environment:
            for kf in env.keyframes:
                if kf.frame > total:
                    raise ValueError(
                        f"environment '{env.id}' keyframe at frame {kf.frame} exceeds "
                        f"total frames ({total})"
                    )
        return self

    @model_validator(mode="after")
    def _validate_held_and_keyframed(self) -> SceneScriptRoot:
        """A held prop may not also be keyframed.

        Two drivers of one prop, and nothing that says which wins. The existing
        precedent is ``_validate_held_references``: a held item's position is
        DERIVED from its holder's hand (``held_items.hand_offset``), which is
        the Continuity State guarantee — the item cannot vanish at a cut or
        switch hands, because those states are not representable. A keyframe
        that moves the item away from the hand would make both of those possible
        again, silently, and the two renderers would have to agree on which
        source wins.

        Rejected rather than merged: the alternative is picking a precedence
        rule and documenting it, which is how a prop ends up "usually in the
        hand" — the exact drift the Continuity State layer exists to prevent.
        """
        for prop in self.props:
            if prop.held_by is not None and prop.keyframes:
                raise ValueError(
                    f"prop '{prop.id}' is both held by '{prop.held_by}' and has "
                    f"{len(prop.keyframes)} keyframes; a held item's position comes "
                    f"from its holder's hand, so it cannot also be animated"
                )
        return self

    @model_validator(mode="after")
    def _validate_camera_keyframes_in_shots(self) -> SceneScriptRoot:
        """Camera keyframes should fall within at least one shot that uses that camera.

        This is a soft structural check: a camera with keyframes outside all its
        shots indicates a timing mismatch. We warn by raising only when ALL keyframes
        of a camera are outside its shots.
        """
        if not self.shots:
            return self

        for cam in self.cameras:
            cam_shots = [s for s in self.shots if s.camera == cam.id]
            if not cam_shots:
                continue  # camera exists but unused; not an error
            for kf in cam.keyframes:
                in_any_shot = any(s.start_frame <= kf.frame <= s.end_frame for s in cam_shots)
                if not in_any_shot:
                    raise ValueError(
                        f"camera '{cam.id}' keyframe at frame {kf.frame} is outside all "
                        f"shots using this camera (shots: "
                        f"{[(s.id, s.start_frame, s.end_frame) for s in cam_shots]})"
                    )
        return self
