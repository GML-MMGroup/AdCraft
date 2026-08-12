"""Bounded worker for durable Agent Canvas continuation deliveries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import ContinuationDeliveryV2
from app.services.pi_agent_runtime_client import PiAgentRuntimeError
from app.services.v2_agent_contract_registry import (
    AgentStructuredContractRegistryError,
)


@dataclass(frozen=True)
class ContinuationWorkerCycle:
    claimed: int
    completed: int
    retried: int
    failed: int


class AgentCanvasContinuationWorker:
    """Claim and process one small continuation batch without sleeping."""

    def __init__(
        self,
        outbox: AgentCanvasContinuationOutboxRepository,
        *,
        next_action: Callable[[str], object],
        capability_command: Callable[[str], object],
        replace_superseded_capability: Callable[[str], object] | None = None,
        capability_materialization: Callable[[str, Callable[[], None]], object] | None = None,
        clock: Callable[[], datetime] | None = None,
        worker_id: str,
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=90),
        base_backoff: timedelta = timedelta(seconds=5),
        maximum_backoff: timedelta = timedelta(minutes=5),
        jitter: Callable[[int], timedelta] | None = None,
        fail_turn: Callable[[str, str, str], object] | None = None,
    ) -> None:
        self._outbox = outbox
        self._handlers = {
            "next_action": next_action,
            "capability_command": capability_command,
        }
        self._capability_materialization = capability_materialization
        self._replace_superseded_capability = replace_superseded_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._worker_id = worker_id
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._maximum_backoff = maximum_backoff
        self._jitter = jitter or (lambda _: timedelta(0))
        self._fail_turn = fail_turn

    def run_once(self) -> ContinuationWorkerCycle:
        claimed = self._outbox.claim_due(
            worker_id=self._worker_id,
            now=self._clock(),
            batch_limit=self._batch_limit,
            lease_duration=self._lease_duration,
        )
        completed = 0
        retried = 0
        failed = 0
        for delivery in claimed:
            outcome = self._process_one(delivery)
            completed += outcome == "completed"
            retried += outcome == "retried"
            failed += outcome == "failed"
        return ContinuationWorkerCycle(
            claimed=len(claimed),
            completed=completed,
            retried=retried,
            failed=failed,
        )

    def _process_one(self, delivery: ContinuationDeliveryV2) -> str:
        try:
            if delivery.operation == "capability_materialization":
                if self._capability_materialization is None:
                    raise V2PersistenceError(
                        "capability_materialization_unavailable",
                        "Capability Materialization worker is unavailable.",
                    )
                self._run_materialization(delivery)
            else:
                self._handlers[delivery.operation](delivery.envelope_id)
        except Exception as error:  # noqa: BLE001 - each delivery is isolated.
            if isinstance(error, V2PersistenceError) and error.code == "continuation_lease_stale":
                return "retried"
            if (
                isinstance(error, V2PersistenceError)
                and error.code == "requirement_revision_superseded"
            ):
                self._outbox.supersede(
                    delivery.continuation_id,
                    reason="Capability result used an obsolete Requirement revision.",
                    now=self._clock(),
                )
                if self._replace_superseded_capability is not None:
                    self._replace_superseded_capability(delivery.envelope_id)
                return "completed"
            error_code, retryable = _structured_failure(error)
            return self._record_failure(
                delivery,
                error_code=error_code,
                error_message=str(error) or "Continuation dispatch failed.",
                retryable=retryable,
            )

        if self._outbox.get(delivery.continuation_id).status == "completed":
            return "completed"
        self._outbox.complete(
            delivery.continuation_id,
            worker_id=self._worker_id,
            lease_generation=delivery.lease_generation,
            now=self._clock(),
        )
        return "completed"

    def _run_materialization(self, delivery: ContinuationDeliveryV2) -> None:
        assert self._capability_materialization is not None
        stopped = Event()
        lease_lost = Event()
        interval = max(self._lease_duration.total_seconds() / 3, 0.01)

        def guard() -> None:
            if lease_lost.is_set():
                raise V2PersistenceError(
                    "continuation_lease_stale",
                    "Continuation lease has been superseded or expired.",
                )
            self._outbox.assert_owned(
                delivery.continuation_id,
                worker_id=self._worker_id,
                lease_generation=delivery.lease_generation,
                now=self._clock(),
            )

        def renew() -> None:
            while not stopped.wait(interval):
                try:
                    self._outbox.renew_lease(
                        delivery.continuation_id,
                        worker_id=self._worker_id,
                        lease_generation=delivery.lease_generation,
                        now=self._clock(),
                        lease_duration=self._lease_duration,
                    )
                except V2PersistenceError:
                    lease_lost.set()
                    return

        thread = Thread(target=renew, name="agent-canvas-materialization-lease", daemon=True)
        thread.start()
        try:
            guard()
            self._capability_materialization(delivery.envelope_id, guard)
            if self._outbox.get(delivery.continuation_id).status != "completed":
                guard()
        finally:
            stopped.set()
            thread.join(timeout=min(interval, 1.0))

    def _record_failure(
        self,
        delivery: ContinuationDeliveryV2,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> str:
        next_attempt = delivery.attempt_count + 1
        if not retryable or next_attempt >= delivery.max_attempts:
            return self._record_terminal(
                delivery,
                error_code=(
                    error_code
                    if error_code != "continuation_dispatch_failed"
                    else "continuation_retry_exhausted"
                ),
                error_message=error_message,
            )
        delay = min(
            self._base_backoff * (2**delivery.attempt_count),
            self._maximum_backoff,
        )
        self._outbox.schedule_retry(
            delivery.continuation_id,
            worker_id=self._worker_id,
            lease_generation=delivery.lease_generation,
            next_attempt_at=self._clock() + delay + self._jitter(next_attempt),
            error_code=error_code,
            error_message=error_message,
            now=self._clock(),
        )
        return "retried"

    def _record_terminal(
        self,
        delivery: ContinuationDeliveryV2,
        *,
        error_code: str,
        error_message: str,
    ) -> str:
        self._outbox.fail(
            delivery.continuation_id,
            worker_id=self._worker_id,
            lease_generation=delivery.lease_generation,
            error_code=error_code,
            error_message=error_message,
            now=self._clock(),
        )
        if self._fail_turn is not None:
            self._fail_turn(
                delivery.continuation_turn_id,
                error_code,
                error_message[:1_024],
            )
        return "failed"


def _structured_failure(error: Exception) -> tuple[str, bool]:
    if isinstance(error, AgentStructuredContractRegistryError):
        return error.code, False
    if isinstance(error, PiAgentRuntimeError):
        return error.code, error.retryable and error.code != "agent_deadline_exceeded"
    if isinstance(error, V2PersistenceError):
        retryable = error.details.get("retryable", False)
        return error.code, bool(retryable) and error.code != "agent_deadline_exceeded"
    return "continuation_dispatch_failed", True
