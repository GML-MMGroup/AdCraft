"""Post-commit dispatcher for durable Agent Canvas automatic Run commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.persistence.agent_canvas_auto_run_repository import (
    AgentCanvasAutomaticRunRepository,
    ClaimedAutomaticRun,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime import CanvasRunRequestV2


class _AcceptedRun(Protocol):
    execution_id: str


StartOrExtend = Callable[..., _AcceptedRun]


@dataclass(frozen=True)
class AutoRunDispatcherCycle:
    claimed: int
    submitted: int
    retried: int
    failed: int


class AgentCanvasAutoRunDispatcher:
    """Claim commands and submit them through canonical selected-node Run."""

    def __init__(
        self,
        commands: AgentCanvasAutomaticRunRepository,
        *,
        start_or_extend: StartOrExtend,
        resume_execution: Callable[[str], object],
        worker_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=90),
        base_backoff: timedelta = timedelta(seconds=5),
        maximum_backoff: timedelta = timedelta(minutes=5),
    ) -> None:
        self._commands = commands
        self._start_or_extend = start_or_extend
        self._resume_execution = resume_execution
        self._worker_id = worker_id
        self._clock = clock
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._maximum_backoff = maximum_backoff

    def run_once(self) -> AutoRunDispatcherCycle:
        claimed = self._commands.claim_due(
            worker_id=self._worker_id,
            now=self._clock(),
            batch_limit=self._batch_limit,
            lease_duration=self._lease_duration,
        )
        submitted = 0
        retried = 0
        failed = 0
        for claim in claimed:
            outcome = self._dispatch_one(claim)
            submitted += outcome == "submitted"
            retried += outcome == "retried"
            failed += outcome == "failed"
        return AutoRunDispatcherCycle(
            claimed=len(claimed),
            submitted=submitted,
            retried=retried,
            failed=failed,
        )

    def _dispatch_one(self, claim: ClaimedAutomaticRun) -> str:
        command = claim.command
        try:
            accepted = self._start_or_extend(
                command.workflow_id,
                CanvasRunRequestV2(
                    scope="selected_nodes",
                    node_ids=(command.node_id,),
                    source_action="agent_auto_generate",
                ),
                idempotency_key=command.command_id,
            )
        except Exception as exception:  # noqa: BLE001 - isolate each durable command.
            error = _dispatch_error(exception)
            delay = min(
                self._base_backoff * (2**command.attempt_count),
                self._maximum_backoff,
            )
            updated = self._commands.record_failure(
                command.command_id,
                worker_id=self._worker_id,
                lease_generation=claim.lease_generation,
                error=error,
                retry_at=self._clock() + delay,
                now=self._clock(),
            )
            return "retried" if updated.state == "pending" else "failed"
        self._commands.mark_submitted(
            command.command_id,
            worker_id=self._worker_id,
            lease_generation=claim.lease_generation,
            execution_id=accepted.execution_id,
            now=self._clock(),
        )
        try:
            self._resume_execution(accepted.execution_id)
        except Exception:  # noqa: BLE001 - durable execution recovery owns resumption.
            pass
        return "submitted"


def _dispatch_error(exception: Exception) -> CanvasNodeErrorV2:
    if isinstance(exception, V2PersistenceError):
        code = exception.code
        message = str(exception)
        retryable = code.endswith(("_unavailable", "_busy", "_timeout")) or code in {
            "runtime_persistence_unavailable",
            "event_store_unavailable",
        }
    else:
        code = "agent_auto_run_submission_failed"
        message = str(exception) or "Automatic Run submission failed."
        retryable = True
    return CanvasNodeErrorV2(
        code=code,
        message=message[:1_024],
        retryable=retryable,
    )
