"""Unit tests for SceneScript parser (LLM output -> SceneScriptRoot).

Covers:
- JSON extraction from markdown wrapping
- Valid/invalid JSON handling
- Schema validation error feedback
- retry_feedback generation
- Skill examples validity
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.parser import ParseResult, extract_json_text, parse_llm_output

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
            "appearance": {"color": "#8B4513"},
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
            "shot_type": "wide",
            "keyframes": [
                {"frame": 0, "position": [10, -10, 5], "look_at": [0, 0, 1]}
            ],
        }
    ],
    "shots": [
        {"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 120, "description": ""}
    ],
    "speech_bindings": [],
}


def _wrap_json(data: dict) -> str:
    return f"```json\n{json.dumps(data, indent=2)}\n```"


# ---------------------------------------------------------------------------
# extract_json_text
# ---------------------------------------------------------------------------


class TestExtractJsonText:
    def test_json_code_block(self) -> None:
        output = _wrap_json(VALID_SCENE_SCRIPT)
        result = extract_json_text(output)
        assert result is not None
        assert '"scene"' in result

    def test_generic_code_block(self) -> None:
        output = f"```\n{json.dumps(VALID_SCENE_SCRIPT)}\n```"
        result = extract_json_text(output)
        assert result is not None

    def test_bare_json_object(self) -> None:
        output = json.dumps(VALID_SCENE_SCRIPT)
        result = extract_json_text(output)
        assert result is not None

    def test_json_with_surrounding_text(self) -> None:
        output = f"Here is the scene script:\n\n{_wrap_json(VALID_SCENE_SCRIPT)}\n\nLet me know if you need changes."
        result = extract_json_text(output)
        assert result is not None

    def test_empty_output_returns_none(self) -> None:
        assert extract_json_text("") is None
        assert extract_json_text("   ") is None
        assert extract_json_text(None) is None  # type: ignore[arg-type]

    def test_no_json_returns_none(self) -> None:
        assert extract_json_text("This is just text with no JSON.") is None

    def test_code_block_without_scene_key_ignored(self) -> None:
        """A code block that doesn't contain 'scene' key should be skipped,
        but bare-object fallback should still find it if it has 'scene'."""
        output = '```json\n{"foo": "bar"}\n```'
        result = extract_json_text(output)
        # First pattern matches but no "scene" key, then bare fallback finds
        # the same block which also has no "scene" -> None
        assert result is None


# ---------------------------------------------------------------------------
# parse_llm_output - success
# ---------------------------------------------------------------------------


class TestParseSuccess:
    def test_valid_json_code_block(self) -> None:
        result = parse_llm_output(_wrap_json(VALID_SCENE_SCRIPT))
        assert result.success
        assert result.scene_script is not None
        assert isinstance(result.scene_script, SceneScriptRoot)
        assert result.scene_script.scene.name == "test-scene"
        assert result.error is None

    def test_valid_bare_json(self) -> None:
        result = parse_llm_output(json.dumps(VALID_SCENE_SCRIPT))
        assert result.success
        assert result.scene_script is not None

    def test_raw_json_preserved(self) -> None:
        result = parse_llm_output(_wrap_json(VALID_SCENE_SCRIPT))
        assert result.raw_json is not None
        assert '"scene"' in result.raw_json

    def test_retry_feedback_none_on_success(self) -> None:
        result = parse_llm_output(_wrap_json(VALID_SCENE_SCRIPT))
        assert result.retry_feedback is None


# ---------------------------------------------------------------------------
# parse_llm_output - failures
# ---------------------------------------------------------------------------


class TestParseFailure:
    def test_no_json_found(self) -> None:
        result = parse_llm_output("Just some text, no JSON here.")
        assert not result.success
        assert result.scene_script is None
        assert "No JSON object found" in (result.error or "")

    def test_invalid_json_syntax(self) -> None:
        bad_output = '```json\n{"scene": {"name": "broken",\n```'
        result = parse_llm_output(bad_output)
        assert not result.success
        assert "Invalid JSON" in (result.error or "")

    def test_schema_validation_failure(self) -> None:
        bad_data = copy.deepcopy(VALID_SCENE_SCRIPT)
        bad_data["shots"][0]["camera"] = "nonexistent_cam"
        result = parse_llm_output(_wrap_json(bad_data))
        assert not result.success
        assert "validation failed" in (result.error or "").lower()
        assert result.error_details is not None
        assert len(result.error_details) > 0

    def test_missing_scene_field(self) -> None:
        bad_data = {"characters": []}
        result = parse_llm_output(_wrap_json(bad_data))
        assert not result.success

    def test_retry_feedback_generated_on_failure(self) -> None:
        result = parse_llm_output("no json here")
        feedback = result.retry_feedback
        assert feedback is not None
        assert "SceneScript validation failed" in feedback
        assert "```json" in feedback

    def test_retry_feedback_includes_validation_details(self) -> None:
        bad_data = copy.deepcopy(VALID_SCENE_SCRIPT)
        bad_data["shots"][0]["camera"] = "missing_cam"
        result = parse_llm_output(_wrap_json(bad_data))
        feedback = result.retry_feedback
        assert feedback is not None
        assert "missing_cam" in feedback or "camera" in feedback.lower()


# ---------------------------------------------------------------------------
# Skill examples validity
# ---------------------------------------------------------------------------


class TestSkillExamples:
    """All skill examples must contain valid SceneScript."""

    EXAMPLES_DIR = Path(
        "agent/skills/video_agent_3d_storyboard/examples"
    )

    @pytest.fixture
    def example_files(self) -> list[Path]:
        if not self.EXAMPLES_DIR.exists():
            pytest.skip("examples directory not found")
        return sorted(self.EXAMPLES_DIR.glob("example_*.json"))

    def test_examples_exist(self, example_files: list[Path]) -> None:
        assert len(example_files) >= 2, "expected at least 2 skill examples"

    def test_each_example_has_required_fields(self, example_files: list[Path]) -> None:
        for path in example_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "title" in data, f"{path.name}: missing 'title'"
            assert "user_input" in data, f"{path.name}: missing 'user_input'"
            assert "expected_scene_script" in data, f"{path.name}: missing 'expected_scene_script'"

    def test_each_example_scene_script_is_valid(self, example_files: list[Path]) -> None:
        for path in example_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            scene_script = data["expected_scene_script"]
            try:
                model = SceneScriptRoot.model_validate(scene_script)
            except Exception as exc:
                pytest.fail(f"{path.name}: invalid SceneScript: {exc}")
            assert model.scene.name is not None
            assert model.total_frames > 0

    def test_each_example_parses_via_parser(self, example_files: list[Path]) -> None:
        for path in example_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            scene_script = data["expected_scene_script"]
            llm_output = _wrap_json(scene_script)
            result = parse_llm_output(llm_output)
            assert result.success, f"{path.name}: parser failed: {result.error}"


# ---------------------------------------------------------------------------
# ParseResult dataclass
# ---------------------------------------------------------------------------


class TestParseResult:
    def test_success_result_structure(self) -> None:
        result = ParseResult(success=True, scene_script=SceneScriptRoot.model_validate(VALID_SCENE_SCRIPT))
        assert result.success
        assert result.retry_feedback is None

    def test_failure_result_structure(self) -> None:
        result = ParseResult(success=False, error="test error", error_details=["detail1"])
        assert not result.success
        assert result.scene_script is None
        feedback = result.retry_feedback
        assert feedback is not None
        assert "test error" in feedback
        assert "detail1" in feedback
