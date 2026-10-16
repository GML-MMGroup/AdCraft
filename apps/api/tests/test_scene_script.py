"""Unit tests for SceneScript schema and validators.

Covers:
- JSON parse/serialize round-trip
- Every validator with a mutation check (valid passes, mutated fails)
- Enum completeness
- Derived properties

Engineering standard §3: every validator has a mutation check that states
what it locks and mutates the input once to watch it go red.
"""

import json

import pytest
from pydantic import ValidationError

from app.schemas.scene_script import SceneScriptRoot

# ---------------------------------------------------------------------------
# Fixture: a complete valid SceneScript
# ---------------------------------------------------------------------------


def _valid_scene_script() -> dict:
    """A minimal but complete valid SceneScript for mutation testing."""
    return {
        "scene": {
            "name": "teahouse-dialogue",
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
                    {"frame": 0, "position": [0.9, -0.9, 0], "rotation_y": 150, "action": "stand"},
                    {"frame": 60, "position": [0.9, -0.9, 0], "rotation_y": -30, "action": "talk"},
                ],
            },
            {
                "id": "char2",
                "type": "lowpoly_human",
                "appearance": {"color": "#4A90D9", "height": 1.65},
                "keyframes": [
                    {"frame": 0, "position": [-1.0, -2.6, 0], "rotation_y": -30, "action": "sit"},
                ],
            },
        ],
        "props": [
            {"id": "table1", "type": "round_table", "position": [0, -1.6, 0], "scale": 1.0},
        ],
        "environment": [
            {"id": "wall1", "type": "wall", "position": [0, -7, 2.5]},
            {"id": "pillar1", "type": "pillar", "position": [-3.5, -6.7, 2.1]},
        ],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [
                    {"frame": 0, "position": [12, -14, 8], "look_at": [0, -1.5, 1.3]},
                    {"frame": 59, "position": [8.5, -10, 6], "look_at": [0, -1.5, 1.3]},
                ],
            },
            {
                "id": "cam2",
                "shot_type": "closeup",
                "keyframes": [
                    {"frame": 60, "position": [2.5, -4.0, 1.7], "look_at": [0.9, -0.9, 1.5]},
                    {"frame": 119, "position": [1.8, -3.0, 1.6], "look_at": [0.9, -0.9, 1.5]},
                ],
            },
        ],
        "shots": [
            {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 60, "description": "wide"},
            {"id": "shot2", "camera": "cam2", "start_frame": 60, "end_frame": 120, "description": "closeup"},
        ],
        "speech_bindings": [
            {"character": "char1", "speech_asset": "speech_audio:abc123", "mode": "bound"},
        ],
    }


@pytest.fixture
def valid_script() -> dict:
    return _valid_scene_script()


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_json_parse_serialize_parse(self, valid_script: dict) -> None:
        """JSON -> model -> JSON -> model produces equal results."""
        model1 = SceneScriptRoot.model_validate(valid_script)
        json_str = model1.model_dump_json()
        model2 = SceneScriptRoot.model_validate_json(json_str)
        assert model1 == model2

    def test_model_dump_contains_input(self, valid_script: dict) -> None:
        """model_dump() includes every input field (may add defaults)."""
        model = SceneScriptRoot.model_validate(valid_script)
        dumped = json.loads(model.model_dump_json())

        def _assert_subset(expected: object, actual: object, path: str = "") -> None:
            if isinstance(expected, dict):
                assert isinstance(actual, dict), f"{path}: expected dict"
                for k, v in expected.items():
                    assert k in actual, f"{path}.{k}: missing in dump"
                    _assert_subset(v, actual[k], f"{path}.{k}")
            elif isinstance(expected, list):
                assert isinstance(actual, list), f"{path}: expected list"
                assert len(actual) == len(expected), f"{path}: length mismatch"
                for i, (e, a) in enumerate(zip(expected, actual)):
                    _assert_subset(e, a, f"{path}[{i}]")
            else:
                assert actual == expected, f"{path}: {actual!r} != {expected!r}"

        _assert_subset(valid_script, dumped)

    def test_empty_collections_are_valid(self) -> None:
        """A scene with no characters/props/cameras/shots is valid."""
        data = {
            "scene": {"name": "empty", "environment": "outdoor", "lighting": "neutral", "duration": 1.0},
        }
        model = SceneScriptRoot.model_validate(data)
        assert model.characters == []
        assert model.shots == []
        assert model.total_frames == 30


# ---------------------------------------------------------------------------
# Derived properties
# ---------------------------------------------------------------------------


class TestDerivedProperties:
    def test_total_frames(self, valid_script: dict) -> None:
        model = SceneScriptRoot.model_validate(valid_script)
        assert model.total_frames == 120  # 4.0 * 30

    def test_total_frames_rounds_up(self) -> None:
        data = {
            "scene": {"name": "t", "environment": "indoor", "lighting": "warm", "duration": 1.5, "frame_rate": 24},
        }
        model = SceneScriptRoot.model_validate(data)
        assert model.total_frames == 36  # ceil(1.5 * 24) = ceil(36)

    def test_character_ids(self, valid_script: dict) -> None:
        model = SceneScriptRoot.model_validate(valid_script)
        assert model.character_ids == {"char1", "char2"}

    def test_camera_ids(self, valid_script: dict) -> None:
        model = SceneScriptRoot.model_validate(valid_script)
        assert model.camera_ids == {"cam1", "cam2"}


# ---------------------------------------------------------------------------
# Validator mutation checks
# ---------------------------------------------------------------------------


class TestPositionValidation:
    """Locks: position must have exactly 3 elements within ±100."""

    def test_valid_position_passes(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_wrong_length_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][0]["position"] = [1.0, 2.0]
        with pytest.raises(ValidationError, match="exactly 3 elements"):
            SceneScriptRoot.model_validate(valid_script)

    def test_mutation_out_of_range_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][0]["position"] = [150.0, 0, 0]
        with pytest.raises(ValidationError, match="outside realistic range"):
            SceneScriptRoot.model_validate(valid_script)

    def test_camera_look_at_wrong_length_fails(self, valid_script: dict) -> None:
        valid_script["cameras"][0]["keyframes"][0]["look_at"] = [0, 0]
        with pytest.raises(ValidationError, match="exactly 3 elements"):
            SceneScriptRoot.model_validate(valid_script)


class TestRotationYValidation:
    """Locks: rotation_y must be in degrees within ±360, not radians."""

    def test_valid_rotation_passes(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_radians_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][0]["rotation_y"] = 3.14
        with pytest.raises(ValidationError, match="appears to be in radians"):
            SceneScriptRoot.model_validate(valid_script)

    def test_mutation_exceeds_360_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][0]["rotation_y"] = 400.0
        with pytest.raises(ValidationError, match="exceeds .* degrees"):
            SceneScriptRoot.model_validate(valid_script)

    def test_zero_rotation_is_valid(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][0]["rotation_y"] = 0.0
        SceneScriptRoot.model_validate(valid_script)


class TestShotFrameRange:
    """Locks: end_frame must be > start_frame."""

    def test_valid_shot_passes(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_end_equals_start_fails(self, valid_script: dict) -> None:
        valid_script["shots"][0]["end_frame"] = 0
        with pytest.raises(ValidationError, match="end_frame .* must be >"):
            SceneScriptRoot.model_validate(valid_script)

    def test_mutation_end_less_than_start_fails(self, valid_script: dict) -> None:
        valid_script["shots"][0]["end_frame"] = -1
        with pytest.raises(ValidationError, match="end_frame .* must be >"):
            SceneScriptRoot.model_validate(valid_script)


class TestShotOverlap:
    """Locks: shot frame ranges must not overlap."""

    def test_non_overlapping_shots_pass(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_overlap_fails(self, valid_script: dict) -> None:
        # shot1 ends at 60, shot2 starts at 60 (touching is OK).
        # Make shot1 end at 80 to overlap with shot2.
        valid_script["shots"][0]["end_frame"] = 80
        with pytest.raises(ValidationError, match="shots overlap"):
            SceneScriptRoot.model_validate(valid_script)

    def test_touching_shots_are_valid(self, valid_script: dict) -> None:
        """shot1 end=60, shot2 start=60 is not an overlap."""
        SceneScriptRoot.model_validate(valid_script)


class TestShotExceedsTotalFrames:
    """Locks: shots must be within duration * frame_rate."""

    def test_shots_within_total_pass(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_exceeds_total_fails(self, valid_script: dict) -> None:
        valid_script["shots"][1]["end_frame"] = 200  # total is 120
        with pytest.raises(ValidationError, match="exceeds total frames"):
            SceneScriptRoot.model_validate(valid_script)


class TestCameraReferences:
    """Locks: every shot's camera must reference an existing camera."""

    def test_valid_references_pass(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_nonexistent_camera_fails(self, valid_script: dict) -> None:
        valid_script["shots"][0]["camera"] = "cam_nonexistent"
        with pytest.raises(ValidationError, match="references camera .* which does not exist"):
            SceneScriptRoot.model_validate(valid_script)


class TestSpeechBindingReferences:
    """Locks: every speech_binding character must reference an existing character."""

    def test_valid_binding_passes(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_nonexistent_character_fails(self, valid_script: dict) -> None:
        valid_script["speech_bindings"][0]["character"] = "char_nonexistent"
        with pytest.raises(ValidationError, match="references character .* which does not exist"):
            SceneScriptRoot.model_validate(valid_script)


class TestUniqueIds:
    """Locks: ids within each collection must be unique."""

    def test_unique_ids_pass(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_duplicate_character_id_fails(self, valid_script: dict) -> None:
        valid_script["characters"][1]["id"] = "char1"
        with pytest.raises(ValidationError, match="duplicate characters ids"):
            SceneScriptRoot.model_validate(valid_script)

    def test_mutation_duplicate_camera_id_fails(self, valid_script: dict) -> None:
        valid_script["cameras"][1]["id"] = "cam1"
        with pytest.raises(ValidationError, match="duplicate cameras ids"):
            SceneScriptRoot.model_validate(valid_script)

    def test_mutation_duplicate_shot_id_fails(self, valid_script: dict) -> None:
        valid_script["shots"][1]["id"] = "shot1"
        with pytest.raises(ValidationError, match="duplicate shots ids"):
            SceneScriptRoot.model_validate(valid_script)


class TestKeyframeBounds:
    """Locks: character and camera keyframes must be within total frames."""

    def test_keyframes_within_bounds_pass(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_character_keyframe_exceeds_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][1]["frame"] = 500  # total is 120
        with pytest.raises(ValidationError, match="character .* keyframe at frame 500 exceeds"):
            SceneScriptRoot.model_validate(valid_script)

    def test_mutation_camera_keyframe_exceeds_fails(self, valid_script: dict) -> None:
        valid_script["cameras"][0]["keyframes"][1]["frame"] = 500
        with pytest.raises(ValidationError, match="camera .* keyframe at frame 500 exceeds"):
            SceneScriptRoot.model_validate(valid_script)


class TestCameraKeyframesInShots:
    """Locks: camera keyframes should fall within at least one shot using that camera."""

    def test_keyframes_in_shots_pass(self, valid_script: dict) -> None:
        SceneScriptRoot.model_validate(valid_script)

    def test_mutation_keyframe_outside_all_shots_fails(self, valid_script: dict) -> None:
        # cam1 is used by shot1 (frames 0-60). Move its keyframe to frame 100.
        valid_script["cameras"][0]["keyframes"][1]["frame"] = 100
        with pytest.raises(ValidationError, match="keyframe at frame 100 is outside all shots"):
            SceneScriptRoot.model_validate(valid_script)

    def test_unused_camera_with_keyframes_is_valid(self, valid_script: dict) -> None:
        """A camera not referenced by any shot can have keyframes without error."""
        valid_script["cameras"].append(
            {"id": "cam_unused", "shot_type": "medium", "keyframes": [
                {"frame": 0, "position": [5, 5, 5], "look_at": [0, 0, 0]}
            ]}
        )
        SceneScriptRoot.model_validate(valid_script)


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


class TestEnumValidation:
    def test_invalid_shot_type_fails(self, valid_script: dict) -> None:
        valid_script["cameras"][0]["shot_type"] = "extreme_closeup"
        with pytest.raises(ValidationError):
            SceneScriptRoot.model_validate(valid_script)

    def test_invalid_action_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["keyframes"][0]["action"] = "dance"
        with pytest.raises(ValidationError):
            SceneScriptRoot.model_validate(valid_script)

    def test_invalid_speech_mode_fails(self, valid_script: dict) -> None:
        valid_script["speech_bindings"][0]["mode"] = "locked"
        with pytest.raises(ValidationError):
            SceneScriptRoot.model_validate(valid_script)

    def test_invalid_environment_kind_fails(self, valid_script: dict) -> None:
        valid_script["scene"]["environment"] = "space"
        with pytest.raises(ValidationError):
            SceneScriptRoot.model_validate(valid_script)


# ---------------------------------------------------------------------------
# Extra-forbid (no unexpected fields)
# ---------------------------------------------------------------------------


class TestExtraForbid:
    def test_unexpected_top_level_field_fails(self, valid_script: dict) -> None:
        valid_script["unknown_field"] = "oops"
        with pytest.raises(ValidationError):
            SceneScriptRoot.model_validate(valid_script)

    def test_unexpected_character_field_fails(self, valid_script: dict) -> None:
        valid_script["characters"][0]["unknown"] = "oops"
        with pytest.raises(ValidationError):
            SceneScriptRoot.model_validate(valid_script)
