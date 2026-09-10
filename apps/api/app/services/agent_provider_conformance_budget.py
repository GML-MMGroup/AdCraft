"""Derive the frozen outer budget for one provider conformance run."""

from __future__ import annotations

from hashlib import sha256
import json

from app.schemas.agent_runtime import (
    AgentProviderConformanceBudgetPlanV1,
    AgentRunRequest,
)


class AgentProviderConformanceBudgetError(ValueError):
    """The frozen production request cannot produce a safe diagnostic budget."""


def canonical_agent_provider_conformance_budget_digest(
    plan: AgentProviderConformanceBudgetPlanV1,
) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(payload).hexdigest()}"


def derive_agent_provider_conformance_budget(
    request: AgentRunRequest,
) -> AgentProviderConformanceBudgetPlanV1:
    primary_seconds = request.policy.primary_timeout_seconds
    if primary_seconds is None or not 1 <= primary_seconds <= 900:
        raise AgentProviderConformanceBudgetError("conformance_budget_invalid")

    exact_case_timeout_ms = primary_seconds * 1_000
    isolation_case_timeout_ms = min(exact_case_timeout_ms, 60_000)
    success_path_ms = isolation_case_timeout_ms + (3 * exact_case_timeout_ms)
    diagnostic_path_ms = exact_case_timeout_ms + (5 * isolation_case_timeout_ms)
    matrix_timeout_ms = max(success_path_ms, diagnostic_path_ms) + 30_000
    child_timeout_ms = matrix_timeout_ms + 60_000
    lease_duration_seconds = (child_timeout_ms // 1_000) + 60
    if lease_duration_seconds > 3_600:
        raise AgentProviderConformanceBudgetError("conformance_budget_invalid")

    return AgentProviderConformanceBudgetPlanV1(
        exact_case_timeout_ms=exact_case_timeout_ms,
        isolation_case_timeout_ms=isolation_case_timeout_ms,
        matrix_timeout_ms=matrix_timeout_ms,
        child_timeout_ms=child_timeout_ms,
        lease_duration_seconds=lease_duration_seconds,
    )
