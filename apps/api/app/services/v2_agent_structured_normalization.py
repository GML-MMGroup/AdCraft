"""Closed, contract-local normalization for structured Agent submissions."""

from __future__ import annotations

from copy import deepcopy
import math
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from app.schemas.agent_runtime import StructuredViolation


DECISION_BUNDLE_CAPABILITY_ALIAS_RULE_ID = (
    "decision_bundle.creative_directive.capability_ids_alias.v1"
)
COMPACT_TURN_INTENT_OMITTABLE_NULLS_RULE_ID = "compact_turn_intent_v3.omittable_nulls.v1"
COMPACT_TURN_INTENT_FIELD_ALIASES_RULE_ID = "compact_turn_intent_v3.field_aliases.v1"
COMPACT_TURN_INTENT_PRESENCE_ALIASES_RULE_ID = "compact_turn_intent_v3.presence_aliases.v1"
COMPACT_TURN_INTENT_PRESENCE_SAFE_DEFAULT_RULE_ID = "compact_turn_intent_v3.presence_safe_default.v1"
COMPACT_TURN_INTENT_LOSSLESS_SCALARS_RULE_ID = "compact_turn_intent_v3.lossless_scalars.v1"

_INTAKE_ELEMENT_NAMES = (
    "product",
    "prop",
    "character",
    "scene",
    "world_setting",
    "script",
    "storyboard",
    "video",
    "audio",
)
_INTAKE_CONTROL_NAMES = (
    "duration_seconds",
    "aspect_ratio",
    "output_resolution",
    "frame_rate",
    "spoken_language",
    "audio_mode",
    "product_count",
    "prop_count",
    "character_count",
    "scene_count",
    "storyboard_sequence_count",
    "video_segment_count",
)


@dataclass(frozen=True, slots=True)
class AgentStructuredNormalizationResult:
    """One copied candidate and bounded evidence from registered normalization."""

    value: dict[str, Any]
    rule_ids: tuple[str, ...] = ()
    normalized_path_count: int = 0
    violations: tuple[StructuredViolation, ...] = ()


NormalizationRule = Callable[[dict[str, Any], Mapping[str, Any]], AgentStructuredNormalizationResult]
_NORMALIZATION_RULES: Mapping[str, NormalizationRule]


class AgentStructuredNormalizationRegistry:
    """Apply only exact normalization rules owned by one registered contract."""

    def normalize(
        self,
        contract_name: str,
        value: dict[str, Any],
        *,
        validation_context: Mapping[str, Any] | None = None,
    ) -> AgentStructuredNormalizationResult:
        rule = _NORMALIZATION_RULES.get(contract_name)
        if rule is None:
            return AgentStructuredNormalizationResult(value=deepcopy(value))
        return rule(value, validation_context or {})


def _normalize_decision_bundle_capability_alias(
    value: dict[str, Any],
    _validation_context: Mapping[str, Any],
) -> AgentStructuredNormalizationResult:
    candidate = deepcopy(value)
    effects = tuple(_creative_directive_effects(candidate))
    for path, effect in effects:
        if "capacity_ids" in effect and "capability_ids" in effect:
            return AgentStructuredNormalizationResult(
                value=deepcopy(value),
                violations=(
                    StructuredViolation(
                        code="agent_structured_normalization_alias_conflict",
                        message=(
                            "The structured result contains both the registered alias "
                            "and canonical field."
                        ),
                        field_path=path,
                    ),
                ),
            )

    normalized_path_count = 0
    for _, effect in effects:
        if "capacity_ids" not in effect:
            continue
        effect["capability_ids"] = effect.pop("capacity_ids")
        normalized_path_count += 1

    return AgentStructuredNormalizationResult(
        value=candidate,
        rule_ids=((DECISION_BUNDLE_CAPABILITY_ALIAS_RULE_ID,) if normalized_path_count else ()),
        normalized_path_count=normalized_path_count,
    )


def _normalize_compact_turn_intent_omittable_nulls(
    value: dict[str, Any],
    _validation_context: Mapping[str, Any],
) -> AgentStructuredNormalizationResult:
    candidate = deepcopy(value)
    normalized_path_count = 0

    normalized_path_count += _remove_null_property(candidate, "explicit_elements")
    explicit_elements = candidate.get("explicit_elements")
    if isinstance(explicit_elements, dict):
        normalized_path_count += sum(
            _remove_null_property(explicit_elements, element_name)
            for element_name in _INTAKE_ELEMENT_NAMES
        )

    requirement_patch = candidate.get("requirement_patch")
    if isinstance(requirement_patch, dict):
        normalized_path_count += _remove_null_property(
            requirement_patch,
            "controls_to_set",
        )
        controls = requirement_patch.get("controls_to_set")
        if isinstance(controls, dict):
            normalized_path_count += sum(
                _remove_null_property(controls, control_name)
                for control_name in _INTAKE_CONTROL_NAMES
            )

        normalized_path_count += _remove_null_property(
            requirement_patch,
            "directives_to_add",
        )
        directives = requirement_patch.get("directives_to_add")
        if isinstance(directives, list):
            normalized_path_count += sum(
                _remove_null_property(directive, "capability_id")
                for directive in directives
                if isinstance(directive, dict) and directive.get("scope_kind") == "global"
            )

    return AgentStructuredNormalizationResult(
        value=candidate,
        rule_ids=((COMPACT_TURN_INTENT_OMITTABLE_NULLS_RULE_ID,) if normalized_path_count else ()),
        normalized_path_count=normalized_path_count,
    )


def _normalize_compact_turn_intent(
    value: dict[str, Any],
    validation_context: Mapping[str, Any],
) -> AgentStructuredNormalizationResult:
    candidate = deepcopy(value)
    rule_ids: list[str] = []
    count = 0
    violations: list[StructuredViolation] = []

    changed, conflict = _normalize_control_aliases(candidate)
    count += changed
    if changed:
        rule_ids.append(COMPACT_TURN_INTENT_FIELD_ALIASES_RULE_ID)
    if conflict:
        violations.append(conflict)
        return AgentStructuredNormalizationResult(value=deepcopy(value), violations=tuple(violations))

    changed = _normalize_presence_aliases(candidate)
    count += changed
    if changed:
        rule_ids.append(COMPACT_TURN_INTENT_PRESENCE_ALIASES_RULE_ID)
    changed = _normalize_presence_safe_defaults(candidate)
    count += changed
    if changed:
        rule_ids.append(COMPACT_TURN_INTENT_PRESENCE_SAFE_DEFAULT_RULE_ID)
    changed = _normalize_lossless_scalars(candidate)
    count += changed
    if changed:
        rule_ids.append(COMPACT_TURN_INTENT_LOSSLESS_SCALARS_RULE_ID)

    null_result = _normalize_compact_turn_intent_omittable_nulls(candidate, validation_context)
    candidate = null_result.value
    count += null_result.normalized_path_count
    rule_ids.extend(null_result.rule_ids)
    return AgentStructuredNormalizationResult(value=candidate, rule_ids=tuple(rule_ids), normalized_path_count=count)


ROLE_CREATIVE_BRIEF_ROLE_VARIANT_RULE_ID = (
    "role_creative_brief_v2.role_variant_from_context.v1"
)
ROLE_CREATIVE_BRIEF_PRODUCT_MAIN_SUMMARY_EXPANSION_RULE_ID = (
    "role_creative_brief_v2.product_main_summary_expansion.v1"
)
ROLE_CREATIVE_BRIEF_PRODUCT_MULTIVIEW_SUMMARY_EXPANSION_RULE_ID = (
    "role_creative_brief_v2.product_multiview_summary_expansion.v1"
)
ROLE_CREATIVE_BRIEF_PROP_SUMMARY_EXPANSION_RULE_ID = (
    "role_creative_brief_v2.prop_summary_expansion.v1"
)
ROLE_CREATIVE_BRIEF_CHARACTER_MAIN_SUMMARY_EXPANSION_RULE_ID = (
    "role_creative_brief_v2.character_main_summary_expansion.v1"
)
_PRODUCT_MAIN_SUMMARY_ALIASES = (
    "description",
    "brief_content",
    "concept_summary",
)
_PRODUCT_MAIN_REQUIRED_FIELDS = (
    "identity",
    "geometry",
    "materials",
    "marks",
    "palette",
)
_ROLE_VARIANT_VALUES = frozenset(
    {
        "world_view",
        "product_main",
        "product_multiview",
        "prop",
        "character_main",
        "character_turnaround",
        "scene_board",
        "script",
        "storyboard_grid",
        "video_segment",
        "bgm",
        "free_text",
        "free_image",
        "free_video",
        "free_audio",
    }
)


def _normalize_role_creative_brief(
    value: dict[str, Any],
    validation_context: Mapping[str, Any],
) -> AgentStructuredNormalizationResult:
    """Apply only contract-owned, trusted-context role brief compatibility rules."""

    expected_variant = validation_context.get("role_variant")
    if expected_variant not in _ROLE_VARIANT_VALUES:
        return AgentStructuredNormalizationResult(value=deepcopy(value))

    supplied = value.get("role_variant")
    candidate = deepcopy(value)
    rule_ids: list[str] = []
    normalized_path_count = 0
    if "role_variant" not in value:
        candidate["role_variant"] = expected_variant
        rule_ids.append(ROLE_CREATIVE_BRIEF_ROLE_VARIANT_RULE_ID)
        normalized_path_count += 1
    elif supplied != expected_variant:
        return AgentStructuredNormalizationResult(
            value=deepcopy(value),
            violations=(
                StructuredViolation(
                    code="agent_structured_normalization_role_variant_conflict",
                    message="The structured role brief role_variant conflicts with trusted context.",
                    field_path="role_variant",
                ),
            ),
        )

    if expected_variant in {"product_main", "product_multiview"}:
        expansion = _expand_product_main_summary(candidate)
        if expansion.violations:
            return AgentStructuredNormalizationResult(
                value=deepcopy(value),
                violations=expansion.violations,
            )
        candidate = expansion.value
        if expansion.normalized_path_count:
            expansion_path_count = expansion.normalized_path_count
            if expected_variant == "product_multiview" and "views" not in candidate:
                candidate["views"] = ["front", "side", "back", "three-quarter", "detail"]
                expansion_path_count += 1
            rule_ids.append(
                (
                    ROLE_CREATIVE_BRIEF_PRODUCT_MULTIVIEW_SUMMARY_EXPANSION_RULE_ID
                    if expected_variant == "product_multiview"
                    else ROLE_CREATIVE_BRIEF_PRODUCT_MAIN_SUMMARY_EXPANSION_RULE_ID
                )
            )
            normalized_path_count += expansion_path_count

    if expected_variant == "prop":
        expansion = _expand_role_summary(
            candidate,
            {
                "identity": "{summary}",
                "form": "Use only the prop form explicitly described in the accepted direction: {summary}",
                "materials": "Use only the prop materials explicitly described in the accepted direction: {summary}",
                "palette": "Use only the prop palette explicitly described in the accepted direction: {summary}",
            },
        )
        if expansion.violations:
            return AgentStructuredNormalizationResult(value=deepcopy(value), violations=expansion.violations)
        candidate = expansion.value
        if expansion.normalized_path_count:
            rule_ids.append(ROLE_CREATIVE_BRIEF_PROP_SUMMARY_EXPANSION_RULE_ID)
            normalized_path_count += expansion.normalized_path_count

    if expected_variant == "character_main":
        expansion = _expand_role_summary(
            candidate,
            {
                "identity": "{summary}",
                "face_and_hair": "Use only the face and hair details explicitly described in the accepted direction: {summary}",
                "silhouette_and_proportions": "Use only the silhouette and proportions explicitly described in the accepted direction: {summary}",
                "wardrobe": "Use only the wardrobe details explicitly described in the accepted direction: {summary}",
                "accessories": "",
            },
        )
        if expansion.violations:
            return AgentStructuredNormalizationResult(value=deepcopy(value), violations=expansion.violations)
        candidate = expansion.value
        if expansion.normalized_path_count:
            rule_ids.append(ROLE_CREATIVE_BRIEF_CHARACTER_MAIN_SUMMARY_EXPANSION_RULE_ID)
            normalized_path_count += expansion.normalized_path_count

    return AgentStructuredNormalizationResult(
        value=candidate,
        rule_ids=tuple(rule_ids),
        normalized_path_count=normalized_path_count,
    )


def _expand_product_main_summary(
    value: dict[str, Any],
) -> AgentStructuredNormalizationResult:
    """Expand one generic product summary without inventing product attributes.

    This rule applies only when no canonical Product Main field was supplied.
    Every generated field retains the same source summary and limits the compiler
    to details explicitly stated in that summary.
    """

    return _expand_role_summary(
        value,
        {
            "identity": "{summary}",
            "geometry": "Use only the product geometry explicitly described in the accepted direction: {summary}",
            "materials": "Use only the materials and finish explicitly described in the accepted direction: {summary}",
            "marks": "Use only the marks and certifications explicitly described in the accepted direction: {summary}",
            "palette": "Use only the palette explicitly described in the accepted direction: {summary}",
        },
    )


def _expand_role_summary(
    value: dict[str, Any],
    field_templates: Mapping[str, str],
) -> AgentStructuredNormalizationResult:
    if any(field in value for field in field_templates):
        return AgentStructuredNormalizationResult(value=deepcopy(value))

    supplied = tuple(
        (name, value[name]) for name in _PRODUCT_MAIN_SUMMARY_ALIASES if name in value
    )
    if not supplied or any(not isinstance(item, str) or not item.strip() for _, item in supplied):
        return AgentStructuredNormalizationResult(value=deepcopy(value))

    summaries = tuple(item.strip() for _, item in supplied)
    if len(set(summaries)) != 1:
        return AgentStructuredNormalizationResult(
            value=deepcopy(value),
            violations=(
                StructuredViolation(
                    code="agent_structured_normalization_alias_conflict",
                    message="The structured product brief contains conflicting summary aliases.",
                    field_path="product_main",
                ),
            ),
        )

    summary = summaries[0]
    candidate = deepcopy(value)
    for name, _ in supplied:
        del candidate[name]
    candidate.update({name: template.format(summary=summary) for name, template in field_templates.items()})
    return AgentStructuredNormalizationResult(
        value=candidate,
        normalized_path_count=len(supplied) + len(field_templates),
    )


_CONTROL_ALIASES = MappingProxyType({
    "target_duration_sec": "duration_seconds",
    "target_duration_seconds": "duration_seconds",
    "duration_sec": "duration_seconds",
    "resolution": "output_resolution",
    "fps": "frame_rate",
})
_PRESENCE_ALIASES = MappingProxyType({
    "include": "include", "included": "include", "present": "include", "required": "include", "包含": "include", "需要": "include", "已提及": "include",
    "exclude": "exclude", "excluded": "exclude", "absent": "exclude", "omit": "exclude", "排除": "exclude", "不要": "exclude", "不需要": "exclude",
    "unspecified": "unspecified", "unknown": "unspecified", "not_mentioned": "unspecified", "not specified": "unspecified", "未说明": "unspecified", "未提及": "unspecified", "不确定": "unspecified",
})
_FLOAT_CONTROLS = frozenset(("duration_seconds", "frame_rate"))
_INT_CONTROLS = frozenset(("product_count", "prop_count", "character_count", "scene_count", "storyboard_sequence_count", "video_segment_count"))
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_INTEGER_RE = re.compile(r"[0-9]+")


def _normalize_control_aliases(candidate: dict[str, Any]) -> tuple[int, StructuredViolation | None]:
    controls = candidate.get("requirement_patch", {}).get("controls_to_set") if isinstance(candidate.get("requirement_patch"), dict) else None
    if not isinstance(controls, dict):
        return 0, None
    groups: dict[str, list[tuple[str, Any]]] = {}
    known = frozenset(_CONTROL_ALIASES) | frozenset(_CONTROL_ALIASES.values())
    for key, val in list(controls.items()):
        nk = unicodedata.normalize("NFKC", key)
        target = _CONTROL_ALIASES.get(nk, nk) if nk in known else key
        groups.setdefault(target, []).append((key, val))
    changed = 0
    for target, entries in groups.items():
        if len(entries) > 1:
            first_value = entries[0][1]
            if any(not _typed_equal(first_value, val) for _, val in entries[1:]):
                return 0, StructuredViolation(code="agent_structured_normalization_alias_conflict", message="Canonical and alias control values conflict.", field_path=f"requirement_patch.controls_to_set.{target}")
        canonical = next(((key, val) for key, val in entries if key == target), entries[0])
        if canonical[0] != target or len(entries) > 1:
            controls[target] = canonical[1]
        changed += sum(key != target for key, _ in entries)
        for key, _ in entries:
            if key != target and key in controls:
                del controls[key]
    return changed, None


def _typed_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def _normalize_presence_aliases(candidate: dict[str, Any]) -> int:
    elements = candidate.get("explicit_elements")
    if not isinstance(elements, dict):
        return 0
    changed = 0
    for name in _INTAKE_ELEMENT_NAMES:
        item = elements.get(name)
        if not isinstance(item, dict) or "presence" not in item or not isinstance(item["presence"], str):
            continue
        key = unicodedata.normalize("NFKC", item["presence"]).strip().casefold()
        mapped = _PRESENCE_ALIASES.get(key)
        if mapped is not None and item["presence"] != mapped:
            item["presence"] = mapped
            changed += 1
    return changed


def _normalize_presence_safe_defaults(candidate: dict[str, Any]) -> int:
    elements = candidate.get("explicit_elements")
    if not isinstance(elements, dict):
        return 0
    changed = 0
    for name in _INTAKE_ELEMENT_NAMES:
        item = elements.get(name)
        if not isinstance(item, dict) or "presence" not in item:
            continue
        presence = item["presence"]
        if isinstance(presence, str):
            if not presence.strip():
                continue
        elif not isinstance(presence, (bool, int, float)):
            continue
        if presence in {"include", "exclude", "unspecified"}:
            continue
        item["presence"] = "unspecified"
        changed += 1
    return changed


def _normalize_lossless_scalars(candidate: dict[str, Any]) -> int:
    patch = candidate.get("requirement_patch")
    controls = patch.get("controls_to_set") if isinstance(patch, dict) else None
    if not isinstance(controls, dict):
        return 0
    changed = 0
    for name in _FLOAT_CONTROLS | _INT_CONTROLS:
        item = controls.get(name)
        if not isinstance(item, dict) or not isinstance(item.get("value"), str):
            continue
        raw = item["value"]
        try:
            if name in _FLOAT_CONTROLS:
                if _DECIMAL_RE.fullmatch(raw) is None:
                    continue
                parsed = float(raw)
                if not math.isfinite(parsed):
                    continue
            else:
                if _INTEGER_RE.fullmatch(raw) is None:
                    continue
                parsed = int(raw)
        except (ValueError, OverflowError):
            continue
        item["value"] = parsed
        changed += 1
    return changed


def _remove_null_property(container: dict[str, Any], property_name: str) -> int:
    if property_name not in container or container[property_name] is not None:
        return 0
    del container[property_name]
    return 1


def _creative_directive_effects(
    value: dict[str, Any],
) -> tuple[tuple[str, dict[str, Any]], ...]:
    questions = value.get("questions")
    if not isinstance(questions, list):
        return ()
    matched: list[tuple[str, dict[str, Any]]] = []
    for question_index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        options = question.get("options")
        if not isinstance(options, list):
            continue
        for option_index, option in enumerate(options):
            if not isinstance(option, dict):
                continue
            effects = option.get("effects")
            if not isinstance(effects, list):
                continue
            for effect_index, effect in enumerate(effects):
                if not isinstance(effect, dict):
                    continue
                if effect.get("effect_type") != "creative_directive":
                    continue
                matched.append(
                    (
                        (
                            f"questions.{question_index}.options.{option_index}."
                            f"effects.{effect_index}"
                        ),
                        effect,
                    )
                )
    return tuple(matched)


_NORMALIZATION_RULES = MappingProxyType(
    {
        "CompactTurnIntentDecisionV3": _normalize_compact_turn_intent,
        "DecisionBundleDraftV1": _normalize_decision_bundle_capability_alias,
        "RoleCreativeBriefV2": _normalize_role_creative_brief,
    }
)

AGENT_STRUCTURED_NORMALIZATION_REGISTRY = AgentStructuredNormalizationRegistry()
