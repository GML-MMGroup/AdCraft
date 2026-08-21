"""Shared identity and deadline budget for one V2 Pi planning request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from app.schemas.agent_runtime import AgentName
from app.schemas.agent_operation_contexts import FrozenPlanningFacts
from app.schemas.workflow_v2_intent import V2ExplicitConstraints


class V2PiPlanningDeadlineError(RuntimeError):
    code = "v2_planning_deadline_exceeded"


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    run_id: str
    request_id: str
    parent_run_id: str
    deadline_at: datetime
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class V2PiPlanningSession:
    parent_run_id: str
    workflow_id: str
    deadline_at: datetime
    finalization_reserve_seconds: float = 20.0
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(timezone.utc),
        repr=False,
        compare=False,
    )

    @classmethod
    def start(
        cls,
        *,
        workflow_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> V2PiPlanningSession:
        effective_clock = clock or (lambda: datetime.now(timezone.utc))
        started_at = effective_clock()
        if started_at.tzinfo is None:
            raise ValueError("planning session clock must return timezone-aware values")
        return cls(
            parent_run_id=f"arun_plan_{_stable_digest(workflow_id, 'parent')}",
            workflow_id=workflow_id,
            deadline_at=started_at + timedelta(seconds=600),
            clock=effective_clock,
        )

    def __post_init__(self) -> None:
        if self.deadline_at.tzinfo is None:
            raise ValueError("deadline_at must be timezone-aware")
        if self.finalization_reserve_seconds < 0:
            raise ValueError("finalization_reserve_seconds cannot be negative")

    def child(
        self,
        *,
        agent_name: AgentName,
        operation: str,
        logical_key: str,
    ) -> AgentInvocation:
        timeout_seconds = self.require_model_budget()
        identity = f"{self.parent_run_id}:{agent_name}:{operation}:{logical_key}"
        return AgentInvocation(
            run_id=f"arun_{_stable_digest(identity, 'run')}",
            request_id=f"req_{_stable_digest(identity, 'request')}",
            parent_run_id=self.parent_run_id,
            deadline_at=self.deadline_at,
            timeout_seconds=timeout_seconds,
        )

    def remaining_model_seconds(self, *, now: datetime | None = None) -> float:
        current = now or self.clock()
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        remaining = (self.deadline_at - current).total_seconds()
        return max(0.0, remaining - self.finalization_reserve_seconds)

    def require_model_budget(self, *, now: datetime | None = None) -> float:
        remaining = self.remaining_model_seconds(now=now)
        if remaining <= 0:
            raise V2PiPlanningDeadlineError(
                "The shared V2 planning deadline has entered its finalization reserve."
            )
        return remaining


def _stable_digest(identity: str, purpose: str) -> str:
    return sha256(f"{purpose}:{identity}".encode("utf-8")).hexdigest()[:32]


def freeze_explicit_planning_facts(
    constraints: V2ExplicitConstraints,
) -> FrozenPlanningFacts:
    requirements = tuple(
        value
        for value in (
            constraints.product_source_span,
            constraints.storyboard_shot_count_span,
            constraints.duration_source_span,
            *(character.source_span for character in constraints.characters),
            *(scene.source_span for scene in constraints.scenes),
        )
        if value
    )
    return FrozenPlanningFacts(
        product_name=constraints.product_name,
        duration_seconds=constraints.duration_seconds,
        aspect_ratio=constraints.aspect_ratio,
        character_count=constraints.character_count,
        scene_count=constraints.scene_count,
        shot_count=constraints.storyboard_shot_count,
        explicit_requirements=requirements,
    )


def merge_planning_degradation(
    current: dict[str, Any],
    *,
    stage: str | None = None,
    stages: list[str] | tuple[str, ...] = (),
    reason_codes: list[str] | tuple[str, ...] = (),
    repaired_violation_codes: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Merge normalized degraded-planning evidence in stable order."""

    merged_stages = _dedupe_nonempty(
        [
            *list(current.get("degraded_stages") or []),
            *([stage] if stage else []),
            *stages,
        ]
    )
    merged_reasons = _dedupe_nonempty(
        [
            *list(current.get("degraded_reason_codes") or []),
            *reason_codes,
        ]
    )
    merged_repairs = _dedupe_nonempty(
        [
            *list(current.get("repaired_violation_codes") or []),
            *repaired_violation_codes,
        ]
    )
    result: dict[str, Any] = {
        "planning_degraded": True,
        "degraded_stages": merged_stages,
        "degraded_reason_codes": merged_reasons,
    }
    if merged_repairs:
        result["repaired_violation_codes"] = merged_repairs
    return result


def _dedupe_nonempty(values: list[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip() for value in values if value is not None and str(value).strip()
        )
    )
