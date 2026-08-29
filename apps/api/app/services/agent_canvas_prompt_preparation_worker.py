"""Bounded recovery worker for durable Node prompt preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation_dispatch import PromptPreparationDispatchV1
from app.services.agent_canvas_prompt_preparation_lease import (
    HeartbeatWait,
    PromptPreparationLeaseScope,
    wait_for_prompt_preparation_heartbeat,
)
from app.services.agent_canvas_prompt_preparation import context_digest


logger = logging.getLogger(__name__)

PreparationCallback = Callable[[PromptPreparationDispatchV1, StageAuthoringContextV1], object]
PreparationContextLoader = Callable[[PromptPreparationDispatchV1], StageAuthoringContextV1]
BarrierCallback = Callable[[PromptPreparationDispatchV1, object], object]


@dataclass(frozen=True)
class PromptPreparationWorkerCycle:
    claimed: int
    completed: int
    retried: int
    failed: int
    superseded: int = 0
    lease_lost: int = 0


class AgentCanvasPromptPreparationWorker:
    """Process a bounded batch without introducing a second state machine."""

    def __init__(
        self,
        dispatches: AgentCanvasPromptPreparationDispatchRepository,
        *,
        prepare: PreparationCallback,
        context_loader: PreparationContextLoader | None = None,
        worker_id: str,
        clock: Callable[[], datetime] | None = None,
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=90),
        base_backoff: timedelta = timedelta(seconds=5),
        maximum_backoff: timedelta = timedelta(minutes=5),
        barrier_callback: BarrierCallback | None = None,
        heartbeat_wait: HeartbeatWait = wait_for_prompt_preparation_heartbeat,
    ) -> None:
        if not worker_id:
            raise ValueError("Prompt-preparation worker requires an identity.")
        if batch_limit < 1 or lease_duration <= timedelta(0):
            raise ValueError("Prompt-preparation worker limits are invalid.")
        self._dispatches = dispatches
        self._prepare = prepare
        self._context_loader = context_loader
        self._worker_id = worker_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._maximum_backoff = maximum_backoff
        self._barrier_callback = barrier_callback
        self._heartbeat_wait = heartbeat_wait

    def run_once(self) -> PromptPreparationWorkerCycle:
        claimed, terminalized = self._dispatches.claim_due_with_terminalized(
            worker_id=self._worker_id,
            now=self._clock(),
            batch_limit=self._batch_limit,
            lease_duration=self._lease_duration,
        )
        completed = retried = superseded = lease_lost = 0
        failed = 0
        for dispatch in terminalized:
            exhausted = V2PersistenceError(
                "prompt_preparation_retry_exhausted",
                "Prompt preparation retry budget was exhausted.",
                stage="prompt_preparation_worker",
            )
            try:
                self._notify_terminal(dispatch, exhausted)
            except Exception:  # noqa: BLE001 - barrier wake must not halt recovery.
                logger.exception(
                    "Prompt-preparation terminal barrier notification failed dispatch_id=%s",
                    dispatch.dispatch_id,
                )
            failed += 1
        for dispatch in claimed:
            try:
                outcome = self._process_one(dispatch)
            except Exception as error:  # noqa: BLE001 - isolate one dispatch.
                logger.error(
                    "Prompt-preparation dispatch failed dispatch_id=%s code=%s",
                    dispatch.dispatch_id,
                    _error_code(error),
                )
                outcome = "failed"
            completed += outcome == "completed"
            retried += outcome == "retried"
            failed += outcome == "failed"
            superseded += outcome == "superseded"
            lease_lost += outcome == "lease_lost"
        return PromptPreparationWorkerCycle(
            claimed=len(claimed),
            completed=completed,
            retried=retried,
            failed=failed,
            superseded=superseded,
            lease_lost=lease_lost,
        )

    def _process_one(self, dispatch: PromptPreparationDispatchV1) -> str:
        lease_scope = PromptPreparationLeaseScope(
            self._dispatches,
            dispatch_id=dispatch.dispatch_id,
            worker_id=self._worker_id,
            lease_generation=dispatch.lease_generation,
            lease_duration=self._lease_duration,
            clock=self._clock,
            heartbeat_wait=self._heartbeat_wait,
        )
        try:
            with lease_scope as lease_guard:
                self._dispatches.assert_current_snapshot(
                    dispatch,
                    now=self._clock(),
                )
                if dispatch.context_json:
                    try:
                        context = StageAuthoringContextV1.model_validate(dispatch.context_json)
                    except Exception as error:  # Pydantic details stay private.
                        raise V2PersistenceError(
                            "prompt_preparation_context_invalid",
                            "Persisted prompt-preparation context is invalid.",
                            stage="prompt_preparation_worker",
                        ) from error
                elif self._context_loader is not None:
                    # Legacy direct-node fixtures may supply an explicit test
                    # loader. Production workers have no loader and therefore
                    # fail closed when immutable context proof is absent.
                    context = self._context_loader(dispatch)
                else:
                    raise V2PersistenceError(
                        "prompt_preparation_context_missing",
                        "Prompt-preparation dispatch has no immutable context snapshot.",
                        stage="prompt_preparation_worker",
                    )
                if not isinstance(context, StageAuthoringContextV1):
                    raise V2PersistenceError(
                        "prompt_preparation_context_invalid",
                        "Prompt-preparation context loader returned an invalid snapshot.",
                        stage="prompt_preparation_worker",
                    )
                if dispatch.context_json and (
                    not dispatch.context_digest
                    or context_digest(context) != dispatch.context_digest
                ):
                    raise V2PersistenceError(
                        "prompt_preparation_dispatch_stale",
                        "Prompt-preparation context does not match its frozen dispatch snapshot.",
                        stage="prompt_preparation_worker",
                    )
                result = self._prepare(dispatch, context)
                current = self._dispatches.get(dispatch.dispatch_id)
                if current.status in {"completed", "failed", "superseded"}:
                    if current.status == "superseded":
                        return "superseded"
                    self._notify_terminal(current, result)
                    return "completed" if current.status == "completed" else "failed"
                lease_guard()
                completed = self._dispatches.complete(
                    dispatch.dispatch_id,
                    worker_id=self._worker_id,
                    lease_generation=dispatch.lease_generation,
                    now=self._clock(),
                    node_revision=dispatch.node_revision,
                    operation_id=dispatch.operation_id,
                    context_digest=dispatch.context_digest,
                    source_snapshot=dispatch.source_snapshot,
                )
                self._notify_terminal(completed, result)
                return "completed"
        except V2PersistenceError as error:
            if error.code == "prompt_preparation_dispatch_lease_stale":
                return "lease_lost"
            if error.code in {
                "prompt_preparation_dispatch_stale",
                "prompt_preparation_dispatch_superseded",
            }:
                return self._supersede_stale(dispatch, str(error))
            return self._handle_failure(dispatch, error)
        except Exception as error:  # noqa: BLE001 - bounded retry policy.
            return self._handle_failure(dispatch, error)

    def _supersede_stale(self, dispatch: PromptPreparationDispatchV1, reason: str) -> str:
        try:
            self._dispatches.supersede_owned_fenced(
                dispatch.dispatch_id,
                worker_id=self._worker_id,
                lease_generation=dispatch.lease_generation,
                reason="stale_current_node_snapshot",
                now=self._clock(),
            )
            return "superseded"
        except V2PersistenceError as error:
            if error.code == "prompt_preparation_dispatch_lease_stale":
                return "lease_lost"
            logger.info(
                "Stale prompt-preparation dispatch already reconciled dispatch_id=%s reason=%s",
                dispatch.dispatch_id,
                reason,
            )
            return "superseded"

    def _handle_failure(self, dispatch: PromptPreparationDispatchV1, error: Exception) -> str:
        current = self._dispatches.get(dispatch.dispatch_id)
        # NodePromptPreparationService can atomically publish a failed Node and
        # reconcile its outbox row before returning the exception.  Reopen that
        # same identity for a bounded retry rather than creating a successor.
        if current.status in {"completed", "superseded"}:
            return "completed" if current.status == "completed" else "superseded"
        error_code, retryable = _failure(error)
        next_attempt = dispatch.attempt_no
        if retryable and next_attempt < dispatch.max_attempts:
            delay = min(
                self._base_backoff * (2 ** max(dispatch.attempt_no - 1, 0)),
                self._maximum_backoff,
            )
            try:
                if current.status == "failed":
                    self._dispatches.requeue_failed(
                        dispatch.dispatch_id,
                        next_attempt_at=self._clock() + delay,
                        error_code=error_code,
                        error_message=str(error)[:1_024] or "Prompt preparation failed.",
                        now=self._clock(),
                        node_revision=dispatch.node_revision,
                        operation_id=dispatch.operation_id,
                        context_digest=dispatch.context_digest,
                        source_snapshot=dispatch.source_snapshot or None,
                    )
                else:
                    self._dispatches.schedule_retry(
                        dispatch.dispatch_id,
                        worker_id=self._worker_id,
                        lease_generation=dispatch.lease_generation,
                        next_attempt_at=self._clock() + delay,
                        error_code=error_code,
                        error_message=str(error)[:1_024] or "Prompt preparation failed.",
                        now=self._clock(),
                        node_revision=dispatch.node_revision,
                        operation_id=dispatch.operation_id,
                        context_digest=dispatch.context_digest,
                        source_snapshot=dispatch.source_snapshot or None,
                    )
                return "retried"
            except V2PersistenceError as lease_error:
                if lease_error.code == "prompt_preparation_dispatch_lease_stale":
                    return "lease_lost"
                if lease_error.code in {
                    "prompt_preparation_dispatch_stale",
                    "prompt_preparation_dispatch_state_conflict",
                }:
                    return "superseded"
                raise
        try:
            if current.status == "failed":
                self._notify_terminal(current, error)
                return "failed"
            failed = self._dispatches.fail(
                dispatch.dispatch_id,
                worker_id=self._worker_id,
                lease_generation=dispatch.lease_generation,
                error_code=error_code,
                error_message=str(error)[:1_024] or "Prompt preparation failed.",
                now=self._clock(),
                node_revision=dispatch.node_revision,
                operation_id=dispatch.operation_id,
                context_digest=dispatch.context_digest,
                source_snapshot=dispatch.source_snapshot or None,
            )
            self._notify_terminal(failed, error)
            return "failed"
        except V2PersistenceError as lease_error:
            if lease_error.code == "prompt_preparation_dispatch_lease_stale":
                return "lease_lost"
            raise

    def _notify_terminal(
        self,
        dispatch: PromptPreparationDispatchV1,
        result: object,
    ) -> None:
        """Notify the existing barrier only after a committed terminal result."""

        if self._barrier_callback is None or dispatch.status not in {"completed", "failed"}:
            return
        self._barrier_callback(dispatch, result)


def _failure(error: Exception) -> tuple[str, bool]:
    if isinstance(error, V2PersistenceError):
        return error.code, bool(error.details.get("retryable", False))
    return "prompt_preparation_failed", True


def _error_code(error: Exception) -> str:
    return error.code if isinstance(error, V2PersistenceError) else "prompt_preparation_failed"


__all__ = (
    "AgentCanvasPromptPreparationWorker",
    "PreparationCallback",
    "PreparationContextLoader",
    "PromptPreparationWorkerCycle",
)
