"""Shared validation for immutable proposal candidate cardinality."""

from __future__ import annotations

from pydantic import BaseModel


def proposal_candidate_count_details(
    expected_candidate_count: int,
    result: BaseModel,
) -> dict[str, object] | None:
    """Return bounded mismatch details, or ``None`` when the result matches."""

    options = getattr(result, "options", None)
    actual_candidate_count = len(options) if isinstance(options, tuple) else None
    if actual_candidate_count == expected_candidate_count:
        return None
    return {
        "expected_candidate_count": expected_candidate_count,
        "actual_candidate_count": actual_candidate_count,
        "field_path": "options",
    }
