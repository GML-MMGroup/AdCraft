"""Reference asset management for video model integration.

Manages the handoff of 3D previs render results (reference video or 5
keyframe images) to video generation models. Implements the ADR 0005 §4a
fallback strategy: models that support reference video get the rendered MP4;
models that don't get 5 keyframe images per shot; prompt-only as last resort.
The ADR 0005 §4a ``previs_control_level`` degradation marker is derived from
the effective reference mode + control-signal availability and is queryable
in execution results (never silent).

See: docs/adr/0005-3d-low-fidelity-previs.md
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.keyframes import extract_keyframes
from app.services.scene3d.prompt_builder import (
    VideoPromptBundle,
    determine_reference_mode,
    keyframe_guidance_text,
    previs_control_level,
)


@dataclass
class ReferenceVideoAsset:
    """A rendered previs video to use as reference for video generation."""

    path: str
    duration_seconds: float
    frame_count: int
    width: int = 960
    height: int = 540


@dataclass
class ReferenceKeyframeSet:
    """5 keyframe images for one shot (fallback reference mode)."""

    shot_id: str
    image_paths: list[str]  # 5 images at 0/25/50/75/100%
    guidance_text: str


@dataclass
class ControlSignals:
    """Per-render-job geometric control-signal bundle (ADR 0005 §4).

    Carries the queryable completeness marker and per-shot degradation
    markers produced by ``control_passes.collect_control_passes``; the
    per-shot file paths live in the matching ``ShotControlPasses`` and are
    exposed through ``per_shot`` for provider adapters that need to attach
    depth/normal/flow references to specific shots.
    """

    completeness: str
    degradation_markers: dict[str, list[str]]
    per_shot: dict[str, object] = field(default_factory=dict)


@dataclass
class VideoModelInput:
    """Complete input package for a video generation model.

    Contains the prompt bundle and reference assets in the format appropriate
    for the target model's capabilities.
    """

    prompt_bundle: VideoPromptBundle
    reference_mode: str  # "video" | "keyframes" | "none"
    reference_video: ReferenceVideoAsset | None = None
    keyframe_sets: list[ReferenceKeyframeSet] = field(default_factory=list)
    model_capabilities: dict[str, bool] = field(default_factory=dict)
    control_signals_available: bool = False
    control_signals: ControlSignals | None = None

    @property
    def previs_control_level(self) -> str:
        """ADR 0005 §4a degradation marker (queryable, never silent)."""
        return previs_control_level(
            self.reference_mode, self.control_signals_available
        )


def build_video_model_input(
    scene_script: SceneScriptRoot,
    rendered_video_path: str | None = None,
    rendered_frames_dir: str | None = None,
    keyframes_output_dir: str | None = None,
    model_supports_reference_video: bool = False,
    model_supports_reference_images: bool = True,
    control_signals_available: bool = False,
    control_signals: ControlSignals | None = None,
) -> VideoModelInput:
    """Build a complete video model input package.

    Args:
        scene_script: Validated SceneScript root.
        rendered_video_path: Path to rendered previs MP4 (for "video" mode).
        rendered_frames_dir: Directory containing rendered PNG frames (for
                             keyframe extraction in "keyframes" mode).
        keyframes_output_dir: Directory to copy keyframe images to.
        model_supports_reference_video: Whether the target model accepts
                                        reference video input.
        model_supports_reference_images: Whether the target model accepts
                                        reference image input.
        control_signals_available: Whether geometric control passes
                                    (depth/normal/flow, ADR 0005 §4) were
                                    produced and can be consumed. Does not
                                    change mode selection; it only lifts a
                                    "video" mode from "video_only" to "full".
        control_signals: Optional collected control-pass bundle carrying
                         per-shot file paths and queryable degradation
                         markers; when omitted, only the boolean
                         ``control_signals_available`` is surfaced.

    Returns:
        VideoModelInput with prompts and appropriate reference assets.
    """
    reference_mode = determine_reference_mode(
        model_supports_reference_video,
        model_supports_reference_images,
    )

    prompt_bundle = VideoPromptBundle(
        scene_name=scene_script.scene.name,
        total_duration=scene_script.scene.duration,
        total_frames=scene_script.total_frames,
        global_prompt="",
        global_negative_prompt="",
        shots=[],
        reference_mode=reference_mode,
    )
    # Build properly via the builder
    from app.services.scene3d.prompt_builder import build_video_prompt_bundle
    prompt_bundle = build_video_prompt_bundle(scene_script, reference_mode)

    model_input = VideoModelInput(
        prompt_bundle=prompt_bundle,
        reference_mode=reference_mode,
        model_capabilities={
            "supports_reference_video": model_supports_reference_video,
            "supports_reference_images": model_supports_reference_images,
            "control_signals_available": control_signals_available,
        },
        control_signals_available=control_signals_available,
        control_signals=control_signals,
    )

    if reference_mode == "video" and rendered_video_path and os.path.exists(rendered_video_path):
        model_input.reference_video = ReferenceVideoAsset(
            path=rendered_video_path,
            duration_seconds=scene_script.scene.duration,
            frame_count=scene_script.total_frames,
        )

    elif reference_mode == "keyframes" and rendered_frames_dir and os.path.isdir(rendered_frames_dir):
        output_dir = keyframes_output_dir or os.path.join(rendered_frames_dir, "keyframes")
        shot_keyframes = extract_keyframes(scene_script, rendered_frames_dir, output_dir)

        for skf in shot_keyframes:
            shot_prompt = next(
                (s for s in prompt_bundle.shots if s.shot_id == skf.shot_id),
                None,
            )
            guidance = keyframe_guidance_text(shot_prompt) if shot_prompt else ""

            model_input.keyframe_sets.append(
                ReferenceKeyframeSet(
                    shot_id=skf.shot_id,
                    image_paths=skf.files,
                    guidance_text=guidance,
                )
            )

    return model_input


def format_reference_instructions(model_input: VideoModelInput) -> str:
    """Format human-readable instructions for using reference assets.

    Useful for logging, debugging, and passing to agent skills that need
    to understand how to use the reference assets.
    """
    lines = [
        f"Video Model Input for: {model_input.prompt_bundle.scene_name}",
        f"Reference mode: {model_input.reference_mode}",
        f"Total duration: {model_input.prompt_bundle.total_duration:.1f}s",
        f"Shots: {len(model_input.prompt_bundle.shots)}",
        "",
    ]

    if model_input.reference_mode == "video" and model_input.reference_video:
        lines.append("REFERENCE VIDEO:")
        lines.append(f"  Path: {model_input.reference_video.path}")
        lines.append(f"  Duration: {model_input.reference_video.duration_seconds:.1f}s")
        lines.append(f"  Frames: {model_input.reference_video.frame_count}")
        lines.append("  Usage: Pass as reference video to the video generation model.")
    elif model_input.reference_mode == "keyframes":
        lines.append("REFERENCE KEYFRAMES (5 per shot, 0/25/50/75/100%):")
        for kf_set in model_input.keyframe_sets:
            lines.append(f"  Shot '{kf_set.shot_id}': {len(kf_set.image_paths)} images")
            for i, path in enumerate(kf_set.image_paths):
                lines.append(f"    [{i}] {path}")
        lines.append("")
        lines.append("  Usage: Pass these 5 images per shot as visual anchors.")
        lines.append("  The model should interpolate between keyframes for temporal consistency.")
    else:
        lines.append("No reference assets (prompt-only mode).")

    lines.append("")
    lines.append("GLOBAL PROMPT:")
    lines.append(f"  {model_input.prompt_bundle.global_prompt}")

    return "\n".join(lines)
