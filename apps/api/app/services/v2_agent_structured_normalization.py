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
    {"DecisionBundleDraftV1": _normalize_decision_bundle_capability_alias}
)

AGENT_STRUCTURED_NORMALIZATION_REGISTRY = AgentStructuredNormalizationRegistry()
