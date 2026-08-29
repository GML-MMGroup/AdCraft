from copy import deepcopy

from app.services.v2_agent_structured_normalization import AGENT_STRUCTURED_NORMALIZATION_REGISTRY


def norm(value):
    return AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize("CompactTurnIntentDecisionV3", value)


def test_aliased_fields_and_presence_map():
    value = {"requirement_patch": {"controls_to_set": {"duration_sec": {"value": "12"}, "resolution": {"value": "1080p"}}}, "explicit_elements": {"product": {"presence": "包含", "source_quote": "x"}}}
    result = norm(value)
    controls = result.value["requirement_patch"]["controls_to_set"]
    assert controls["duration_seconds"]["value"] == 12.0
    assert controls["output_resolution"]["value"] == "1080p"
    assert result.value["explicit_elements"]["product"]["presence"] == "include"
    assert "compact_turn_intent_v3.field_aliases.v1" in result.rule_ids
    assert "compact_turn_intent_v3.presence_aliases.v1" in result.rule_ids


def test_all_key_aliases_and_nfkc():
    value = {"requirement_patch": {"controls_to_set": {"target_duration_sec": {"value": "1"}, "duration_sec": {"value": "1"}, "resolution": {"value": "x"}, "fps": {"value": "24"}}}}
    result = norm(value)
    controls = result.value["requirement_patch"]["controls_to_set"]
    assert set(controls) == {"duration_seconds", "output_resolution", "frame_rate"}
    assert controls["duration_seconds"]["value"] == 1.0


def test_conflict_rejects():
    result = norm({"requirement_patch": {"controls_to_set": {"duration_seconds": {"value": 1}, "duration_sec": {"value": 2}}}})
    assert result.violations and result.violations[0].code == "agent_structured_normalization_alias_conflict"
    assert "duration" in (result.violations[0].field_path or "")


def test_unknown_values_and_extra_stay():
    value = {"explicit_elements": {"product": {"presence": "mystery", "source_quote": "x", "extra": 1}}, "extra_top": 2}
    assert norm(value).value == value


def test_numeric_lossless_only():
    result = norm({"requirement_patch": {"controls_to_set": {"product_count": {"value": "3"}, "scene_count": {"value": "3.5"}}}})
    controls = result.value["requirement_patch"]["controls_to_set"]
    assert controls["product_count"]["value"] == 3
    assert controls["scene_count"]["value"] == "3.5"


def test_null_input_untouched_and_idempotent():
    value = {"explicit_elements": {"product": None}, "requirement_patch": {"controls_to_set": {"fps": None}}}
    original = deepcopy(value)
    first = norm(value)
    second = norm(first.value)
    assert value == original
    assert "product" not in first.value["explicit_elements"]
    assert "fps" not in first.value["requirement_patch"]["controls_to_set"]
    assert first.value == second.value
