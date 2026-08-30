"""Renewable fenced lease scope for one prompt-preparation dispatch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Event, Thread

from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.errors import V2PersistenceError


HeartbeatWait = Callable[[Event, float], bool]


def wait_for_prompt_preparation_heartbeat(stop: Event, interval_seconds: float) -> bool:
    return stop.wait(interval_seconds)


class PromptPreparationLeaseScope:
    """Renew one dispatch lease while the role compiler is running."""

    def __init__(
        self,
        dispatches: AgentCanvasPromptPreparationDispatchRepository,
        *,
        dispatch_id: str,
        worker_id: str,
        lease_generation: int,
        lease_duration: timedelta,
        clock: Callable[[], datetime],
        heartbeat_wait: HeartbeatWait = wait_for_prompt_preparation_heartbeat,
    ) -> None:
        self._dispatches = dispatches
        self._dispatch_id = dispatch_id
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
            name="agent-canvas-prompt-preparation-lease",
            daemon=True,
        )

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def __enter__(self) -> Callable[[], None]:
        self.assert_owned()
        self._thread.start()
        return self.assert_owned

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()

    def assert_owned(self) -> None:
        if self._lease_lost.is_set():
            raise _stale_lease()
        try:
            self._dispatches.assert_owned(
                self._dispatch_id,
                worker_id=self._worker_id,
                lease_generation=self._lease_generation,
                now=self._clock(),
            )
        except V2PersistenceError as error:
            if error.code == "prompt_preparation_dispatch_lease_stale":
                self._lease_lost.set()
            raise

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=min(self._interval_seconds + 0.1, 1.0))

    def _renew_until_stopped(self) -> None:
        while not self._heartbeat_wait(self._stop, self._interval_seconds):
            try:
                self._dispatches.renew_lease(
                    self._dispatch_id,
                    worker_id=self._worker_id,
                    lease_generation=self._lease_generation,
                    now=self._clock(),
                    lease_duration=self._lease_duration,
                )
            except Exception:  # noqa: BLE001 - ownership is checked at publication.
                self._lease_lost.set()
                return


def _stale_lease() -> V2PersistenceError:
    return V2PersistenceError(
        "prompt_preparation_dispatch_lease_stale",
        "Prompt-preparation dispatch lease has been superseded or expired.",
        stage="prompt_preparation_worker",
    )


__all__ = (
    "HeartbeatWait",
    "PromptPreparationLeaseScope",
    "wait_for_prompt_preparation_heartbeat",
)
