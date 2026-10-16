"""SceneScript to video-model prompt builder.

Generates video generation prompts from a validated SceneScript. Produces
per-shot prompts with camera language, character blocking, scene description,
and motion guidance. Also generates reference-asset guidance (reference video
or 5 keyframe images) based on model capability.

See: docs/3d-previs/prompt-engineering-guide.md
     docs/adr/0005-3d-low-fidelity-previs.md (§4a fallback strategy)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.scene_script import (
    SceneScriptRoot,
    SceneShot,
    SceneCharacter,
    SceneCamera,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ShotPrompt:
    """Video generation prompt for one shot."""

    shot_id: str
    camera_id: str
    start_frame: int
    end_frame: int
    duration_seconds: float
    prompt: str  # Main generation prompt (English)
    negative_prompt: str = ""
    camera_description: str = ""
    characters_in_shot: list[str] = field(default_factory=list)
    reference_mode: str = "video"  # "video" | "keyframes" | "none"
    reference_assets: list[str] = field(default_factory=list)


@dataclass
class VideoPromptBundle:
    """Complete video generation prompt bundle for a SceneScript."""

    scene_name: str
    total_duration: float
    total_frames: int
    global_prompt: str  # Overall scene description
    global_negative_prompt: str
    shots: list[ShotPrompt]
    reference_mode: str  # "video" | "keyframes" | "none"


# ---------------------------------------------------------------------------
# Camera language mapping
# ---------------------------------------------------------------------------

SHOT_TYPE_TO_CAMERA_LANGUAGE: dict[str, str] = {
    "wide": "wide establishing shot",
    "medium": "medium shot",
    "closeup": "close-up shot",
    "over_shoulder": "over-the-shoulder shot",
    "pov": "point-of-view shot",
    "top_down": "top-down bird's eye view",
    "low_angle": "low angle shot",
    "high_angle": "high angle shot",
    "dutch": "dutch angle shot",
}


def _camera_movement_description(camera: SceneCamera) -> str:
    """Describe camera movement based on keyframe delta."""
    if len(camera.keyframes) < 2:
        return "static camera"

    first = camera.keyframes[0]
    last = camera.keyframes[-1]
    dx = last.position[0] - first.position[0]
    dy = last.position[1] - first.position[1]
    dz = last.position[2] - first.position[2]
    distance = (dx**2 + dy**2 + dz**2) ** 0.5

    if distance < 0.5:
        return "static camera"
    if distance < 2.0:
        return "subtle camera push-in"
    if abs(dx) > abs(dy) and abs(dx) > abs(dz):
        direction = "right" if dx > 0 else "left"
        return f"camera pans {direction}"
    if abs(dz) > abs(dx) and abs(dz) > abs(dy):
        if dz < 0:
            return "camera dollies forward (push-in)"
        return "camera dollies backward (pull-out)"
    return f"camera moves {distance:.1f} units through scene"


def _shot_type_language(shot_type: str) -> str:
    return SHOT_TYPE_TO_CAMERA_LANGUAGE.get(shot_type, f"{shot_type} shot")


# ---------------------------------------------------------------------------
# Character description
# ---------------------------------------------------------------------------


def _character_action_language(action: str | None) -> str:
    """Map SceneScript action enum to natural language."""
    action_map = {
        "stand": "standing still",
        "sit": "sitting",
        "walk": "walking",
        "run": "running",
        "talk": "speaking",
        "listen": "listening attentively",
        "turn": "turning",
        "gesture": "gesturing with hands",
        "enter": "entering the scene",
        "exit": "leaving the scene",
        "pickup": "picking up an object",
        "putdown": "placing an object down",
        "drink": "drinking",
        "eat": "eating",
        "look": "looking",
        "react": "reacting",
        "idle": "idle breathing motion",
    }
    return action_map.get(action or "idle", action or "standing")


def _describe_character_in_shot(
    character: SceneCharacter, shot: SceneShot
) -> str:
    """Describe a character's state within a shot's frame range."""
    # Find keyframes within or near the shot
    relevant_kfs = [
        kf for kf in character.keyframes
        if shot.start_frame <= kf.frame <= shot.end_frame
    ]
    if not relevant_kfs:
        # Use nearest keyframe
        relevant_kfs = sorted(
            character.keyframes,
            key=lambda kf: min(abs(kf.frame - shot.start_frame), abs(kf.frame - shot.end_frame)),
        )[:1]

    if not relevant_kfs:
        return f"{character.id} present"

    actions = [_character_action_language(kf.action) for kf in relevant_kfs]
    unique_actions = list(dict.fromkeys(actions))  # deduplicate preserving order

    if len(unique_actions) == 1:
        return f"{character.id} {unique_actions[0]}"
    return f"{character.id} " + " then ".join(unique_actions)


# ---------------------------------------------------------------------------
# Environment description
# ---------------------------------------------------------------------------


def _environment_language(environment: str, lighting: str) -> str:
    env_map = {
        "indoor": "interior scene",
        "outdoor": "exterior scene",
        "studio": "studio setting",
        "street": "street scene",
        "room": "room interior",
        "forest": "forest setting",
        "city": "urban city setting",
    }
    light_map = {
        "warm": "warm golden lighting",
        "cool": "cool blue lighting",
        "soft": "soft diffused lighting",
        "neutral": "neutral natural lighting",
        "dramatic": "dramatic high-contrast lighting",
        "dark": "dim moody lighting",
        "bright": "bright well-lit scene",
    }
    env = env_map.get(environment, f"{environment} setting")
    light = light_map.get(lighting, f"{lighting} lighting")
    return f"{env}, {light}"


# ---------------------------------------------------------------------------
# Main prompt builder
# ---------------------------------------------------------------------------


def build_shot_prompt(
    scene_script: SceneScriptRoot,
    shot: SceneShot,
    reference_mode: str = "video",
) -> ShotPrompt:
    """Build a video generation prompt for one shot."""
    camera = next(
        (c for c in scene_script.cameras if c.id == shot.camera),
        scene_script.cameras[0] if scene_script.cameras else None,
    )

    shot_type = camera.shot_type if camera else "medium"
    camera_lang = _shot_type_language(shot_type)
    movement = _camera_movement_description(camera) if camera else "static camera"
    camera_description = f"{camera_lang}, {movement}"

    # Characters in this shot (all characters, since SceneScript doesn't
    # explicitly assign characters to shots — they're all in the scene)
    char_descriptions = [
        _describe_character_in_shot(c, shot)
        for c in scene_script.characters
    ]
    char_ids = [c.id for c in scene_script.characters]

    # Environment
    env_lang = _environment_language(
        scene_script.scene.environment, scene_script.scene.lighting
    )

    # Props
    prop_names = [p.type.replace("_", " ") for p in scene_script.props]
    props_lang = f", featuring {', '.join(prop_names)}" if prop_names else ""

    # Assemble prompt
    duration = (shot.end_frame - shot.start_frame) / scene_script.scene.frame_rate
    action_text = "; ".join(char_descriptions) if char_descriptions else "no characters"

    prompt_parts = [
        f"{camera_description}.",
        f"{env_lang}{props_lang}.",
        f"Characters: {action_text}.",
        f"Cinematic composition, {duration:.1f}s continuous shot.",
        "Low-fidelity 3D previs style, simple geometric forms, clear spatial layout.",
    ]

    if shot.description:
        prompt_parts.insert(0, f"{shot.description}.")

    prompt = " ".join(prompt_parts)

    negative_prompt = (
        "photorealistic, detailed textures, complex lighting, "
        "text overlays, watermark, distorted geometry, flickering"
    )

    return ShotPrompt(
        shot_id=shot.id,
        camera_id=shot.camera,
        start_frame=shot.start_frame,
        end_frame=shot.end_frame,
        duration_seconds=duration,
        prompt=prompt,
        negative_prompt=negative_prompt,
        camera_description=camera_description,
        characters_in_shot=char_ids,
        reference_mode=reference_mode,
    )


def build_video_prompt_bundle(
    scene_script: SceneScriptRoot,
    reference_mode: str = "video",
) -> VideoPromptBundle:
    """Build a complete video generation prompt bundle.

    Args:
        scene_script: Validated SceneScript root.
        reference_mode: How to guide the video model:
            - "video": use rendered previs video as reference
            - "keyframes": use 5 keyframe images per shot (fallback for
              models that don't support reference video, ADR 0005 §4a)
            - "none": prompt-only, no reference assets

    Returns:
        VideoPromptBundle with global and per-shot prompts.
    """
    total_frames = scene_script.total_frames
    total_duration = scene_script.scene.duration

    # Global prompt
    env_lang = _environment_language(
        scene_script.scene.environment, scene_script.scene.lighting
    )
    char_count = len(scene_script.characters)
    shot_count = len(scene_script.shots)

    global_prompt = (
        f"{scene_script.scene.name}: {env_lang}. "
        f"{char_count} character(s), {shot_count} shot(s). "
        f"Total duration {total_duration:.1f}s. "
        f"Low-fidelity 3D previs animation with controllable camera and blocking."
    )

    global_negative_prompt = (
        "photorealistic, detailed textures, complex VFX, "
        "text overlays, watermark, distorted geometry, inconsistent character design"
    )

    # Per-shot prompts
    shots = [
        build_shot_prompt(scene_script, shot, reference_mode)
        for shot in scene_script.shots
    ]

    return VideoPromptBundle(
        scene_name=scene_script.scene.name,
        total_duration=total_duration,
        total_frames=total_frames,
        global_prompt=global_prompt,
        global_negative_prompt=global_negative_prompt,
        shots=shots,
        reference_mode=reference_mode,
    )


# ---------------------------------------------------------------------------
# Previs control level (ADR 0005 §4/§4a: queryable degradation, never silent)
# ---------------------------------------------------------------------------

PREVIS_CONTROL_LEVELS = ("full", "video_only", "images_only", "text_only")

_CONTROL_LEVEL_BY_MODE = {
    "video": "full",
    "keyframes": "images_only",
    "none": "text_only",
}


def previs_control_level(
    reference_mode: str,
    control_signals_available: bool,
) -> str:
    """Map the effective reference mode + control-signal availability to the
    ADR 0005 §4a `previs_control_level` degradation marker.

    - "full": reference video AND geometric control signals consumed
    - "video_only": reference video consumed, control signals unavailable
    - "images_only": 5 keyframe images consumed (no reference video support)
    - "text_only": prompt-only, no reference assets

    Unknown modes fail closed to "text_only" — a misspelled mode must never
    report higher control than was actually applied.
    """
    if reference_mode not in _CONTROL_LEVEL_BY_MODE:
        return "text_only"
    if reference_mode == "video" and not control_signals_available:
        return "video_only"
    return _CONTROL_LEVEL_BY_MODE[reference_mode]


# ---------------------------------------------------------------------------
# Reference asset guidance
# ---------------------------------------------------------------------------


def determine_reference_mode(
    model_supports_reference_video: bool,
    model_supports_reference_images: bool = True,
    control_signals_available: bool = False,
) -> str:
    """Determine the appropriate reference mode based on model capabilities.

    Implements ADR 0005 §4a fallback strategy:
    - If model supports reference video → "video"
    - Else if model supports reference images → "keyframes" (5 images/shot)
    - Else → "none" (prompt-only)

    ``control_signals_available`` does not change the mode selection: control
    passes are an optional add-on to reference video (ADR 0005 §4). It is
    accepted so callers can thread the capability through a single call; the
    degradation level is derived via :func:`previs_control_level`.
    """
    del control_signals_available  # reserved for §4 control-pass wiring
    if model_supports_reference_video:
        return "video"
    if model_supports_reference_images:
        return "keyframes"
    return "none"


def keyframe_guidance_text(shot: ShotPrompt) -> str:
    """Generate guidance text for keyframe-based reference (5 images/shot).

    Used when the video model doesn't support reference video. Describes
    what each of the 5 keyframes (0%, 25%, 50%, 75%, 100%) should contain.
    """
    return (
        f"Reference keyframes for shot '{shot.shot_id}' "
        f"({shot.duration_seconds:.1f}s, {shot.camera_description}):\n"
        f"- Frame 0 (0%): Opening composition, establish spatial layout\n"
        f"- Frame 1 (25%): Early action, character positioning\n"
        f"- Frame 2 (50%): Mid-shot peak action or camera movement\n"
        f"- Frame 3 (75%): Late action, transition toward closing\n"
        f"- Frame 4 (100%): Final composition, shot closing state\n"
        f"Use these 5 keyframes as visual anchors for temporal consistency. "
        f"Interpolate smoothly between keyframes. Characters: {', '.join(shot.characters_in_shot)}."
    )
