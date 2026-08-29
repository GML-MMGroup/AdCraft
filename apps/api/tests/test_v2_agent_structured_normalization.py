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


def test_alias_order_retains_canonical_key():
    for controls in (
        {"duration_sec": {"value": 1}, "duration_seconds": {"value": 1}},
        {"duration_seconds": {"value": 1}, "duration_sec": {"value": 1}},
    ):
        result = norm({"requirement_patch": {"controls_to_set": controls}})
        assert set(result.value["requirement_patch"]["controls_to_set"]) == {"duration_seconds"}


def test_unknown_fullwidth_key_stays_unchanged():
    value = {"requirement_patch": {"controls_to_set": {"ｘ": {"value": 1}}}}
    result = norm(value)
    assert result.value == value
    assert "compact_turn_intent_v3.field_aliases.v1" not in result.rule_ids


def test_fullwidth_registered_alias_key_maps():
    result = norm({"requirement_patch": {"controls_to_set": {"ｆｐｓ": {"value": "24"}}}})
    assert result.value["requirement_patch"]["controls_to_set"]["frame_rate"]["value"] == 24.0


def test_all_presence_aliases_map():
    aliases = ("include", "included", "present", "required", "\u5305\u542b", "\u9700\u8981", "\u5df2\u63d0\u53ca", "exclude", "excluded", "absent", "omit", "\u6392\u9664", "\u4e0d\u8981", "\u4e0d\u9700\u8981", "unspecified", "unknown", "not_mentioned", "not specified", "\u672a\u8bf4\u660e", "\u672a\u63d0\u53ca", "\u4e0d\u786e\u5b9a")
    for alias in aliases:
        result = norm({"explicit_elements": {"product": {"presence": alias, "source_quote": "x"}}})
        assert result.value["explicit_elements"]["product"]["presence"] in {"include", "exclude", "unspecified"}


def test_non_lossless_float_string_stays():
    value = {"requirement_patch": {"controls_to_set": {"duration_seconds": {"value": "\u7ea660\u79d2"}}}}
    assert norm(value).value == value


def test_normalized_path_count_counts_each_alias_path_once():
    fps = norm({"requirement_patch": {"controls_to_set": {"fps": {"value": "24"}}}})
    assert fps.normalized_path_count == 2
    resolution = norm({"requirement_patch": {"controls_to_set": {"resolution": {"value": "1080p"}}}})
    assert resolution.normalized_path_count == 1


def test_conflict_is_type_sensitive():
    result = norm({"requirement_patch": {"controls_to_set": {"duration_sec": {"value": True}, "duration_seconds": {"value": 1}}}})
    assert result.violations and result.violations[0].code == "agent_structured_normalization_alias_conflict"


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
