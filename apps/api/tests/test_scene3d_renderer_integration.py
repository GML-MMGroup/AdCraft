"""Integration tests for Blender renderer with real Blender execution.

These tests require Blender to be installed and available. They are marked
with @pytest.mark.integration and are skipped by default unless Blender is
detected.

Run with: pytest tests/test_scene3d_renderer_integration.py -m integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_renderer import (
    get_blender_capability,
    render_scene_script,
    reset_capability_cache,
)
from app.services.scene3d.encoder import encode_png_sequence
from app.services.scene3d.keyframes import extract_keyframes


# Blender executable path (override with BLENDER_EXECUTABLE env var)
BLENDER_EXE = os.environ.get("BLENDER_EXECUTABLE", r"D:\Blender\blender.exe")


def _blender_available() -> bool:
    """Check if Blender is available for integration tests."""
    if os.path.exists(BLENDER_EXE):
        return True
    # Also check PATH
    import shutil
    return shutil.which("blender") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _blender_available(),
        reason="Blender not available for integration tests",
    ),
]


SIMPLE_SCENE = {
    "scene": {
        "name": "integration-test",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 1.0,  # 1 second = 30 frames (fast render)
        "frame_rate": 30,
    },
    "characters": [
        {
            "id": "char1",
            "type": "lowpoly_human",
            "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
            "keyframes": [
                {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
            ],
        }
    ],
    "props": [],
    "environment": [],
    "cameras": [
        {
            "id": "cam1",
            "shot_type": "medium",
            "keyframes": [
                {"frame": 0, "position": [5, -5, 3], "look_at": [0, 0, 1]}
            ],
        }
    ],
    "shots": [
        {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 30, "description": "test"}
    ],
    "speech_bindings": [],
}


class TestBlenderCapability:
    def test_capability_probe(self) -> None:
        reset_capability_cache()
        cap = get_blender_capability(BLENDER_EXE)
        assert cap.state in ("ready", "degraded")
        assert cap.version is not None or cap.state == "degraded"


class TestRenderSceneScript:
    def test_renders_png_frames(self, tmp_path: Path) -> None:
        scene_script = SceneScriptRoot.model_validate(SIMPLE_SCENE)
        output_dir = tmp_path / "frames"
        output_dir.mkdir()

        result = render_scene_script(
            scene_script,
            str(output_dir),
            executable=BLENDER_EXE,
            timeout_seconds=300,
        )

        assert result.success, f"Render failed: {result.error}"
        assert result.frame_count > 0
        assert result.output_dir is not None

        # Verify actual PNG files exist
        frame_files = list(Path(result.output_dir).glob("frame_*.png"))
        assert len(frame_files) > 0
        for f in frame_files[:3]:
            assert f.stat().st_size > 0

    def test_render_duration_tracking(self, tmp_path: Path) -> None:
        scene_script = SceneScriptRoot.model_validate(SIMPLE_SCENE)
        output_dir = tmp_path / "frames2"
        output_dir.mkdir()

        result = render_scene_script(
            scene_script,
            str(output_dir),
            executable=BLENDER_EXE,
            timeout_seconds=300,
        )

        assert result.success
        assert result.duration_seconds > 0


class TestEncodePngSequence:
    def test_encode_to_mp4(self, tmp_path: Path) -> None:
        # First render
        scene_script = SceneScriptRoot.model_validate(SIMPLE_SCENE)
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        render_result = render_scene_script(
            scene_script,
            str(frames_dir),
            executable=BLENDER_EXE,
            timeout_seconds=300,
        )
        assert render_result.success

        # Then encode
        output_path = str(tmp_path / "output.mp4")
        encode_result = encode_png_sequence(
            str(frames_dir),
            output_path,
            fps=30,
        )

        # ffmpeg may not be available in all environments
        if encode_result.success:
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
        else:
            pytest.skip(f"ffmpeg not available: {encode_result.error}")


class TestRenderControlPasses:
    """Real-binary check that Blender actually emits depth/normal/flow files.

    Verifies the on-disk layout that ``control_passes.collect_control_passes``
    expects (sibling ``control_depth`` / ``control_normal`` / ``control_flow``
    subdirectories under the frames dir), against a real Cycles render.
    """

    def test_control_pass_directories_populated(self, tmp_path: Path) -> None:
        from app.services.scene3d.control_passes import collect_control_passes

        scene_script = SceneScriptRoot.model_validate(SIMPLE_SCENE)
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        result = render_scene_script(
            scene_script,
            str(frames_dir),
            executable=BLENDER_EXE,
            timeout_seconds=600,
            include_control_passes=True,
        )
        assert result.success, f"Render failed: {result.error}"

        # Color pass still lands in the frames dir (untouched layout).
        assert list(frames_dir.glob("frame_*.png")), "color pass frames missing"

        # Blender 5.x removed the compositor's Z/Normal/Vector pass sockets
        # (verified on 5.2.1 LTS), so depth is the one geometric signal that
        # can actually be produced. Assert depth is populated AND that the
        # missing normal/flow passes surface as queryable degradation rather
        # than a silent omission (ADR 0005 §4: queryable, never silent).
        depth_dir = frames_dir / "control_depth"
        assert depth_dir.is_dir(), "control_depth dir missing"
        depth_files = [p for p in depth_dir.iterdir() if p.is_file()]
        assert depth_files, "control_depth has no output files"

        # The passes Blender 5.x cannot produce still get their directory, so
        # a future Blender version regains them without a layout change.
        for pass_name in ("normal", "flow"):
            pass_dir = frames_dir / f"control_{pass_name}"
            assert pass_dir.is_dir(), f"control_{pass_name} dir missing"

        # Collection must align depth files to the shot's 5 keyframe frames.
        collected = collect_control_passes(scene_script, str(frames_dir))
        assert len(collected.shots[0].depth_files) == 5
        assert collected.completeness == "partial"
        assert collected.degradation_markers == {"shot1": ["normal", "flow"]}


class TestExtractKeyframesFromRender:
    def test_extracts_5_keyframes(self, tmp_path: Path) -> None:
        scene_script = SceneScriptRoot.model_validate(SIMPLE_SCENE)
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        render_result = render_scene_script(
            scene_script,
            str(frames_dir),
            executable=BLENDER_EXE,
            timeout_seconds=300,
        )
        assert render_result.success

        keyframes_dir = tmp_path / "keyframes"
        results = extract_keyframes(scene_script, str(frames_dir), str(keyframes_dir))

        assert len(results) == 1
        assert results[0].shot_id == "shot1"
        # 30-frame shot should yield 5 keyframes
        assert len(results[0].files) == 5
        for f in results[0].files:
            assert Path(f).exists()
            assert Path(f).stat().st_size > 0
