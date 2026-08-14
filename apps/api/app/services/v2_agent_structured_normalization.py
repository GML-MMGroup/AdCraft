"""Closed, contract-local normalization for structured Agent submissions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from app.schemas.agent_runtime import StructuredViolation


DECISION_BUNDLE_CAPABILITY_ALIAS_RULE_ID = (
    "decision_bundle.creative_directive.capability_ids_alias.v1"
)
COMPACT_TURN_INTENT_OMITTABLE_NULLS_RULE_ID = "compact_turn_intent_v3.omittable_nulls.v1"

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
        "CompactTurnIntentDecisionV3": _normalize_compact_turn_intent_omittable_nulls,
        "DecisionBundleDraftV1": _normalize_decision_bundle_capability_alias,
    }
)

AGENT_STRUCTURED_NORMALIZATION_REGISTRY = AgentStructuredNormalizationRegistry()
