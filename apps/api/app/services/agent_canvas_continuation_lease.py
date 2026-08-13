"""Private renewable lease scope for one continuation delivery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Event, Thread

from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.errors import V2PersistenceError


HeartbeatWait = Callable[[Event, float], bool]


def wait_for_heartbeat(stop: Event, interval_seconds: float) -> bool:
    """Wait for the next renewal interval or until the scope stops."""

    return stop.wait(interval_seconds)


class ContinuationLeaseScope:
    """Renew and cooperatively guard one claimed continuation lease."""

    def __init__(
        self,
        outbox: AgentCanvasContinuationOutboxRepository,
        *,
        continuation_id: str,
        worker_id: str,
        lease_generation: int,
        lease_duration: timedelta,
        clock: Callable[[], datetime],
        heartbeat_wait: HeartbeatWait = wait_for_heartbeat,
    ) -> None:
        self._outbox = outbox
        self._continuation_id = continuation_id
        self._worker_id = worker_id
        self._lease_generation = lease_generation
        self._lease_duration = lease_duration
        self._clock = clock
        self._heartbeat_wait = heartbeat_wait
        self._stop = Event()
        self._lease_lost = Event()
        self._interval_seconds = max(lease_duration.total_seconds() / 3, 0.01)
        self._thread = Thread(
            target=self._renew_until_stopped,
            name="agent-canvas-continuation-lease",
            daemon=True,
        )

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    @property
    def heartbeat_alive(self) -> bool:
        return self._thread.is_alive()

    def __enter__(self) -> Callable[[], None]:
        self.assert_owned()
        self._thread.start()
        return self.assert_owned

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()

    def assert_owned(self) -> None:
        if self._lease_lost.is_set():
            raise _stale_lease_error()
        try:
            self._outbox.assert_owned(
                self._continuation_id,
                worker_id=self._worker_id,
                lease_generation=self._lease_generation,
                now=self._clock(),
            )
        except V2PersistenceError as error:
            if error.code == "continuation_lease_stale":
                self._lease_lost.set()
            raise

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=min(self._interval_seconds + 0.1, 1.0))

    def _renew_until_stopped(self) -> None:
        while not self._heartbeat_wait(self._stop, self._interval_seconds):
            try:
                self._outbox.renew_lease(
                    self._continuation_id,
                    worker_id=self._worker_id,
                    lease_generation=self._lease_generation,
                    now=self._clock(),
                    lease_duration=self._lease_duration,
                )
            except Exception:  # noqa: BLE001 - ownership loss is worker-local.
                self._lease_lost.set()
                return


def _stale_lease_error() -> V2PersistenceError:
    return V2PersistenceError(
        "continuation_lease_stale",
        "Continuation lease has been superseded or expired.",
    )
