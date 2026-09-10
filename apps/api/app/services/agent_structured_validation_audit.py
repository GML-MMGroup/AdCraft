"""Project bounded structured-validation diagnostics without rejected values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from app.schemas.agent_runtime import AgentStructuredValidationAttemptAuditV1


_ATTEMPT_FIELDS = (
    "attempt",
    "attempt_stage",
    "violation_count",
    "validation_paths",
    "violation_codes",
    "violation_categories",
    "repair_allowed",
    "truncated",
)


def safe_structured_validation_attempts(candidate: Any) -> list[dict[str, Any]]:
    """Return protocol-valid attempt summaries after applying an exact allowlist."""

    if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes)):
        return []
    attempts: list[dict[str, Any]] = []
    for raw_attempt in candidate[:2]:
        if not isinstance(raw_attempt, Mapping):
            continue
        allowed = {key: raw_attempt[key] for key in _ATTEMPT_FIELDS if key in raw_attempt}
        try:
            attempt = AgentStructuredValidationAttemptAuditV1.model_validate(allowed)
        except ValidationError:
            continue
        attempts.append(attempt.model_dump(mode="json"))
    return attempts


def ordered_validation_path_union(candidate: Any) -> tuple[str, ...]:
    """Return the first 32 distinct paths in attempt and path order."""

    ordered: list[str] = []
    seen: set[str] = set()
    for attempt in safe_structured_validation_attempts(candidate):
        for path in attempt["validation_paths"]:
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
            if len(ordered) == 32:
                return tuple(ordered)
    return tuple(ordered)
