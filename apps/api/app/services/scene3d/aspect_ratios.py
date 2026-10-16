"""Multi-aspect-ratio adaptation for 3D previs.

Handles adaptation of SceneScript camera and render settings for different
video aspect ratios (16:9 landscape, 9:16 portrait, 1:1 square, etc.).
Adjusts camera FOV, position, and render resolution to maintain proper
framing across formats.

See: docs/adr/0005-3d-low-fidelity-previs.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.schemas.scene_script import (
    SceneScriptRoot,
    SceneCamera,
    CameraKeyframe,
)


# ---------------------------------------------------------------------------
# Aspect ratio definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AspectRatio:
    """A video aspect ratio specification."""

    ratio_id: str
    name: str
    width: int  # Default render width
    height: int  # Default render height
    ratio: float  # width / height
    orientation: str  # "landscape" | "portrait" | "square"
    common_uses: list[str]


ASPECT_RATIOS: list[AspectRatio] = [
    AspectRatio(
        ratio_id="16:9",
        name="Widescreen (16:9)",
        width=1920,
        height=1080,
        ratio=16 / 9,
        orientation="landscape",
        common_uses=["YouTube", "film", "TV", "desktop video"],
    ),
    AspectRatio(
        ratio_id="9:16",
        name="Vertical (9:16)",
        width=1080,
        height=1920,
        ratio=9 / 16,
        orientation="portrait",
        common_uses=["TikTok", "Reels", "Shorts", "mobile video"],
    ),
    AspectRatio(
        ratio_id="1:1",
        name="Square (1:1)",
        width=1080,
        height=1080,
        ratio=1.0,
        orientation="square",
        common_uses=["Instagram feed", "social media"],
    ),
    AspectRatio(
        ratio_id="4:3",
        name="Standard (4:3)",
        width=1440,
        height=1080,
        ratio=4 / 3,
        orientation="landscape",
        common_uses=["legacy TV", "presentation"],
    ),
    AspectRatio(
        ratio_id="21:9",
        name="Cinematic (21:9)",
        width=2520,
        height=1080,
        ratio=21 / 9,
        orientation="landscape",
        common_uses=["cinematic", "ultrawide", "film"],
    ),
    AspectRatio(
        ratio_id="4:5",
        name="Portrait (4:5)",
        width=1080,
        height=1350,
        ratio=4 / 5,
        orientation="portrait",
        common_uses=["Instagram portrait", "social media"],
    ),
]


def get_aspect_ratio(ratio_id: str) -> AspectRatio | None:
    """Get an aspect ratio by ID."""
    return next((r for r in ASPECT_RATIOS if r.ratio_id == ratio_id), None)


def list_aspect_ratios(orientation: str | None = None) -> list[AspectRatio]:
    """List available aspect ratios, optionally filtered by orientation."""
    if orientation:
        return [r for r in ASPECT_RATIOS if r.orientation == orientation]
    return list(ASPECT_RATIOS)


# ---------------------------------------------------------------------------
# Camera adaptation
# ---------------------------------------------------------------------------

# Base FOV for 16:9 reference (horizontal FOV in degrees)
BASE_HFOV_DEGREES = 60.0


def _hfov_to_vfov(hfov_deg: float, aspect_ratio: float) -> float:
    """Convert horizontal FOV to vertical FOV for a given aspect ratio."""
    hfov_rad = math.radians(hfov_deg)
    vfov_rad = 2 * math.atan(math.tan(hfov_rad / 2) / aspect_ratio)
    return math.degrees(vfov_rad)


def _vfov_to_hfov(vfov_deg: float, aspect_ratio: float) -> float:
    """Convert vertical FOV to horizontal FOV for a given aspect ratio."""
    vfov_rad = math.radians(vfov_deg)
    hfov_rad = 2 * math.atan(math.tan(vfov_rad / 2) * aspect_ratio)
    return math.degrees(hfov_rad)


def adapt_camera_for_aspect(
    camera: SceneCamera,
    target_ratio: AspectRatio,
    base_ratio: AspectRatio | None = None,
) -> SceneCamera:
    """Adapt a camera's position for a target aspect ratio.

    For portrait formats (9:16, 4:5), the camera is moved slightly farther
    back to maintain vertical framing. For landscape formats, position is
    largely preserved. The look_at targets are unchanged.

    Args:
        camera: Original camera to adapt.
        target_ratio: Target aspect ratio.
        base_ratio: Original/base aspect ratio (defaults to 16:9).

    Returns:
        New SceneCamera with adapted positions.
    """
    if base_ratio is None:
        base_ratio = get_aspect_ratio("16:9")

    # Calculate distance multiplier for portrait formats
    # For 9:16, we need to move back ~1.5x to maintain similar framing
    distance_multiplier = 1.0
    if target_ratio.orientation == "portrait":
        # Scale based on how much narrower the format is
        distance_multiplier = math.sqrt(base_ratio.ratio / target_ratio.ratio)
    elif target_ratio.ratio_id == "21:9":
        # Ultrawide: move slightly closer for cinematic feel
        distance_multiplier = 0.9

    adapted_keyframes = []
    for kf in camera.keyframes:
        # Scale camera position distance from look_at target
        cam_pos = kf.position
        look_at = kf.look_at

        # Calculate direction vector from look_at to camera
        dx = cam_pos[0] - look_at[0]
        dy = cam_pos[1] - look_at[1]
        dz = cam_pos[2] - look_at[2]

        # Apply distance multiplier
        new_pos = [
            look_at[0] + dx * distance_multiplier,
            look_at[1] + dy * distance_multiplier,
            look_at[2] + dz * distance_multiplier,
        ]

        adapted_keyframes.append(
            CameraKeyframe(
                frame=kf.frame,
                position=new_pos,
                look_at=list(look_at),
            )
        )

    return SceneCamera(
        id=camera.id,
        shot_type=camera.shot_type,
        keyframes=adapted_keyframes,
    )


def adapt_scene_script_for_aspect(
    scene_script: SceneScriptRoot,
    target_ratio_id: str,
) -> tuple[SceneScriptRoot, dict[str, Any]]:
    """Adapt an entire SceneScript for a target aspect ratio.

    Adapts all cameras and returns render settings for the target format.

    Args:
        scene_script: Original SceneScript to adapt.
        target_ratio_id: Target aspect ratio ID (e.g., "9:16", "1:1").

    Returns:
        Tuple of (adapted SceneScript, render_settings dict).

    Raises:
        ValueError: If target_ratio_id is not recognized.
    """
    target_ratio = get_aspect_ratio(target_ratio_id)
    if target_ratio is None:
        available = ", ".join(r.ratio_id for r in ASPECT_RATIOS)
        raise ValueError(f"Unknown aspect ratio '{target_ratio_id}'. Available: {available}")

    base_ratio = get_aspect_ratio("16:9")

    # Adapt all cameras
    adapted_cameras = [
        adapt_camera_for_aspect(cam, target_ratio, base_ratio)
        for cam in scene_script.cameras
    ]

    # Build adapted SceneScript (cameras replaced, everything else preserved)
    adapted = SceneScriptRoot(
        scene=scene_script.scene,
        characters=scene_script.characters,
        props=scene_script.props,
        environment=scene_script.environment,
        cameras=adapted_cameras,
        shots=scene_script.shots,
        speech_bindings=scene_script.speech_bindings,
    )

    # Calculate render settings
    vfov = _hfov_to_vfov(BASE_HFOV_DEGREES, target_ratio.ratio)

    render_settings = {
        "aspect_ratio": target_ratio.ratio_id,
        "resolution_width": target_ratio.width,
        "resolution_height": target_ratio.height,
        "orientation": target_ratio.orientation,
        "vertical_fov_degrees": round(vfov, 2),
        "horizontal_fov_degrees": BASE_HFOV_DEGREES,
        "camera_distance_multiplier": round(
            math.sqrt(base_ratio.ratio / target_ratio.ratio)
            if target_ratio.orientation == "portrait"
            else 1.0,
            3,
        ),
    }

    return adapted, render_settings


# ---------------------------------------------------------------------------
# Render resolution presets
# ---------------------------------------------------------------------------


def get_render_resolution(
    ratio_id: str,
    quality: str = "standard",
) -> tuple[int, int]:
    """Get render resolution for an aspect ratio and quality level.

    Args:
        ratio_id: Aspect ratio ID.
        quality: "preview" | "standard" | "high"

    Returns:
        Tuple of (width, height).
    """
    ratio = get_aspect_ratio(ratio_id)
    if ratio is None:
        return 960, 540  # default preview

    quality_scale = {
        "preview": 0.5,
        "standard": 1.0,
        "high": 1.5,
    }
    scale = quality_scale.get(quality, 1.0)
    return (
        int(ratio.width * scale),
        int(ratio.height * scale),
    )
