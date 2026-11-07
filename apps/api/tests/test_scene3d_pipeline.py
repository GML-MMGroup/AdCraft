"""Unit tests for blender_converter, encoder, and keyframes.

Renderer tests with real Blender are in test_scene3d_renderer_integration.py
and marked with @pytest.mark.integration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_converter import scene_script_to_blender
from app.services.scene3d.keyframes import (
    extract_keyframes,
    keyframe_manifest,
    _shot_keyframe_frames,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SCENE_SCRIPT = {
    "scene": {
        "name": "test-scene",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 4.0,
        "frame_rate": 30,
    },
    "characters": [
        {
            "id": "char1",
            "type": "lowpoly_human",
            "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
            "keyframes": [
                {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"},
                {"frame": 60, "position": [1, 0, 0], "rotation_y": 90, "action": "walk"},
            ],
        }
    ],
    "props": [
        {"id": "table1", "type": "round_table", "position": [0, -1, 0], "scale": 1.0, "rotation_y": 0.0}
    ],
    "environment": [
        {"id": "wall1", "type": "wall", "position": [0, -5, 0], "scale": 1.0, "rotation_y": 0.0}
    ],
    "cameras": [
        {
            "id": "cam1",
            "shot_type": "wide",
            "keyframes": [
                {"frame": 0, "position": [10, -10, 5], "look_at": [0, 0, 1]},
                {"frame": 119, "position": [8, -8, 4], "look_at": [0, 0, 1]},
            ],
        }
    ],
    "shots": [
        {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 120, "description": "wide shot"}
    ],
    "speech_bindings": [],
}


@pytest.fixture
def scene_script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(VALID_SCENE_SCRIPT)


# ---------------------------------------------------------------------------
# blender_converter
# ---------------------------------------------------------------------------


class TestBlenderConverter:
    def test_output_is_string(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert isinstance(script, str)
        assert len(script) > 100

    def test_contains_imports(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "import bpy" in script
        assert "import math" in script

    def test_contains_clean_scene(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "read_factory_settings" in script

    def test_contains_frame_settings(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "frame_start = 1" in script
        assert "frame_end = 120" in script
        assert "fps = 30" in script

    def test_contains_character(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "char1" in script
        assert "lowpoly" in script.lower() or "primitive_cube_add" in script

    def test_contains_character_keyframes(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "keyframe_insert" in script
        assert "frame=1" in script  # frame 0 + 1 (Blender 1-indexed)
        assert "frame=61" in script  # frame 60 + 1

    def test_contains_camera(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "cam1" in script
        assert "TRACK_TO" in script

    def test_contains_shot_markers(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "timeline_markers" in script
        assert "shot1" in script

    def test_contains_render_settings(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/tmp/render")
        # The converter pins EEVEE, not CYCLES: previs trades physical
        # accuracy for render speed (960x540 @24fps, one Blender process per
        # shot). Assert the engine that is actually used so a silent switch
        # to a slow renderer fails here rather than in production.
        assert "BLENDER_EEVEE" in script
        assert "PNG" in script
        assert "render.render(animation=True)" in script

    def test_output_dir_in_script(self, scene_script: SceneScriptRoot) -> None:
        script = scene_script_to_blender(scene_script, "/custom/output/dir")
        assert "/custom/output/dir" in script

    def test_deterministic_output(self, scene_script: SceneScriptRoot) -> None:
        """Same input should produce same output."""
        s1 = scene_script_to_blender(scene_script, "/tmp/render")
        s2 = scene_script_to_blender(scene_script, "/tmp/render")
        assert s1 == s2

    def test_known_asset_types_render(self, scene_script: SceneScriptRoot) -> None:
        """All schema-allowed prop types should render without error."""
        data = json.loads(json.dumps(VALID_SCENE_SCRIPT))
        for prop_type in ["round_table", "rect_table", "chair", "box", "lantern"]:
            data["props"] = [{"id": f"p_{prop_type}", "type": prop_type, "position": [0, 0, 0], "scale": 1.0, "rotation_y": 0.0}]
            ss = SceneScriptRoot.model_validate(data)
            script = scene_script_to_blender(ss, "/tmp/render")
            assert "import bpy" in script

    def test_empty_characters_props_environment(self) -> None:
        data = {
            "scene": {"name": "empty", "environment": "outdoor", "lighting": "neutral", "duration": 2.0, "frame_rate": 24},
            "characters": [],
            "props": [],
            "environment": [],
            "cameras": [
                {"id": "cam1", "shot_type": "medium", "keyframes": [
                    {"frame": 0, "position": [5, -5, 3], "look_at": [0, 0, 1]}
                ]}
            ],
            "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 48, "description": ""}],
            "speech_bindings": [],
        }
        ss = SceneScriptRoot.model_validate(data)
        script = scene_script_to_blender(ss, "/tmp/render")
        assert "import bpy" in script
        assert "cam1" in script

    def test_control_passes_flag_adds_depth_pass(self, scene_script: SceneScriptRoot) -> None:
        # Mutation: default converter output must NOT contain control-pass
        # lines; enabling the flag must add them (ADR 0005 §4).
        default_script = scene_script_to_blender(scene_script, "/tmp/render")
        assert "control_depth" not in default_script
        assert "ray_cast" not in default_script
        control_script = scene_script_to_blender(
            scene_script, "/tmp/render", include_control_passes=True
        )
        # Blender 5.x removed the compositor's Z/Normal/Vector pass sockets, so
        # the depth pass is sampled with the Cycles ray-cast API instead of a
        # CompositorNodeOutputFile node (verified against Blender 5.2.1 LTS).
        assert "control_depth" in control_script
        assert "scene.ray_cast" in control_script
        # Normal and flow degrade honestly rather than silently disappearing.
        assert "CONTROL PASS NORMAL: unavailable" in control_script
        assert "CONTROL PASS FLOW: unavailable" in control_script
        assert "control_depth" in control_script
        assert "control_normal" in control_script
        assert "control_flow" in control_script


# ---------------------------------------------------------------------------
# keyframes
# ---------------------------------------------------------------------------


class TestShotKeyframeFrames:
    """``end_frame`` is exclusive, so 100% samples the frame ``end_frame - 1``.

    A shot spanning 0..30 at 30fps is the 30 frames Blender renders for a 1s
    scene (SceneScript frames 0-29); sampling 30 would name a frame that was
    never written and silently drop the shot to 4 keyframes.
    """

    def test_five_frames_for_normal_shot(self) -> None:
        from app.schemas.scene_script import SceneShot
        shot = SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=100, description="")
        frames = _shot_keyframe_frames(shot)
        assert len(frames) == 5
        assert frames[0] == 0
        assert frames[-1] == 99
        assert frames[2] == 50  # midpoint

    def test_percentages_are_0_25_50_75_100(self) -> None:
        from app.schemas.scene_script import SceneShot
        shot = SceneShot(id="s1", camera="cam1", start_frame=10, end_frame=90, description="")
        frames = _shot_keyframe_frames(shot)
        assert frames == [10, 30, 50, 69, 89]

    def test_minimal_shot(self) -> None:
        from app.schemas.scene_script import SceneShot
        shot = SceneShot(id="s1", camera="cam1", start_frame=5, end_frame=6, description="")
        frames = _shot_keyframe_frames(shot)
        assert len(frames) >= 1
        assert frames[0] == 5
        assert frames[-1] == 5

    def test_two_frame_shot_dedupes(self) -> None:
        from app.schemas.scene_script import SceneShot
        shot = SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=1, description="")
        frames = _shot_keyframe_frames(shot)
        assert len(frames) <= 2
        assert frames[0] == 0
        assert frames[-1] == 0


class TestKeyframeManifest:
    def test_manifest_structure(self, scene_script: SceneScriptRoot) -> None:
        manifest = keyframe_manifest(scene_script)
        assert "shot1" in manifest
        assert len(manifest["shot1"]) == 5
        assert manifest["shot1"][0]["percentage"] == 0.0
        assert manifest["shot1"][-1]["percentage"] == 100.0

    def test_manifest_frame_values(self, scene_script: SceneScriptRoot) -> None:
        manifest = keyframe_manifest(scene_script)
        frames = [entry["frame"] for entry in manifest["shot1"]]
        assert frames == [0, 30, 60, 89, 119]


class TestExtractKeyframes:
    def test_extracts_from_fake_frames(self, scene_script: SceneScriptRoot, tmp_path: Path) -> None:
        """Create fake PNG frames and verify keyframe extraction copies them."""
        frames_dir = tmp_path / "frames"
        output_dir = tmp_path / "keyframes"
        frames_dir.mkdir()

        # Create fake frame files (Blender 1-indexed: frame_0001 = SceneScript frame 0)
        for f in range(1, 122):
            (frames_dir / f"frame_{f:04d}.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        results = extract_keyframes(scene_script, str(frames_dir), str(output_dir))
        assert len(results) == 1
        assert results[0].shot_id == "shot1"
        assert len(results[0].files) == 5
        for f in results[0].files:
            assert Path(f).exists()

    def test_missing_frames_skipped(self, scene_script: SceneScriptRoot, tmp_path: Path) -> None:
        frames_dir = tmp_path / "frames"
        output_dir = tmp_path / "keyframes"
        frames_dir.mkdir()
        # Only create first frame
        (frames_dir / "frame_0001.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        results = extract_keyframes(scene_script, str(frames_dir), str(output_dir))
        assert len(results[0].files) == 1  # only first keyframe found

    def test_empty_frames_dir(self, scene_script: SceneScriptRoot, tmp_path: Path) -> None:
        frames_dir = tmp_path / "frames"
        output_dir = tmp_path / "keyframes"
        frames_dir.mkdir()

        results = extract_keyframes(scene_script, str(frames_dir), str(output_dir))
        assert len(results) == 1
        assert len(results[0].files) == 0
