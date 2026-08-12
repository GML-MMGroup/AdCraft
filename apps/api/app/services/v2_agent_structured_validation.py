"""Trusted schema and semantic validation for in-run Pi submissions."""

from __future__ import annotations

from typing import Any
import unicodedata

from pydantic import ValidationError

from app.persistence.agent_run_repository import AgentRunRecord, AgentRunRepository
from app.schemas.agent_runtime import (
    AgentStructuredSubmission,
    AgentStructuredValidationResult,
    StructuredViolation,
)
from app.services.v2_agent_contract_registry import (
    AgentStructuredContractRegistryError,
    validate_agent_contract,
)


class V2AgentStructuredValidationService:
    """Validate model-owned values against Python-owned durable run metadata."""

    def __init__(self, repository: AgentRunRepository) -> None:
        self._repository = repository

    def validate(
        self,
        *,
        run: AgentRunRecord,
        submission: AgentStructuredSubmission,
    ) -> AgentStructuredValidationResult:
        identity_violations = _identity_violations(run, submission)
        if identity_violations:
            return _rejected(submission, identity_violations)
        raw_semantic_violations = self._raw_semantic_violations(
            run,
            submission.value,
        )

        try:
            normalized = validate_agent_contract(
                run.contract_name or "",
                submission.value,
            )
        except ValidationError as error:
            return _rejected(
                submission,
                tuple(
                    StructuredViolation(
                        code=str(item["type"]),
                        message=str(item["msg"]),
                        field_path=".".join(str(part) for part in item["loc"]) or None,
                        expected=_safe_violation_value(item.get("ctx")),
                        actual=_safe_violation_value(item.get("input")),
                    )
                    for item in error.errors()
                )
                + raw_semantic_violations,
            )
        except AgentStructuredContractRegistryError:
            return _rejected(
                submission,
                (
                    StructuredViolation(
                        code="agent_contract_not_allowed",
                        message="The persisted Agent contract is not registered.",
                        field_path="contract_name",
                    ),
                ),
                repair_allowed=False,
            )

        normalized_value = _canonicalize_profile_value(
            run.validation_profile,
            run.validation_context,
            normalized.model_dump(
                mode="json",
                exclude_unset=run.contract_name == "CompactTurnIntentDecisionV2",
            ),
        )
        if run.validation_profile == "canary_reject_first_v1":
            if submission.attempt == 1:
                return _rejected(
                    submission,
                    (
                        StructuredViolation(
                            code="canary_first_submission_rejected",
                            message="The verification canary requires one scoped repair.",
                        ),
                    ),
                )
            return AgentStructuredValidationResult(
                accepted=True,
                normalized_result_id=submission.submission_id,
                normalized_value=normalized_value,
                repair_allowed=False,
            )
        semantic_violations = raw_semantic_violations + _semantic_violations(
            run.validation_profile,
            run.validation_context,
            normalized_value,
        )
        if semantic_violations:
            return _rejected(submission, semantic_violations)
        return AgentStructuredValidationResult(
            accepted=True,
            normalized_result_id=submission.submission_id,
            normalized_value=normalized_value,
            repair_allowed=False,
        )

    def _raw_semantic_violations(
        self,
        run: AgentRunRecord,
        value: dict[str, Any],
    ) -> tuple[StructuredViolation, ...]:
        if run.validation_profile != "agent_intake_source_quotes_v1":
            return ()
        source_turn_id = run.validation_context.get("source_turn_id")
        if not isinstance(source_turn_id, str) or not source_turn_id:
            return (_invalid_intake_validation_context(),)
        source_message = self._repository.load_validation_source_message(
            workflow_id=run.workflow_id,
            conversation_id=run.conversation_id,
            turn_id=source_turn_id,
        )
        if source_message is None:
            return (_invalid_intake_validation_context(),)
        return _intake_source_quote_violations(source_message, value)


def _identity_violations(
    run: AgentRunRecord,
    submission: AgentStructuredSubmission,
) -> tuple[StructuredViolation, ...]:
    if submission.run_id != run.run_id:
        return (
            StructuredViolation(
                code="agent_run_mismatch",
                message="The structured submission does not belong to this Agent run.",
                field_path="run_id",
            ),
        )
    if submission.contract_name != run.contract_name:
        return (
            StructuredViolation(
                code="agent_contract_mismatch",
                message="The structured submission contract does not match the Agent run.",
                field_path="contract_name",
                expected=run.contract_name,
                actual=submission.contract_name,
            ),
        )
    return ()


def _semantic_violations(
    profile: str | None,
    context: dict[str, Any],
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    if profile in {
        None,
        "schema_only_v1",
        "video_parameter_intent_v1",
        "agent_intake_source_quotes_v1",
    }:
        return ()
    if profile == "front_desk_core_v1":
        return _front_desk_core_violations(value)
    if profile != "frozen_fields_v1":
        return (
            StructuredViolation(
                code="agent_validation_profile_not_allowed",
                message="The persisted Agent validation profile is not registered.",
                field_path="validation_profile",
            ),
        )
    expected_values = context.get("expected_values")
    if not isinstance(expected_values, dict):
        return (
            StructuredViolation(
                code="agent_validation_context_invalid",
                message="The persisted Agent validation context is incomplete.",
                field_path="expected_values",
            ),
        )
    violations: list[StructuredViolation] = []
    for field_path, expected in expected_values.items():
        if not isinstance(field_path, str):
            continue
        actual = _value_at_path(value, field_path)
        if actual != expected:
            violations.append(
                StructuredViolation(
                    code="frozen_fact_mismatch",
                    message="The result changed a frozen explicit fact.",
                    field_path=field_path,
                    expected=expected,
                    actual=actual,
                )
            )
    return tuple(violations)


def _invalid_intake_validation_context() -> StructuredViolation:
    return StructuredViolation(
        code="agent_validation_context_invalid",
        message="The persisted Agent validation context is incomplete.",
        field_path="source_turn_id",
    )


def _safe_violation_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2_048]
    if isinstance(value, BaseException):
        return str(value)[:1_024]
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            str(key)[:160]: _safe_violation_value(item, depth=depth + 1)
            for key, item in tuple(value.items())[:16]
        }
    if isinstance(value, (list, tuple)):
        return [_safe_violation_value(item, depth=depth + 1) for item in value[:16]]
    return type(value).__name__


def _intake_source_quote_violations(
    source_message: str,
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    normalized_message = unicodedata.normalize("NFKC", source_message)
    violations: list[StructuredViolation] = []
    for field_path, quote in _intake_source_quotes(value):
        if unicodedata.normalize("NFKC", quote) in normalized_message:
            continue
        violations.append(
            StructuredViolation(
                code="requirement_source_quote_invalid",
                message="Requirement evidence must quote the current user message exactly.",
                field_path=field_path,
                expected="exact substring of the current user message",
                actual=quote,
            )
        )
    return tuple(violations)


def _intake_source_quotes(value: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    quotes: list[tuple[str, str]] = []
    requirement_patch = value.get("requirement_patch")
    if isinstance(requirement_patch, dict):
        controls = requirement_patch.get("controls_to_set")
        if isinstance(controls, dict):
            for control_name, control in controls.items():
                if isinstance(control, dict) and isinstance(control.get("source_quote"), str):
                    quotes.append(
                        (
                            f"requirement_patch.controls_to_set.{control_name}.source_quote",
                            control["source_quote"],
                        )
                    )
        directives = requirement_patch.get("directives_to_add")
        if isinstance(directives, list):
            quotes.extend(
                (
                    f"requirement_patch.directives_to_add.{index}.source_quote",
                    directive["source_quote"],
                )
                for index, directive in enumerate(directives)
                if isinstance(directive, dict) and isinstance(directive.get("source_quote"), str)
            )
    explicit_elements = value.get("explicit_elements")
    if isinstance(explicit_elements, list):
        quotes.extend(
            (f"explicit_elements.{index}.source_quote", element["source_quote"])
            for index, element in enumerate(explicit_elements)
            if isinstance(element, dict) and isinstance(element.get("source_quote"), str)
        )
    return tuple(quotes)


def _canonicalize_profile_value(
    profile: str | None,
    context: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    if profile != "front_desk_core_v1":
        return value
    if value.get("intent") not in {"ready_for_workflow", "ad_request"}:
        return value
    ad_request = value.get("ad_request")
    fallback = context.get("fallback_product_description")
    if (
        isinstance(ad_request, dict)
        and not str(ad_request.get("product_description") or "").strip()
        and isinstance(fallback, str)
        and fallback.strip()
    ):
        value = dict(value)
        value["ad_request"] = {
            **ad_request,
            "product_description": fallback.strip()[:1_000],
        }
    return value


def _front_desk_core_violations(
    value: dict[str, Any],
) -> tuple[StructuredViolation, ...]:
    if value.get("intent") not in {"ready_for_workflow", "ad_request"}:
        return ()
    ad_request = value.get("ad_request")
    if not isinstance(ad_request, dict):
        return (
            StructuredViolation(
                code="front_desk_core_field_missing",
                message="Workflow creation requires a structured advertising request.",
                field_path="ad_request",
            ),
        )
    violations: list[StructuredViolation] = []
    for field_name in ("product_name", "product_description", "target_audience"):
        field_value = ad_request.get(field_name)
        if field_value is None or not str(field_value).strip():
            violations.append(
                StructuredViolation(
                    code="front_desk_core_field_missing",
                    message="Workflow creation is missing required advertising information.",
                    field_path=f"ad_request.{field_name}",
                )
            )
    return tuple(violations)


def _value_at_path(value: dict[str, Any], field_path: str) -> Any:
    current: Any = value
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _rejected(
    submission: AgentStructuredSubmission,
    violations: tuple[StructuredViolation, ...],
    *,
    repair_allowed: bool | None = None,
) -> AgentStructuredValidationResult:
    return AgentStructuredValidationResult(
        accepted=False,
        violations=violations,
        repair_allowed=(submission.attempt < 2 if repair_allowed is None else repair_allowed),
    )
