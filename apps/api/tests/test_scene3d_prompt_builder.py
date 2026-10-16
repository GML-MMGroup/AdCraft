"""Unit tests for prompt_builder and reference_assets (P5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.prompt_builder import (
    ShotPrompt,
    VideoPromptBundle,
    build_shot_prompt,
    build_video_prompt_bundle,
    determine_reference_mode,
    keyframe_guidance_text,
    previs_control_level,
    _shot_type_language,
    _camera_movement_description,
    _character_action_language,
)
from app.services.scene3d.reference_assets import (
    VideoModelInput,
    build_video_model_input,
    format_reference_instructions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TWO_SHOT_SCENE = {
    "scene": {
        "name": "teahouse-dialogue",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 8.0,
        "frame_rate": 30,
    },
    "characters": [
        {
            "id": "scholar",
            "type": "lowpoly_human",
            "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
            "keyframes": [
                {"frame": 0, "position": [0.9, -0.9, 0], "rotation_y": 150, "action": "sit"},
                {"frame": 120, "position": [0.9, -0.9, 0], "rotation_y": -30, "action": "talk"},
            ],
        },
        {
            "id": "merchant",
            "type": "lowpoly_human",
            "appearance": {"color": "#4A90D9", "height": 1.65, "scale": 1.0},
            "keyframes": [
                {"frame": 0, "position": [-1.0, -2.6, 0], "rotation_y": -30, "action": "sit"},
                {"frame": 120, "position": [-1.0, -2.6, 0], "rotation_y": -30, "action": "sit"},
            ],
        },
    ],
    "props": [
        {"id": "table1", "type": "round_table", "position": [0, -1.6, 0], "scale": 1.0, "rotation_y": 0.0},
        {"id": "teapot", "type": "vase", "position": [0, -1.6, 0.8], "scale": 0.5, "rotation_y": 0.0},
    ],
    "environment": [
        {"id": "wall1", "type": "wall", "position": [0, -7, 2.5], "scale": 1.0, "rotation_y": 0.0},
    ],
    "cameras": [
        {
            "id": "wide_cam",
            "shot_type": "wide",
            "keyframes": [
                {"frame": 0, "position": [12, -14, 8], "look_at": [0, -1.5, 1.3]},
                {"frame": 119, "position": [8.5, -10, 6], "look_at": [0, -1.5, 1.3]},
            ],
        },
        {
            "id": "cu_cam",
            "shot_type": "closeup",
            "keyframes": [
                {"frame": 120, "position": [2.5, -4.0, 1.7], "look_at": [0.9, -0.9, 1.5]},
                {"frame": 239, "position": [1.8, -3.0, 1.6], "look_at": [0.9, -0.9, 1.5]},
            ],
        },
    ],
    "shots": [
        {"id": "shot1", "camera": "wide_cam", "start_frame": 0, "end_frame": 120, "description": "wide establishing shot of teahouse"},
        {"id": "shot2", "camera": "cu_cam", "start_frame": 120, "end_frame": 240, "description": "close-up on scholar speaking"},
    ],
    "speech_bindings": [],
}


@pytest.fixture
def two_shot_script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(TWO_SHOT_SCENE)


# ---------------------------------------------------------------------------
# prompt_builder tests
# ---------------------------------------------------------------------------


class TestShotTypeLanguage:
    def test_known_shot_types(self) -> None:
        assert "wide" in _shot_type_language("wide").lower()
        assert "close-up" in _shot_type_language("closeup").lower()
        assert "medium" in _shot_type_language("medium").lower()

    def test_unknown_shot_type_falls_back(self) -> None:
        result = _shot_type_language("dramatic_angle")
        assert "dramatic_angle" in result


class TestCameraMovement:
    def test_static_camera_single_keyframe(self) -> None:
        from app.schemas.scene_script import SceneCamera
        cam = SceneCamera(
            id="c1", shot_type="medium",
            keyframes=[{"frame": 0, "position": [5, -5, 3], "look_at": [0, 0, 1]}],
        )
        assert "static" in _camera_movement_description(cam).lower()

    def test_push_in_camera(self) -> None:
        from app.schemas.scene_script import SceneCamera
        cam = SceneCamera(
            id="c1", shot_type="medium",
            keyframes=[
                {"frame": 0, "position": [10, -10, 5], "look_at": [0, 0, 1]},
                {"frame": 100, "position": [10, -10, 1], "look_at": [0, 0, 1]},
            ],
        )
        desc = _camera_movement_description(cam).lower()
        assert "push" in desc or "dolli" in desc or "forward" in desc


class TestCharacterActionLanguage:
    def test_known_actions(self) -> None:
        assert "walking" in _character_action_language("walk")
        assert "speaking" in _character_action_language("talk")
        assert "sitting" in _character_action_language("sit")

    def test_none_action_defaults_to_idle(self) -> None:
        assert "idle" in _character_action_language(None).lower()

    def test_unknown_action_passthrough(self) -> None:
        assert "dancing" in _character_action_language("dancing")


class TestBuildShotPrompt:
    def test_returns_shot_prompt(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert isinstance(result, ShotPrompt)
        assert result.shot_id == "shot1"
        assert result.camera_id == "wide_cam"

    def test_prompt_contains_camera_language(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert "wide" in result.prompt.lower()
        assert "establishing" in result.prompt.lower()

    def test_prompt_contains_characters(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert "scholar" in result.prompt
        assert "merchant" in result.prompt

    def test_prompt_contains_environment(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert "interior" in result.prompt.lower() or "indoor" in result.prompt.lower()
        assert "warm" in result.prompt.lower()

    def test_prompt_contains_props(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert "round table" in result.prompt.lower()

    def test_closeup_shot_prompt(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[1]
        result = build_shot_prompt(two_shot_script, shot)
        assert "close-up" in result.prompt.lower()
        assert result.duration_seconds == pytest.approx(4.0, abs=0.01)

    def test_negative_prompt_present(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert len(result.negative_prompt) > 0
        assert "photorealistic" in result.negative_prompt

    def test_shot_description_included(self, two_shot_script: SceneScriptRoot) -> None:
        shot = two_shot_script.shots[0]
        result = build_shot_prompt(two_shot_script, shot)
        assert "teahouse" in result.prompt.lower()


class TestBuildVideoPromptBundle:
    def test_returns_bundle(self, two_shot_script: SceneScriptRoot) -> None:
        bundle = build_video_prompt_bundle(two_shot_script)
        assert isinstance(bundle, VideoPromptBundle)
        assert bundle.scene_name == "teahouse-dialogue"
        assert len(bundle.shots) == 2

    def test_global_prompt(self, two_shot_script: SceneScriptRoot) -> None:
        bundle = build_video_prompt_bundle(two_shot_script)
        assert "teahouse" in bundle.global_prompt.lower()
        assert "2 character" in bundle.global_prompt.lower()
        assert "2 shot" in bundle.global_prompt.lower()

    def test_total_frames(self, two_shot_script: SceneScriptRoot) -> None:
        bundle = build_video_prompt_bundle(two_shot_script)
        assert bundle.total_frames == 240  # 8s * 30fps

    def test_reference_mode_propagated(self, two_shot_script: SceneScriptRoot) -> None:
        bundle = build_video_prompt_bundle(two_shot_script, reference_mode="keyframes")
        assert bundle.reference_mode == "keyframes"
        for shot in bundle.shots:
            assert shot.reference_mode == "keyframes"


class TestDetermineReferenceMode:
    def test_video_supported(self) -> None:
        assert determine_reference_mode(True, True) == "video"

    def test_keyframes_fallback(self) -> None:
        assert determine_reference_mode(False, True) == "keyframes"

    def test_none_fallback(self) -> None:
        assert determine_reference_mode(False, False) == "none"

    def test_video_takes_precedence(self) -> None:
        assert determine_reference_mode(True, False) == "video"

    def test_control_signals_do_not_change_mode(self) -> None:
        # ADR 0005 §4: control passes add-on to reference video, not a new
        # reference mode; the level derives via previs_control_level.
        assert determine_reference_mode(True, True, True) == "video"
        assert determine_reference_mode(False, True, True) == "keyframes"


class TestPrevisControlLevel:
    """Mutation-check target: the §4a degradation marker must map a
    (reference_mode, control_signals) pair to exactly one known level, and
    unknown modes must fail closed to text_only."""

    def test_full_requires_video_and_signals(self) -> None:
        assert previs_control_level("video", True) == "full"

    def test_video_without_signals_degrades(self) -> None:
        assert previs_control_level("video", False) == "video_only"

    def test_keyframes_maps_to_images_only(self) -> None:
        assert previs_control_level("keyframes", True) == "images_only"
        assert previs_control_level("keyframes", False) == "images_only"

    def test_none_maps_to_text_only(self) -> None:
        assert previs_control_level("none", True) == "text_only"
        assert previs_control_level("none", False) == "text_only"

    def test_unknown_mode_fails_closed(self) -> None:
        assert previs_control_level("bogus", True) == "text_only"
        assert previs_control_level("", False) == "text_only"


class TestVideoModelInputLevel:
    def test_default_level_is_text_only(self) -> None:
        # A VideoModelInput with no reference assets reports its true level.
        model_input = build_video_model_input(
            SceneScriptRoot.model_validate(TWO_SHOT_SCENE),
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert model_input.previs_control_level == "text_only"

    def test_video_level_lifted_by_control_signals(self) -> None:
        model_input = build_video_model_input(
            SceneScriptRoot.model_validate(TWO_SHOT_SCENE),
            model_supports_reference_video=True,
            control_signals_available=True,
        )
        assert model_input.reference_mode == "video"
        assert model_input.previs_control_level == "full"

    def test_video_without_signals_is_video_only(self) -> None:
        model_input = build_video_model_input(
            SceneScriptRoot.model_validate(TWO_SHOT_SCENE),
            model_supports_reference_video=True,
        )
        assert model_input.previs_control_level == "video_only"


class TestKeyframeGuidanceText:
    def test_guidance_contains_5_frames(self, two_shot_script: SceneScriptRoot) -> None:
        bundle = build_video_prompt_bundle(two_shot_script)
        shot = bundle.shots[0]
        guidance = keyframe_guidance_text(shot)
        assert "0%" in guidance
        assert "25%" in guidance
        assert "50%" in guidance
        assert "75%" in guidance
        assert "100%" in guidance
        assert shot.shot_id in guidance


# ---------------------------------------------------------------------------
# reference_assets tests
# ---------------------------------------------------------------------------


class TestBuildVideoModelInput:
    def test_prompt_only_mode(self, two_shot_script: SceneScriptRoot) -> None:
        result = build_video_model_input(
            two_shot_script,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        assert isinstance(result, VideoModelInput)
        assert result.reference_mode == "none"
        assert result.reference_video is None
        assert len(result.keyframe_sets) == 0

    def test_video_mode_with_rendered_video(
        self, two_shot_script: SceneScriptRoot, tmp_path: Path
    ) -> None:
        video_path = tmp_path / "previs.mp4"
        video_path.write_bytes(b"fake mp4")

        result = build_video_model_input(
            two_shot_script,
            rendered_video_path=str(video_path),
            model_supports_reference_video=True,
        )
        assert result.reference_mode == "video"
        assert result.reference_video is not None
        assert result.reference_video.path == str(video_path)
        assert result.reference_video.duration_seconds == 8.0

    def test_video_mode_without_rendered_video_falls_back(
        self, two_shot_script: SceneScriptRoot
    ) -> None:
        result = build_video_model_input(
            two_shot_script,
            rendered_video_path=None,
            model_supports_reference_video=True,
        )
        # Mode is "video" but no actual video asset
        assert result.reference_mode == "video"
        assert result.reference_video is None

    def test_keyframes_mode_with_frames(
        self, two_shot_script: SceneScriptRoot, tmp_path: Path
    ) -> None:
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        # Create fake frames for 240 frames
        for f in range(1, 242):
            (frames_dir / f"frame_{f:04d}.png").write_bytes(b"\x89PNG")

        result = build_video_model_input(
            two_shot_script,
            rendered_frames_dir=str(frames_dir),
            keyframes_output_dir=str(tmp_path / "keyframes"),
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        assert result.reference_mode == "keyframes"
        assert len(result.keyframe_sets) == 2  # 2 shots
        for kf_set in result.keyframe_sets:
            assert len(kf_set.image_paths) == 5
            assert len(kf_set.guidance_text) > 0


class TestFormatReferenceInstructions:
    def test_prompt_only_format(self, two_shot_script: SceneScriptRoot) -> None:
        model_input = build_video_model_input(
            two_shot_script,
            model_supports_reference_video=False,
            model_supports_reference_images=False,
        )
        text = format_reference_instructions(model_input)
        assert "prompt-only" in text.lower()
        assert "teahouse" in text

    def test_video_format(
        self, two_shot_script: SceneScriptRoot, tmp_path: Path
    ) -> None:
        video_path = tmp_path / "previs.mp4"
        video_path.write_bytes(b"fake")
        model_input = build_video_model_input(
            two_shot_script,
            rendered_video_path=str(video_path),
            model_supports_reference_video=True,
        )
        text = format_reference_instructions(model_input)
        assert "REFERENCE VIDEO" in text
        assert "previs.mp4" in text

    def test_keyframes_format(
        self, two_shot_script: SceneScriptRoot, tmp_path: Path
    ) -> None:
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        for f in range(1, 242):
            (frames_dir / f"frame_{f:04d}.png").write_bytes(b"\x89PNG")

        model_input = build_video_model_input(
            two_shot_script,
            rendered_frames_dir=str(frames_dir),
            keyframes_output_dir=str(tmp_path / "kf"),
            model_supports_reference_video=False,
            model_supports_reference_images=True,
        )
        text = format_reference_instructions(model_input)
        assert "REFERENCE KEYFRAMES" in text
        assert "shot1" in text
        assert "shot2" in text
