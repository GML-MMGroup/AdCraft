"""Camera shot template library for rapid SceneScript generation.

Provides pre-defined camera/shot templates for common scene patterns. Users
can select a template and fill in character/scene details to quickly generate
a valid SceneScript, rather than specifying every camera position manually.

Templates cover:
- dialogue: Two-character dialogue with shot/reverse-shot pattern
- monologue: Single character speaking to camera
- entrance: Character entering a scene and approaching
- establishing: Wide establishing shot of environment
- showcase: Product/object showcase with orbiting camera
- walk_and_talk: Characters walking while talking

See: docs/3d-previs/prompt-engineering-guide.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.scene_script import (
    SceneScriptRoot,
    SceneInfo,
    SceneCharacter,
    CharacterAppearance,
    CharacterKeyframe,
    SceneProp,
    SceneEnvironmentObject,
    SceneCamera,
    CameraKeyframe,
    SceneShot,
)


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------


@dataclass
class ShotTemplate:
    """A reusable shot template specification."""

    template_id: str
    name: str
    description: str
    category: str  # "dialogue" | "single" | "movement" | "environment" | "showcase"
    min_characters: int
    max_characters: int
    default_duration: float
    default_frame_rate: int = 30
    tags: list[str] = field(default_factory=list)


# Template catalog
SHOT_TEMPLATES: list[ShotTemplate] = [
    ShotTemplate(
        template_id="dialogue_shot_reverse",
        name="Dialogue: Shot/Reverse-Shot",
        description="Two-character dialogue with alternating over-the-shoulder shots. Classic conversation coverage.",
        category="dialogue",
        min_characters=2,
        max_characters=2,
        default_duration=8.0,
        tags=["dialogue", "conversation", "two-shot", "OTS"],
    ),
    ShotTemplate(
        template_id="dialogue_wide_then_cu",
        name="Dialogue: Wide Establish then Close-ups",
        description="Start with wide two-shot, then cut to close-ups of each speaker.",
        category="dialogue",
        min_characters=2,
        max_characters=3,
        default_duration=10.0,
        tags=["dialogue", "wide", "close-up", "establishing"],
    ),
    ShotTemplate(
        template_id="monologue_to_camera",
        name="Monologue: Direct to Camera",
        description="Single character speaking directly to camera, with subtle push-in.",
        category="single",
        min_characters=1,
        max_characters=1,
        default_duration=6.0,
        tags=["monologue", "direct-address", "POV", "push-in"],
    ),
    ShotTemplate(
        template_id="character_entrance",
        name="Character Entrance",
        description="Character enters from background and approaches foreground. Wide to medium tracking.",
        category="movement",
        min_characters=1,
        max_characters=2,
        default_duration=5.0,
        tags=["entrance", "walking", "tracking", "wide-to-medium"],
    ),
    ShotTemplate(
        template_id="establishing_shot",
        name="Establishing Shot",
        description="Slow wide shot establishing environment and spatial layout. No character focus.",
        category="environment",
        min_characters=0,
        max_characters=5,
        default_duration=4.0,
        tags=["establishing", "wide", "environment", "slow-pan"],
    ),
    ShotTemplate(
        template_id="product_showcase_orbit",
        name="Product Showcase: Orbit",
        description="Camera orbits around a central object/character. 360-degree showcase.",
        category="showcase",
        min_characters=0,
        max_characters=1,
        default_duration=6.0,
        tags=["showcase", "orbit", "360", "product"],
    ),
    ShotTemplate(
        template_id="walk_and_talk",
        name="Walk and Talk",
        description="Two characters walking side by side while conversing. Side-tracking camera.",
        category="movement",
        min_characters=2,
        max_characters=2,
        default_duration=8.0,
        tags=["walk-talk", "tracking", "side-shot", "movement"],
    ),
]


def list_templates(category: str | None = None) -> list[ShotTemplate]:
    """List available shot templates, optionally filtered by category."""
    if category:
        return [t for t in SHOT_TEMPLATES if t.category == category]
    return list(SHOT_TEMPLATES)


def get_template(template_id: str) -> ShotTemplate | None:
    """Get a template by ID."""
    return next((t for t in SHOT_TEMPLATES if t.template_id == template_id), None)


# ---------------------------------------------------------------------------
# Template-based SceneScript generators
# ---------------------------------------------------------------------------


def _make_character(
    char_id: str,
    position: list[float],
    rotation_y: float = 0,
    action: str = "stand",
    color: str = "#8B4513",
    height: float = 1.7,
) -> SceneCharacter:
    return SceneCharacter(
        id=char_id,
        type="lowpoly_human",
        appearance=CharacterAppearance(color=color, height=height, scale=1.0),
        keyframes=[
            CharacterKeyframe(
                frame=0,
                position=position,
                rotation_y=rotation_y,
                action=action,
            )
        ],
    )


def generate_dialogue_shot_reverse(
    scene_name: str = "dialogue-scene",
    char1_name: str = "char1",
    char2_name: str = "char2",
    duration: float = 8.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate a dialogue shot/reverse-shot SceneScript.

    Two characters face each other across a table. Shot 1 is over-the-shoulder
    of char1 looking at char2; shot 2 is reverse, over-the-shoulder of char2.
    """
    total_frames = int(duration * frame_rate)
    mid_frame = total_frames // 2

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="warm",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[
            _make_character(char1_name, [0.9, -0.9, 0], rotation_y=150, action="talk", color="#8B4513"),
            _make_character(char2_name, [-1.0, -2.6, 0], rotation_y=-30, action="sit", color="#4A90D9"),
        ],
        props=[
            SceneProp(id="table1", type="round_table", position=[0, -1.6, 0], scale=1.0, rotation_y=0.0),
        ],
        environment=[
            SceneEnvironmentObject(id="wall1", type="wall", position=[0, -7, 2.5], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_ots1",
                shot_type="over_shoulder",
                keyframes=[
                    CameraKeyframe(frame=0, position=[2.5, -4.0, 1.7], look_at=[-1.0, -2.6, 1.5]),
                ],
            ),
            SceneCamera(
                id="cam_ots2",
                shot_type="over_shoulder",
                keyframes=[
                    CameraKeyframe(frame=mid_frame, position=[-2.5, -0.5, 1.7], look_at=[0.9, -0.9, 1.5]),
                ],
            ),
        ],
        shots=[
            SceneShot(id="shot1", camera="cam_ots1", start_frame=0, end_frame=mid_frame,
                       description=f"Over-the-shoulder of {char1_name}, looking at {char2_name}"),
            SceneShot(id="shot2", camera="cam_ots2", start_frame=mid_frame, end_frame=total_frames,
                       description=f"Reverse over-the-shoulder of {char2_name}"),
        ],
        speech_bindings=[],
    )


def generate_character_entrance(
    scene_name: str = "entrance-scene",
    char_name: str = "char1",
    duration: float = 5.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate a character entrance SceneScript.

    Character enters from background doorway and approaches foreground.
    Camera starts wide, pushes in to medium as character approaches.
    """
    total_frames = int(duration * frame_rate)

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="warm",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[
            SceneCharacter(
                id=char_name,
                type="lowpoly_human",
                appearance=CharacterAppearance(color="#2ECC71", height=1.75, scale=1.0),
                keyframes=[
                    CharacterKeyframe(frame=0, position=[2.2, -5.4, 0], rotation_y=160, action="walk"),
                    CharacterKeyframe(frame=total_frames // 2, position=[1.8, -3.0, 0], rotation_y=160, action="walk"),
                    CharacterKeyframe(frame=total_frames - 1, position=[1.0, -1.5, 0], rotation_y=180, action="stand"),
                ],
            ),
        ],
        props=[],
        environment=[
            SceneEnvironmentObject(id="wall1", type="wall", position=[0, -7, 2.5], scale=1.0, rotation_y=0.0),
            SceneEnvironmentObject(id="door1", type="door", position=[2.2, -6.0, 1.5], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_track",
                shot_type="wide",
                keyframes=[
                    CameraKeyframe(frame=0, position=[12, -14, 8], look_at=[0, -1.5, 1.3]),
                    CameraKeyframe(frame=total_frames - 1, position=[6, -8, 4], look_at=[1.0, -1.5, 1.5]),
                ],
            ),
        ],
        shots=[
            SceneShot(id="shot1", camera="cam_track", start_frame=0, end_frame=total_frames,
                       description=f"Wide tracking shot as {char_name} enters and approaches"),
        ],
        speech_bindings=[],
    )


def generate_establishing_shot(
    scene_name: str = "establishing-scene",
    duration: float = 4.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate an establishing shot SceneScript.

    Slow wide shot with subtle pan, establishing environment and spatial layout.
    """
    total_frames = int(duration * frame_rate)

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="warm",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[],
        props=[
            SceneProp(id="table1", type="round_table", position=[0, -1.6, 0], scale=1.0, rotation_y=0.0),
        ],
        environment=[
            SceneEnvironmentObject(id="wall1", type="wall", position=[0, -7, 2.5], scale=1.0, rotation_y=0.0),
            SceneEnvironmentObject(id="pillar1", type="pillar", position=[-3.5, -6.7, 2.1], scale=1.0, rotation_y=0.0),
            SceneEnvironmentObject(id="pillar2", type="pillar", position=[3.5, -6.7, 2.1], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_wide",
                shot_type="wide",
                keyframes=[
                    CameraKeyframe(frame=0, position=[14, -16, 9], look_at=[0, -3, 2]),
                    CameraKeyframe(frame=total_frames - 1, position=[10, -12, 7], look_at=[0, -3, 2]),
                ],
            ),
        ],
        shots=[
            SceneShot(id="shot1", camera="cam_wide", start_frame=0, end_frame=total_frames,
                       description="Slow wide establishing shot with subtle push-in"),
        ],
        speech_bindings=[],
    )


def generate_monologue_to_camera(
    scene_name: str = "monologue-scene",
    char_name: str = "char1",
    duration: float = 6.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate a direct-to-camera monologue SceneScript with a subtle push-in.

    Single character faces the camera (rotation_y ~180); the camera starts
    medium-wide and pushes in to medium by the last frame.
    """
    total_frames = int(duration * frame_rate)

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="neutral",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[
            _make_character(char_name, [0.0, -2.0, 0], rotation_y=180, action="talk", color="#E67E22"),
        ],
        props=[],
        environment=[
            SceneEnvironmentObject(id="wall1", type="wall", position=[0, -5, 2.5], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_push",
                shot_type="medium",
                keyframes=[
                    CameraKeyframe(frame=0, position=[0.0, -7.5, 1.9], look_at=[0.0, -2.0, 1.4]),
                    CameraKeyframe(frame=total_frames - 1, position=[0.0, -4.5, 1.7], look_at=[0.0, -2.0, 1.4]),
                ],
            ),
        ],
        shots=[
            SceneShot(
                id="shot1",
                camera="cam_push",
                start_frame=0,
                end_frame=total_frames,
                description=f"{char_name} speaks directly to camera with a subtle push-in",
            ),
        ],
        speech_bindings=[],
    )


def generate_product_showcase_orbit(
    scene_name: str = "product-orbit",
    prop_id: str = "product1",
    prop_type: str = "vase",
    duration: float = 6.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate a product showcase SceneScript with a partial orbit camera.

    A single prop sits at the origin on a pedestal; the camera arcs from a
    front-left position around to the front-right over the clip duration.
    """
    total_frames = int(duration * frame_rate)
    quarter = total_frames // 4
    three_quarter = (total_frames * 3) // 4

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="dramatic",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[],
        props=[
            SceneProp(id=prop_id, type=prop_type, position=[0.0, 0.0, 0.0], scale=1.0, rotation_y=0.0),
            SceneProp(id="table1", type="rect_table", position=[0.0, 0.0, -0.4], scale=1.0, rotation_y=0.0),
        ],
        environment=[
            SceneEnvironmentObject(id="wall1", type="wall", position=[0.0, -4.5, 2.5], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_orbit",
                shot_type="closeup",
                keyframes=[
                    CameraKeyframe(frame=0, position=[-2.4, -3.2, 1.4], look_at=[0.0, 0.0, 1.0]),
                    CameraKeyframe(frame=quarter, position=[0.0, -4.0, 1.2], look_at=[0.0, 0.0, 1.0]),
                    CameraKeyframe(frame=three_quarter, position=[2.4, -3.2, 1.4], look_at=[0.0, 0.0, 1.0]),
                    CameraKeyframe(frame=total_frames - 1, position=[3.0, -1.5, 1.6], look_at=[0.0, 0.0, 1.0]),
                ],
            ),
        ],
        shots=[
            SceneShot(
                id="shot1",
                camera="cam_orbit",
                start_frame=0,
                end_frame=total_frames,
                description=f"Orbiting showcase of {prop_id}",
            ),
        ],
        speech_bindings=[],
    )


def generate_walk_and_talk(
    scene_name: str = "walk-talk-scene",
    char1_name: str = "char1",
    char2_name: str = "char2",
    duration: float = 8.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate a walk-and-talk SceneScript with two characters and side tracking.

    Both characters walk from left background toward the right; the camera
    tracks alongside them on the X axis, keeping the pair centered.
    """
    total_frames = int(duration * frame_rate)
    mid_frame = total_frames // 2

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="outdoor",
            lighting="soft",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[
            SceneCharacter(
                id=char1_name,
                type="lowpoly_human",
                appearance=CharacterAppearance(color="#8B4513", height=1.7, scale=1.0),
                keyframes=[
                    CharacterKeyframe(frame=0, position=[-3.0, -3.0, 0], rotation_y=90, action="walk"),
                    CharacterKeyframe(frame=mid_frame, position=[0.0, -1.0, 0], rotation_y=90, action="walk"),
                    CharacterKeyframe(frame=total_frames - 1, position=[3.0, 1.0, 0], rotation_y=90, action="talk"),
                ],
            ),
            SceneCharacter(
                id=char2_name,
                type="lowpoly_human",
                appearance=CharacterAppearance(color="#4A90D9", height=1.65, scale=1.0),
                keyframes=[
                    CharacterKeyframe(frame=0, position=[-3.4, -4.2, 0], rotation_y=90, action="walk"),
                    CharacterKeyframe(frame=mid_frame, position=[-0.4, -2.2, 0], rotation_y=90, action="walk"),
                    CharacterKeyframe(frame=total_frames - 1, position=[2.6, -0.2, 0], rotation_y=90, action="talk"),
                ],
            ),
        ],
        props=[],
        environment=[
            SceneEnvironmentObject(id="pillar1", type="pillar", position=[-5.0, -6.0, 2.1], scale=1.0, rotation_y=0.0),
            SceneEnvironmentObject(id="pillar2", type="pillar", position=[5.0, -6.0, 2.1], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_side",
                shot_type="wide",
                keyframes=[
                    CameraKeyframe(frame=0, position=[-6.5, 2.5, 1.8], look_at=[-3.2, -3.6, 1.2]),
                    CameraKeyframe(frame=mid_frame, position=[0.0, 0.5, 1.8], look_at=[-0.2, -1.6, 1.2]),
                    CameraKeyframe(frame=total_frames - 1, position=[6.5, -1.5, 1.8], look_at=[2.8, 0.4, 1.2]),
                ],
            ),
        ],
        shots=[
            SceneShot(
                id="shot1",
                camera="cam_side",
                start_frame=0,
                end_frame=total_frames,
                description=f"{char1_name} and {char2_name} walk side by side in conversation",
            ),
        ],
        speech_bindings=[],
    )


def generate_dialogue_wide_then_cu(
    scene_name: str = "dialogue-wide-cu",
    char1_name: str = "char1",
    char2_name: str = "char2",
    duration: float = 10.0,
    frame_rate: int = 30,
) -> SceneScriptRoot:
    """Generate a dialogue SceneScript: wide two-shot, then close-ups of each speaker.

    Shot 1 is a static wide two-shot; shot 2 is a close-up on char1; shot 3 is a
    close-up on char2. Shots are non-overlapping and cover the full duration.
    """
    total_frames = int(duration * frame_rate)
    third = total_frames // 3

    return SceneScriptRoot(
        scene=SceneInfo(
            name=scene_name,
            environment="indoor",
            lighting="warm",
            duration=duration,
            frame_rate=frame_rate,
        ),
        characters=[
            _make_character(char1_name, [0.9, -0.9, 0], rotation_y=150, action="talk", color="#8B4513"),
            _make_character(char2_name, [-1.0, -2.6, 0], rotation_y=-30, action="sit", color="#4A90D9"),
        ],
        props=[
            SceneProp(id="table1", type="round_table", position=[0, -1.6, 0], scale=1.0, rotation_y=0.0),
        ],
        environment=[
            SceneEnvironmentObject(id="wall1", type="wall", position=[0, -7, 2.5], scale=1.0, rotation_y=0.0),
        ],
        cameras=[
            SceneCamera(
                id="cam_wide",
                shot_type="wide",
                keyframes=[
                    CameraKeyframe(frame=0, position=[7.5, -9.5, 3.5], look_at=[0.0, -1.6, 1.4]),
                ],
            ),
            SceneCamera(
                id="cam_cu1",
                shot_type="closeup",
                keyframes=[
                    CameraKeyframe(frame=third, position=[2.2, -2.2, 1.6], look_at=[0.9, -0.9, 1.5]),
                ],
            ),
            SceneCamera(
                id="cam_cu2",
                shot_type="closeup",
                keyframes=[
                    CameraKeyframe(frame=third * 2, position=[-2.0, -4.2, 1.6], look_at=[-1.0, -2.6, 1.5]),
                ],
            ),
        ],
        shots=[
            SceneShot(
                id="shot1",
                camera="cam_wide",
                start_frame=0,
                end_frame=third,
                description=f"Wide two-shot of {char1_name} and {char2_name} at the table",
            ),
            SceneShot(
                id="shot2",
                camera="cam_cu1",
                start_frame=third,
                end_frame=third * 2,
                description=f"Close-up of {char1_name} speaking",
            ),
            SceneShot(
                id="shot3",
                camera="cam_cu2",
                start_frame=third * 2,
                end_frame=total_frames,
                description=f"Close-up of {char2_name} responding",
            ),
        ],
        speech_bindings=[],
    )


# ---------------------------------------------------------------------------
# Template dispatcher
# ---------------------------------------------------------------------------


TEMPLATE_GENERATORS: dict[str, Any] = {
    "dialogue_shot_reverse": generate_dialogue_shot_reverse,
    "dialogue_wide_then_cu": generate_dialogue_wide_then_cu,
    "monologue_to_camera": generate_monologue_to_camera,
    "character_entrance": generate_character_entrance,
    "establishing_shot": generate_establishing_shot,
    "product_showcase_orbit": generate_product_showcase_orbit,
    "walk_and_talk": generate_walk_and_talk,
}


def generate_from_template(
    template_id: str,
    **kwargs: Any,
) -> SceneScriptRoot:
    """Generate a SceneScript from a named template.

    Args:
        template_id: ID of the template to use.
        **kwargs: Template-specific parameters (scene_name, char names, duration, etc.).

    Returns:
        Validated SceneScriptRoot.

    Raises:
        ValueError: If template_id is not recognized.
    """
    generator = TEMPLATE_GENERATORS.get(template_id)
    if generator is None:
        available = ", ".join(TEMPLATE_GENERATORS.keys())
        raise ValueError(f"Unknown template '{template_id}'. Available: {available}")
    return generator(**kwargs)
