"""Shared identity and deadline budget for one V2 Pi planning request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256

from app.schemas.agent_runtime import AgentName


class V2PiPlanningDeadlineError(RuntimeError):
    code = "v2_planning_deadline_exceeded"


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    run_id: str
    request_id: str
    parent_run_id: str
    deadline_at: datetime
    timeout_seconds: float
    model_policy_id: str


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
            model_policy_id=f"{agent_name}.{operation}.v1",
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
