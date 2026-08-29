"""Closed, contract-local normalization for structured Agent submissions."""

from __future__ import annotations

from copy import deepcopy
import math
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


NormalizationRule = Callable[[dict[str, Any]], AgentStructuredNormalizationResult]
_NORMALIZATION_RULES: Mapping[str, NormalizationRule]


class AgentStructuredNormalizationRegistry:
    """Apply only exact normalization rules owned by one registered contract."""

    def normalize(
        self,
        contract_name: str,
        value: dict[str, Any],
    ) -> AgentStructuredNormalizationResult:
        rule = _NORMALIZATION_RULES.get(contract_name)
        if rule is None:
            return AgentStructuredNormalizationResult(value=deepcopy(value))
        return rule(value)


def _normalize_decision_bundle_capability_alias(
    value: dict[str, Any],
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


def _normalize_compact_turn_intent(value: dict[str, Any]) -> AgentStructuredNormalizationResult:
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
    changed = _normalize_lossless_scalars(candidate)
    count += changed
    if changed:
        rule_ids.append(COMPACT_TURN_INTENT_LOSSLESS_SCALARS_RULE_ID)

    null_result = _normalize_compact_turn_intent_omittable_nulls(candidate)
    candidate = null_result.value
    count += null_result.normalized_path_count
    rule_ids.extend(null_result.rule_ids)
    return AgentStructuredNormalizationResult(value=candidate, rule_ids=tuple(rule_ids), normalized_path_count=count)


_CONTROL_ALIASES = {"target_duration_sec": "duration_seconds", "duration_sec": "duration_seconds", "resolution": "output_resolution", "fps": "frame_rate"}
_PRESENCE_ALIASES = {
    "include": "include", "included": "include", "present": "include", "required": "include", "包含": "include", "需要": "include", "已提及": "include",
    "exclude": "exclude", "excluded": "exclude", "absent": "exclude", "omit": "exclude", "排除": "exclude", "不要": "exclude", "不需要": "exclude",
    "unspecified": "unspecified", "unknown": "unspecified", "not_mentioned": "unspecified", "not specified": "unspecified", "未说明": "unspecified", "未提及": "unspecified", "不确定": "unspecified",
}
_FLOAT_CONTROLS = {"duration_seconds", "frame_rate"}
_INT_CONTROLS = {"product_count", "prop_count", "character_count", "scene_count", "storyboard_sequence_count", "video_segment_count"}


def _normalize_control_aliases(candidate: dict[str, Any]) -> tuple[int, StructuredViolation | None]:
    controls = candidate.get("requirement_patch", {}).get("controls_to_set") if isinstance(candidate.get("requirement_patch"), dict) else None
    if not isinstance(controls, dict):
        return 0, None
    groups: dict[str, list[tuple[str, Any]]] = {}
    known = set(_CONTROL_ALIASES) | set(_CONTROL_ALIASES.values())
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
            changed += (canonical[0] != target)
        for key, _ in entries:
            if key != target and key in controls:
                del controls[key]
                changed += 1
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
        raw = item["value"].strip()
        try:
            if name in _FLOAT_CONTROLS:
                parsed = float(raw)
                if not math.isfinite(parsed):
                    continue
            else:
                if not raw.isdigit() and not (raw.startswith("-") and raw[1:].isdigit()):
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
    }
)

AGENT_STRUCTURED_NORMALIZATION_REGISTRY = AgentStructuredNormalizationRegistry()
