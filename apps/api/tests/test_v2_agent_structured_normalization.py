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


def test_provider_duration_seconds_alias_maps_at_controls_path():
    result = norm(
        {
            "requirement_patch": {
                "controls_to_set": {
                    "target_duration_seconds": {"value": "60"}
                }
            }
        }
    )

    controls = result.value["requirement_patch"]["controls_to_set"]
    assert controls == {"duration_seconds": {"value": 60.0}}


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


def test_float_underscore_string_stays():
    value = {
        "requirement_patch": {
            "controls_to_set": {
                "duration_seconds": {"value": "1_0"},
                "frame_rate": {"value": "1_0"},
            }
        }
    }
    assert norm(value).value == value


def test_presence_aliases_have_exact_canonical_values():
    expected = {
        "include": "include",
        "included": "include",
        "present": "include",
        "required": "include",
        "\u5305\u542b": "include",
        "\u9700\u8981": "include",
        "\u5df2\u63d0\u53ca": "include",
        "exclude": "exclude",
        "excluded": "exclude",
        "absent": "exclude",
        "omit": "exclude",
        "\u6392\u9664": "exclude",
        "\u4e0d\u8981": "exclude",
        "\u4e0d\u9700\u8981": "exclude",
        "unspecified": "unspecified",
        "unknown": "unspecified",
        "not_mentioned": "unspecified",
        "not specified": "unspecified",
        "\u672a\u8bf4\u660e": "unspecified",
        "\u672a\u63d0\u53ca": "unspecified",
        "\u4e0d\u786e\u5b9a": "unspecified",
    }
    for alias, canonical in expected.items():
        result = norm({"explicit_elements": {"product": {"presence": alias, "source_quote": "x"}}})
        assert result.value["explicit_elements"]["product"]["presence"] == canonical


def test_canonical_input_is_idempotent_without_audit():
    value = {
        "explicit_elements": {
            "product": {"presence": "include", "source_quote": "x"}
        },
        "requirement_patch": {
            "controls_to_set": {"duration_seconds": {"value": 1.0}}
        },
    }
    result = norm(value)
    assert result.value == value
    assert result.normalized_path_count == 0
    assert result.rule_ids == ()


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
    result = norm(value)
    assert result.value["explicit_elements"]["product"]["presence"] == "unspecified"
    assert result.value["explicit_elements"]["product"]["source_quote"] == "x"
    assert result.value["explicit_elements"]["product"]["extra"] == 1
    assert result.value["extra_top"] == 2
    assert result.rule_ids == ("compact_turn_intent_v3.presence_safe_default.v1",)
    assert result.normalized_path_count == 1


def test_unrecognized_presence_scalars_safe_default_to_unspecified():
    result = norm(
        {
            "explicit_elements": {
                "product": {"presence": "model-specific"},
                "video": {"presence": True},
                "audio": {"presence": False},
            }
        }
    )
    elements = result.value["explicit_elements"]
    assert elements["product"]["presence"] == "unspecified"
    assert elements["video"]["presence"] == "unspecified"
    assert elements["audio"]["presence"] == "unspecified"
    assert result.rule_ids == ("compact_turn_intent_v3.presence_safe_default.v1",)
    assert result.normalized_path_count == 3


def test_nested_and_unregistered_presence_values_stay_untouched():
    value = {
        "explicit_elements": {
            "product": {"presence": {"enum": "mystery"}, "nested": {"presence": "mystery"}},
            "unregistered": {"presence": "mystery"},
        }
    }
    result = norm(value)
    assert result.value == value
    assert result.rule_ids == ()
    assert result.normalized_path_count == 0


def test_empty_presence_string_stays_untouched():
    value = {"explicit_elements": {"product": {"presence": ""}}}
    result = norm(value)
    assert result.value == value
    assert result.rule_ids == ()
    assert result.normalized_path_count == 0


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


def test_role_creative_brief_injects_missing_variant_from_trusted_context():
    value = {
        "identity": "A bottle",
        "geometry": "Tall",
        "materials": "Glass",
        "marks": "Logo",
        "palette": "Blue",
    }
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "RoleCreativeBriefV2",
        value,
        validation_context={"role_variant": "product_main"},
    )

    assert result.value["role_variant"] == "product_main"
    assert result.rule_ids == ("role_creative_brief_v2.role_variant_from_context.v1",)
    assert result.normalized_path_count == 1
    assert result.violations == ()


def test_role_creative_brief_expands_an_unambiguous_product_summary_alias():
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "RoleCreativeBriefV2",
        {
            "description": "透明可视化全流程名表质检维保服务，突出透明作业和专属检测报告。"
        },
        validation_context={"role_variant": "product_main"},
    )

    assert result.value == {
        "role_variant": "product_main",
        "identity": "透明可视化全流程名表质检维保服务，突出透明作业和专属检测报告。",
        "geometry": "Use only the product geometry explicitly described in the accepted direction: 透明可视化全流程名表质检维保服务，突出透明作业和专属检测报告。",
        "materials": "Use only the materials and finish explicitly described in the accepted direction: 透明可视化全流程名表质检维保服务，突出透明作业和专属检测报告。",
        "marks": "Use only the marks and certifications explicitly described in the accepted direction: 透明可视化全流程名表质检维保服务，突出透明作业和专属检测报告。",
        "palette": "Use only the palette explicitly described in the accepted direction: 透明可视化全流程名表质检维保服务，突出透明作业和专属检测报告。",
    }
    assert result.rule_ids == (
        "role_creative_brief_v2.role_variant_from_context.v1",
        "role_creative_brief_v2.product_main_summary_expansion.v1",
    )
    assert result.normalized_path_count == 7
    assert result.violations == ()


def test_role_creative_brief_rejects_conflicting_product_summary_aliases():
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "RoleCreativeBriefV2",
        {"description": "A", "concept_summary": "B"},
        validation_context={"role_variant": "product_main"},
    )

    assert [item.code for item in result.violations] == [
        "agent_structured_normalization_alias_conflict"
    ]


def test_role_creative_brief_expands_a_product_multiview_summary_alias():
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "RoleCreativeBriefV2",
        {"brief_content": "A transparent watch maintenance service presentation."},
        validation_context={"role_variant": "product_multiview"},
    )

    assert result.value["role_variant"] == "product_multiview"
    assert result.value["identity"] == "A transparent watch maintenance service presentation."
    assert result.value["views"] == ["front", "side", "back", "three-quarter", "detail"]
    assert result.rule_ids == (
        "role_creative_brief_v2.role_variant_from_context.v1",
        "role_creative_brief_v2.product_multiview_summary_expansion.v1",
    )
    assert result.normalized_path_count == 8
    assert result.violations == ()


def test_role_creative_brief_matching_variant_is_unchanged():
    value = {
        "role_variant": "product_main",
        "identity": "A bottle",
        "geometry": "Tall",
        "materials": "Glass",
        "marks": "Logo",
        "palette": "Blue",
    }
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "RoleCreativeBriefV2",
        value,
        validation_context={"role_variant": "product_main"},
    )

    assert result.value == value
    assert result.rule_ids == ()
    assert result.normalized_path_count == 0
    assert result.violations == ()


def test_role_creative_brief_conflicting_variant_is_rejected():
    value = {
        "role_variant": "product_multiview",
        "identity": "A bottle",
        "geometry": "Tall",
        "materials": "Glass",
        "marks": "Logo",
        "palette": "Blue",
        "views": ["front", "side", "back", "three-quarter", "detail"],
    }
    result = AGENT_STRUCTURED_NORMALIZATION_REGISTRY.normalize(
        "RoleCreativeBriefV2",
        value,
        validation_context={"role_variant": "product_main"},
    )

    assert result.value == value
    assert result.rule_ids == ()
    assert result.normalized_path_count == 0
    assert [item.code for item in result.violations] == [
        "agent_structured_normalization_role_variant_conflict"
    ]
