"""Bounded worker for durable Agent Canvas continuation deliveries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import ContinuationDeliveryV2
from app.services.agent_canvas_continuation_lease import (
    ContinuationLeaseScope,
    HeartbeatWait,
    wait_for_heartbeat,
)
from app.services.agent_canvas_explicit_retry import explicit_turn_retryable
from app.services.pi_agent_runtime_client import PiAgentRuntimeError
from app.services.v2_agent_contract_registry import (
    AgentStructuredContractRegistryError,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContinuationWorkerCycle:
    claimed: int
    completed: int
    retried: int
    failed: int
    lease_lost: int = 0


class AgentCanvasContinuationWorker:
    """Claim and process one small continuation batch without sleeping."""

    def __init__(
        self,
        outbox: AgentCanvasContinuationOutboxRepository,
        *,
        next_action: Callable[[str, Callable[[], None]], object],
        capability_command: Callable[[str, Callable[[], None]], object],
        replace_superseded_capability: Callable[[str], object] | None = None,
        supersede_capability: Callable[[str, str, int], object] | None = None,
        capability_materialization: Callable[[str, Callable[[], None]], object] | None = None,
        clock: Callable[[], datetime] | None = None,
        worker_id: str,
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=90),
        base_backoff: timedelta = timedelta(seconds=5),
        maximum_backoff: timedelta = timedelta(minutes=5),
        jitter: Callable[[int], timedelta] | None = None,
        fail_turn: Callable[[str, str, str, bool], object] | None = None,
        heartbeat_wait: HeartbeatWait = wait_for_heartbeat,
    ) -> None:
        self._outbox = outbox
        self._handlers = {
            "next_action": next_action,
            "capability_command": capability_command,
        }
        self._capability_materialization = capability_materialization
        self._replace_superseded_capability = replace_superseded_capability
        self._supersede_capability = supersede_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._worker_id = worker_id
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._maximum_backoff = maximum_backoff
        self._jitter = jitter or (lambda _: timedelta(0))
        self._fail_turn = fail_turn
        self._heartbeat_wait = heartbeat_wait

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
        lease_lost = 0
        for delivery in claimed:
            try:
                outcome = self._process_one(delivery)
            except Exception as error:  # noqa: BLE001 - preserve batch isolation.
                if _is_stale_lease(error):
                    outcome = "lease_lost"
                else:
                    logger.error(
                        "Agent Canvas continuation delivery failed unexpectedly "
                        "continuation_id=%s operation=%s owner=%s generation=%s code=%s",
                        delivery.continuation_id,
                        delivery.operation,
                        self._worker_id,
                        delivery.lease_generation,
                        _structured_failure(error)[0],
                    )
                    outcome = "failed"
            completed += outcome == "completed"
            retried += outcome == "retried"
            failed += outcome == "failed"
            lease_lost += outcome == "lease_lost"
        return ContinuationWorkerCycle(
            claimed=len(claimed),
            completed=completed,
            retried=retried,
            failed=failed,
            lease_lost=lease_lost,
        )

    def _process_one(self, delivery: ContinuationDeliveryV2) -> str:
        lease_scope = ContinuationLeaseScope(
            self._outbox,
            continuation_id=delivery.continuation_id,
            worker_id=self._worker_id,
            lease_generation=delivery.lease_generation,
            lease_duration=self._lease_duration,
            clock=self._clock,
            heartbeat_wait=self._heartbeat_wait,
        )
        try:
            with lease_scope as lease_guard:
                if delivery.operation == "capability_materialization":
                    if self._capability_materialization is None:
                        raise V2PersistenceError(
                            "capability_materialization_unavailable",
                            "Capability Materialization worker is unavailable.",
                        )
                    self._capability_materialization(delivery.envelope_id, lease_guard)
                else:
                    self._handlers[delivery.operation](delivery.envelope_id, lease_guard)
                current = self._outbox.get(delivery.continuation_id)
                if current.status == "completed":
                    if current.lease_generation != delivery.lease_generation:
                        return "lease_lost"
                else:
                    lease_guard()
        except Exception as error:  # noqa: BLE001 - each delivery is isolated.
            if _is_stale_lease(error):
                return "lease_lost"
            if (
                isinstance(error, V2PersistenceError)
                and error.code == "requirement_revision_superseded"
            ):
                try:
                    lease_scope.assert_owned()
                    if self._replace_superseded_capability is not None:
                        lease_scope.assert_owned()
                    self._outbox.supersede_owned(
                        delivery.continuation_id,
                        worker_id=self._worker_id,
                        lease_generation=delivery.lease_generation,
                        reason="Capability result used an obsolete Requirement revision.",
                        now=self._clock(),
                    )
                    if self._replace_superseded_capability is not None:
                        self._replace_superseded_capability(delivery.envelope_id)
                    return "completed"
                except Exception as stale_error:  # noqa: BLE001 - fenced stale outcome.
                    if _is_stale_lease(stale_error):
                        return "lease_lost"
                    raise
            if (
                isinstance(error, V2PersistenceError)
                and error.code == "guided_capability_superseded"
            ):
                try:
                    lease_scope.assert_owned()
                    if self._supersede_capability is None:
                        raise V2PersistenceError(
                            "guided_capability_supersession_unavailable",
                            "Guided capability supersession publisher is unavailable.",
                        )
                    self._supersede_capability(
                        delivery.continuation_id,
                        self._worker_id,
                        delivery.lease_generation,
                    )
                    return "completed"
                except Exception as stale_error:  # noqa: BLE001 - fenced stale outcome.
                    if _is_stale_lease(stale_error):
                        return "lease_lost"
                    raise
            error_code, retryable = _structured_failure(error)
            try:
                return self._record_failure(
                    delivery,
                    error_code=error_code,
                    error_message=str(error) or "Continuation dispatch failed.",
                    retryable=retryable,
                )
            except Exception as stale_error:  # noqa: BLE001 - fenced stale outcome.
                if _is_stale_lease(stale_error):
                    return "lease_lost"
                raise

        if self._outbox.get(delivery.continuation_id).status == "completed":
            return "completed"
        try:
            self._outbox.complete(
                delivery.continuation_id,
                worker_id=self._worker_id,
                lease_generation=delivery.lease_generation,
                now=self._clock(),
            )
        except Exception as error:  # noqa: BLE001 - fenced stale outcome.
            if _is_stale_lease(error):
                return "lease_lost"
            raise
        return "completed"

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
            try:
                self._fail_turn(
                    delivery.continuation_turn_id,
                    error_code,
                    error_message[:1_024],
                    explicit_turn_retryable(error_code),
                )
            except Exception as error:  # noqa: BLE001 - continuation error is authoritative.
                logger.error(
                    "Agent Canvas continuation Turn publication failed "
                    "continuation_id=%s operation=%s owner=%s generation=%s code=%s",
                    delivery.continuation_id,
                    delivery.operation,
                    self._worker_id,
                    delivery.lease_generation,
                    _structured_failure(error)[0],
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


def _is_stale_lease(error: Exception) -> bool:
    return isinstance(error, V2PersistenceError) and error.code == "continuation_lease_stale"
