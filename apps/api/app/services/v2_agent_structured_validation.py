"""Trusted schema and semantic validation for in-run Pi submissions."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.persistence.agent_run_repository import AgentRunRecord, AgentRunRepository
from app.schemas.agent_runtime import (
    AgentStructuredSubmission,
    AgentStructuredValidationResult,
    StructuredViolation,
)
from app.services.v2_agent_contract_registry import validate_agent_contract


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
                    )
                    for item in error.errors()
                ),
            )
        except ValueError:
            return _rejected(
                submission,
                (
                    StructuredViolation(
                        code="agent_contract_not_allowed",
                        message="The persisted Agent contract is not registered.",
                        field_path="contract_name",
                    ),
                ),
            )

        normalized_value = normalized.model_dump(mode="json")
        semantic_violations = _semantic_violations(
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
    if profile in {None, "schema_only_v1"}:
        return ()
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
) -> AgentStructuredValidationResult:
    return AgentStructuredValidationResult(
        accepted=False,
        violations=violations,
        repair_allowed=submission.attempt < 2,
    )
