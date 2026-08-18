"""Fenced worker for post-accept guided media confirmation resume work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from app.persistence.agent_canvas_guided_media_resume_repository import (
    AgentCanvasGuidedMediaResumeRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_guided_media_resume import (
    GuidedMediaConfirmationResumeDeliveryV1,
)


_RETRYABLE_LOCAL_CODES = {
    "guided_media_resume_delivery_unavailable",
    "guided_media_resume_lease_unavailable",
    "event_store_busy",
    "event_store_unavailable",
}


@dataclass(frozen=True)
class GuidedMediaResumeCycleResult:
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    failed: int = 0
    lease_lost: int = 0


class GuidedMediaConfirmationResumeWorker:
    """Run exact accepted confirmation callbacks behind renewable ownership."""

    def __init__(
        self,
        repository: AgentCanvasGuidedMediaResumeRepository,
        *,
        resume_confirmation: Callable[[str], object],
        worker_id: str,
        lease_duration: timedelta = timedelta(seconds=60),
        retry_delay: timedelta = timedelta(seconds=2),
        batch_limit: int = 8,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if lease_duration <= timedelta(0) or retry_delay < timedelta(0):
            raise ValueError("Guided media resume timing must be non-negative.")
        if batch_limit < 1:
            raise ValueError("Guided media resume batch limit must be positive.")
        self._repository = repository
        self._resume_confirmation = resume_confirmation
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._retry_delay = retry_delay
        self._batch_limit = batch_limit
        self._clock = clock

    def run_one(self, delivery_id: str) -> GuidedMediaResumeCycleResult:
        claimed = self._repository.claim_due(
            worker_id=self._worker_id,
            now=self._clock(),
            batch_limit=1,
            lease_duration=self._lease_duration,
            delivery_id=delivery_id,
        )
        if not claimed:
            return GuidedMediaResumeCycleResult()
        return self._process(claimed[0])

    def run_once(self) -> GuidedMediaResumeCycleResult:
        claimed = self._repository.claim_due(
            worker_id=self._worker_id,
            now=self._clock(),
            batch_limit=self._batch_limit,
            lease_duration=self._lease_duration,
        )
        total = GuidedMediaResumeCycleResult()
        for delivery in claimed:
            result = self._process(delivery)
            total = GuidedMediaResumeCycleResult(
                claimed=total.claimed + result.claimed,
                completed=total.completed + result.completed,
                retried=total.retried + result.retried,
                failed=total.failed + result.failed,
                lease_lost=total.lease_lost + result.lease_lost,
            )
        return total

    def _process(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
    ) -> GuidedMediaResumeCycleResult:
        guard = _GuidedMediaResumeLeaseGuard(
            self._repository,
            delivery,
            lease_duration=self._lease_duration,
            clock=self._clock,
        )
        try:
            with guard:
                self._resume_confirmation(delivery.confirmation_id)
                guard.assert_current()
            self._repository.complete(guard.delivery, now=self._clock())
            return GuidedMediaResumeCycleResult(claimed=1, completed=1)
        except V2PersistenceError as error:
            if error.code == "stale_guided_media_resume_lease":
                return GuidedMediaResumeCycleResult(claimed=1, lease_lost=1)
            return self._record_failure(guard.delivery, error)
        except Exception as error:  # noqa: BLE001 - accepted work must be contained.
            return self._record_failure(guard.delivery, error)

    def _record_failure(
        self,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        error: BaseException,
    ) -> GuidedMediaResumeCycleResult:
        structured = _safe_error(error)
        try:
            if (
                isinstance(error, V2PersistenceError)
                and error.code in _RETRYABLE_LOCAL_CODES
                and delivery.attempt_no < delivery.max_attempts
            ):
                self._repository.defer(
                    delivery,
                    now=self._clock(),
                    retry_at=self._clock() + self._retry_delay,
                )
                return GuidedMediaResumeCycleResult(claimed=1, retried=1)
            self._repository.fail(delivery, now=self._clock(), error=structured)
            return GuidedMediaResumeCycleResult(claimed=1, failed=1)
        except V2PersistenceError as persistence_error:
            if persistence_error.code == "stale_guided_media_resume_lease":
                return GuidedMediaResumeCycleResult(claimed=1, lease_lost=1)
            raise


class _GuidedMediaResumeLeaseGuard:
    def __init__(
        self,
        repository: AgentCanvasGuidedMediaResumeRepository,
        delivery: GuidedMediaConfirmationResumeDeliveryV1,
        *,
        lease_duration: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._delivery = delivery
        self._lease_duration = lease_duration
        self._clock = clock
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._error: BaseException | None = None

    @property
    def delivery(self) -> GuidedMediaConfirmationResumeDeliveryV1:
        with self._lock:
            return self._delivery

    def __enter__(self) -> "_GuidedMediaResumeLeaseGuard":
        self._thread = Thread(
            target=self._renew_loop,
            name="guided-media-resume-lease",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._renewal_interval_seconds + 1)
        if exc_type is None:
            self.assert_current()

    def assert_current(self) -> None:
        if self._error is not None:
            raise V2PersistenceError(
                "stale_guided_media_resume_lease",
                "Guided media resume lease renewal failed.",
                stage="agent_canvas_guided_media_resume_worker",
            ) from self._error

    @property
    def _renewal_interval_seconds(self) -> float:
        return max(self._lease_duration.total_seconds() / 3, 0.01)

    def _renew_loop(self) -> None:
        while not self._stop.wait(self._renewal_interval_seconds):
            try:
                with self._lock:
                    self._delivery = self._repository.renew(
                        self._delivery,
                        now=self._clock(),
                        lease_duration=self._lease_duration,
                    )
            except BaseException as error:
                self._error = error
                self._stop.set()
                return


def _safe_error(error: BaseException) -> CanvasNodeErrorV2:
    if isinstance(error, V2PersistenceError):
        return CanvasNodeErrorV2(
            code=error.code,
            message=str(error),
            retryable=error.code in _RETRYABLE_LOCAL_CODES,
        )
    return CanvasNodeErrorV2(
        code="guided_media_resume_failed",
        message="Guided media confirmation resume failed.",
        retryable=False,
    )
