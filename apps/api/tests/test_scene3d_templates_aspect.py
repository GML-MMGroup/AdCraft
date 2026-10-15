"""Unit tests for shot_templates and aspect_ratios (P6)."""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.shot_templates import (
    SHOT_TEMPLATES,
    ShotTemplate,
    list_templates,
    get_template,
    generate_from_template,
    generate_dialogue_shot_reverse,
    generate_character_entrance,
    generate_establishing_shot,
)
from app.services.scene3d.aspect_ratios import (
    ASPECT_RATIOS,
    AspectRatio,
    get_aspect_ratio,
    list_aspect_ratios,
    adapt_camera_for_aspect,
    adapt_scene_script_for_aspect,
    get_render_resolution,
    _hfov_to_vfov,
)


# ---------------------------------------------------------------------------
# shot_templates tests
# ---------------------------------------------------------------------------


class TestShotTemplateCatalog:
    def test_templates_exist(self) -> None:
        assert len(SHOT_TEMPLATES) >= 3

    def test_all_templates_have_required_fields(self) -> None:
        for t in SHOT_TEMPLATES:
            assert isinstance(t, ShotTemplate)
            assert t.template_id
            assert t.name
            assert t.description
            assert t.category
            assert t.min_characters >= 0
            assert t.max_characters >= t.min_characters
            assert t.default_duration > 0

    def test_list_templates_all(self) -> None:
        all_templates = list_templates()
        assert len(all_templates) == len(SHOT_TEMPLATES)

    def test_list_templates_by_category(self) -> None:
        dialogue = list_templates("dialogue")
        assert len(dialogue) >= 1
        for t in dialogue:
            assert t.category == "dialogue"

    def test_get_template_found(self) -> None:
        t = get_template("dialogue_shot_reverse")
        assert t is not None
        assert t.template_id == "dialogue_shot_reverse"

    def test_get_template_not_found(self) -> None:
        assert get_template("nonexistent") is None


class TestDialogueTemplate:
    def test_generates_valid_scene_script(self) -> None:
        result = generate_dialogue_shot_reverse()
        assert isinstance(result, SceneScriptRoot)
        assert len(result.characters) == 2
        assert len(result.cameras) == 2
        assert len(result.shots) == 2

    def test_custom_names(self) -> None:
        result = generate_dialogue_shot_reverse(
            char1_name="hero", char2_name="villain", scene_name="confrontation"
        )
        assert result.scene.name == "confrontation"
        char_ids = [c.id for c in result.characters]
        assert "hero" in char_ids
        assert "villain" in char_ids

    def test_custom_duration(self) -> None:
        result = generate_dialogue_shot_reverse(duration=12.0, frame_rate=24)
        assert result.scene.duration == 12.0
        assert result.scene.frame_rate == 24
        assert result.total_frames == 288  # 12 * 24

    def test_shots_cover_full_range(self) -> None:
        result = generate_dialogue_shot_reverse(duration=8.0)
        assert result.shots[0].start_frame == 0
        assert result.shots[-1].end_frame == result.total_frames

    def test_cameras_are_over_shoulder(self) -> None:
        result = generate_dialogue_shot_reverse()
        for cam in result.cameras:
            assert cam.shot_type == "over_shoulder"


class TestEntranceTemplate:
    def test_generates_valid_scene_script(self) -> None:
        result = generate_character_entrance()
        assert isinstance(result, SceneScriptRoot)
        assert len(result.characters) == 1
        assert len(result.cameras) == 1
        assert len(result.shots) == 1

    def test_character_has_walk_action(self) -> None:
        result = generate_character_entrance()
        char = result.characters[0]
        actions = [kf.action for kf in char.keyframes]
        assert "walk" in actions

    def test_character_moves_forward(self) -> None:
        result = generate_character_entrance()
        char = result.characters[0]
        first_pos = char.keyframes[0].position
        last_pos = char.keyframes[-1].position
        # Character should move from background (more negative y) to foreground
        assert last_pos[1] > first_pos[1]

    def test_has_door_environment(self) -> None:
        result = generate_character_entrance()
        env_types = [e.type for e in result.environment]
        assert "door" in env_types


class TestEstablishingTemplate:
    def test_generates_valid_scene_script(self) -> None:
        result = generate_establishing_shot()
        assert isinstance(result, SceneScriptRoot)
        assert len(result.characters) == 0
        assert len(result.cameras) == 1
        assert len(result.shots) == 1

    def test_wide_shot(self) -> None:
        result = generate_establishing_shot()
        assert result.cameras[0].shot_type == "wide"

    def test_has_environment_objects(self) -> None:
        result = generate_establishing_shot()
        assert len(result.environment) >= 2  # wall + pillars


class TestGenerateFromTemplate:
    def test_dialogue_dispatch(self) -> None:
        result = generate_from_template("dialogue_shot_reverse")
        assert isinstance(result, SceneScriptRoot)
        assert len(result.characters) == 2

    def test_entrance_dispatch(self) -> None:
        result = generate_from_template("character_entrance")
        assert isinstance(result, SceneScriptRoot)
        assert len(result.characters) == 1

    def test_establishing_dispatch(self) -> None:
        result = generate_from_template("establishing_shot")
        assert isinstance(result, SceneScriptRoot)

    def test_unknown_template_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template"):
            generate_from_template("nonexistent_template")

    def test_passes_kwargs(self) -> None:
        result = generate_from_template(
            "dialogue_shot_reverse", scene_name="test-scene", duration=6.0
        )
        assert result.scene.name == "test-scene"
        assert result.scene.duration == 6.0


# ---------------------------------------------------------------------------
# aspect_ratios tests
# ---------------------------------------------------------------------------


class TestAspectRatioCatalog:
    def test_ratios_exist(self) -> None:
        assert len(ASPECT_RATIOS) >= 5

    def test_all_ratios_have_required_fields(self) -> None:
        for r in ASPECT_RATIOS:
            assert isinstance(r, AspectRatio)
            assert r.ratio_id
            assert r.name
            assert r.width > 0
            assert r.height > 0
            assert r.ratio > 0
            assert r.orientation in ("landscape", "portrait", "square")
            assert abs(r.ratio - r.width / r.height) < 0.01

    def test_get_ratio_found(self) -> None:
        r = get_aspect_ratio("16:9")
        assert r is not None
        assert r.ratio_id == "16:9"

    def test_get_ratio_not_found(self) -> None:
        assert get_aspect_ratio("99:99") is None

    def test_list_all(self) -> None:
        assert len(list_aspect_ratios()) == len(ASPECT_RATIOS)

    def test_list_by_orientation(self) -> None:
        portrait = list_aspect_ratios("portrait")
        assert len(portrait) >= 2
        for r in portrait:
            assert r.orientation == "portrait"

    def test_16_9_is_landscape(self) -> None:
        r = get_aspect_ratio("16:9")
        assert r.orientation == "landscape"
        assert r.ratio == pytest.approx(16 / 9, abs=0.01)

    def test_9_16_is_portrait(self) -> None:
        r = get_aspect_ratio("9:16")
        assert r.orientation == "portrait"
        assert r.ratio == pytest.approx(9 / 16, abs=0.01)

    def test_1_1_is_square(self) -> None:
        r = get_aspect_ratio("1:1")
        assert r.orientation == "square"
        assert r.ratio == 1.0


class TestFovConversion:
    def test_hfov_to_vfov_16_9(self) -> None:
        vfov = _hfov_to_vfov(60.0, 16 / 9)
        # For 16:9, 60deg hfov should give ~35deg vfov
        assert 30 < vfov < 40

    def test_hfov_to_vfov_9_16(self) -> None:
        vfov_16_9 = _hfov_to_vfov(60.0, 16 / 9)
        vfov_9_16 = _hfov_to_vfov(60.0, 9 / 16)
        # Portrait should have larger vfov for same hfov
        assert vfov_9_16 > vfov_16_9


class TestCameraAdaptation:
    def test_adapt_preserves_look_at(self) -> None:
        from app.schemas.scene_script import SceneCamera, CameraKeyframe
        cam = SceneCamera(
            id="cam1",
            shot_type="medium",
            keyframes=[
                CameraKeyframe(frame=0, position=[10, -10, 5], look_at=[0, 0, 1])
            ],
        )
        target = get_aspect_ratio("9:16")
        adapted = adapt_camera_for_aspect(cam, target)
        assert adapted.keyframes[0].look_at == [0, 0, 1]

    def test_portrait_moves_camera_back(self) -> None:
        from app.schemas.scene_script import SceneCamera, CameraKeyframe
        cam = SceneCamera(
            id="cam1",
            shot_type="wide",
            keyframes=[
                CameraKeyframe(frame=0, position=[10, -10, 5], look_at=[0, 0, 1])
            ],
        )
        target = get_aspect_ratio("9:16")
        adapted = adapt_camera_for_aspect(cam, target)
        # Distance from look_at should increase for portrait
        import math
        orig_dist = math.sqrt(sum((a - b) ** 2 for a, b in zip([10, -10, 5], [0, 0, 1])))
        new_dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(adapted.keyframes[0].position, [0, 0, 1])))
        assert new_dist > orig_dist

    def test_landscape_preserves_distance(self) -> None:
        from app.schemas.scene_script import SceneCamera, CameraKeyframe
        cam = SceneCamera(
            id="cam1",
            shot_type="wide",
            keyframes=[
                CameraKeyframe(frame=0, position=[10, -10, 5], look_at=[0, 0, 1])
            ],
        )
        target = get_aspect_ratio("16:9")
        adapted = adapt_camera_for_aspect(cam, target)
        # Same ratio should preserve distance (multiplier = 1.0)
        assert adapted.keyframes[0].position == [10, -10, 5]


class TestSceneScriptAdaptation:
    @pytest.fixture
    def sample_script(self) -> SceneScriptRoot:
        return generate_dialogue_shot_reverse()

    def test_adapt_returns_valid_script(self, sample_script: SceneScriptRoot) -> None:
        adapted, settings = adapt_scene_script_for_aspect(sample_script, "9:16")
        assert isinstance(adapted, SceneScriptRoot)
        assert len(adapted.cameras) == len(sample_script.cameras)
        assert len(adapted.shots) == len(sample_script.shots)
        assert len(adapted.characters) == len(sample_script.characters)

    def test_adapt_9_16_settings(self, sample_script: SceneScriptRoot) -> None:
        _, settings = adapt_scene_script_for_aspect(sample_script, "9:16")
        assert settings["aspect_ratio"] == "9:16"
        assert settings["orientation"] == "portrait"
        assert settings["resolution_width"] == 1080
        assert settings["resolution_height"] == 1920
        assert settings["camera_distance_multiplier"] > 1.0

    def test_adapt_1_1_settings(self, sample_script: SceneScriptRoot) -> None:
        _, settings = adapt_scene_script_for_aspect(sample_script, "1:1")
        assert settings["aspect_ratio"] == "1:1"
        assert settings["orientation"] == "square"
        assert settings["resolution_width"] == 1080
        assert settings["resolution_height"] == 1080

    def test_adapt_unknown_ratio_raises(self, sample_script: SceneScriptRoot) -> None:
        with pytest.raises(ValueError, match="Unknown aspect ratio"):
            adapt_scene_script_for_aspect(sample_script, "99:99")

    def test_adapt_preserves_shot_structure(self, sample_script: SceneScriptRoot) -> None:
        adapted, _ = adapt_scene_script_for_aspect(sample_script, "1:1")
        for orig_shot, new_shot in zip(sample_script.shots, adapted.shots):
            assert orig_shot.id == new_shot.id
            assert orig_shot.camera == new_shot.camera
            assert orig_shot.start_frame == new_shot.start_frame
            assert orig_shot.end_frame == new_shot.end_frame


class TestRenderResolution:
    def test_16_9_standard(self) -> None:
        w, h = get_render_resolution("16:9", "standard")
        assert w == 1920
        assert h == 1080

    def test_9_16_preview(self) -> None:
        w, h = get_render_resolution("9:16", "preview")
        assert w == 540  # 1080 * 0.5
        assert h == 960  # 1920 * 0.5

    def test_1_1_high(self) -> None:
        w, h = get_render_resolution("1:1", "high")
        assert w == 1620  # 1080 * 1.5
        assert h == 1620

    def test_unknown_ratio_defaults(self) -> None:
        w, h = get_render_resolution("unknown")
        assert w == 960
        assert h == 540
