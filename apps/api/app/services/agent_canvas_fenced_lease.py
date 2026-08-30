"""Renewable fencing guards for long Agent Canvas node operations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import TypeVar

from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_runtime import NodeExecutionLeaseV2


T = TypeVar("T")
Clock = Callable[[], datetime]


class NodeLeaseService:
    """Claim, renew, assert, and complete one generation-fenced lease."""

    def __init__(
        self,
        runtime: AgentCanvasRuntimeRepository,
        *,
        ttl: timedelta = timedelta(seconds=60),
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("Lease TTL must be positive.")
        self._runtime = runtime
        self._ttl = ttl
        self._clock = clock

    @property
    def renewal_interval_seconds(self) -> float:
        return max(self._ttl.total_seconds() / 3, 0.01)

    def claim(self, execution_id: str, node_id: str, *, owner_id: str) -> NodeExecutionLeaseV2:
        lease = self._runtime.claim_lease(
            execution_id,
            node_id,
            owner_id=owner_id,
            now=self._clock(),
            ttl=self._ttl,
        )
        if lease is None:
            raise V2PersistenceError(
                "execution_lease_unavailable",
                "Execution lease is owned by another worker.",
                stage="agent_canvas_fenced_lease",
            )
        return lease

    def renew(self, lease: NodeExecutionLeaseV2) -> NodeExecutionLeaseV2:
        return self._runtime.renew_lease(
            lease,
            now=self._clock(),
            ttl=self._ttl,
        )

    def assert_current(self, lease: NodeExecutionLeaseV2) -> None:
        self._runtime.assert_current_lease(lease, now=self._clock())

    def complete(self, lease: NodeExecutionLeaseV2) -> None:
        if not self._runtime.complete_lease(lease, now=self._clock()):
            raise V2PersistenceError(
                "stale_execution_lease",
                "Execution lease ownership was lost.",
                stage="agent_canvas_fenced_lease",
            )

    def guard(self, lease: NodeExecutionLeaseV2) -> "NodeLeaseGuard":
        return NodeLeaseGuard(self, lease)


class NodeLeaseGuard(AbstractContextManager["NodeLeaseGuard"]):
    """Renew ownership in the background while one blocking operation runs."""

    def __init__(self, service: NodeLeaseService, lease: NodeExecutionLeaseV2) -> None:
        self._service = service
        self._lease = lease
        self._stop = Event()
        self._thread: Thread | None = None
        self._error: BaseException | None = None
        self._lock = Lock()

    @property
    def lease(self) -> NodeExecutionLeaseV2:
        with self._lock:
            return self._lease

    def heartbeat(self) -> NodeExecutionLeaseV2:
        with self._lock:
            self._lease = self._service.renew(self._lease)
            return self._lease

    def assert_current(self) -> None:
        if self._error is not None:
            raise V2PersistenceError(
                "stale_execution_lease",
                "Execution lease renewal failed.",
                stage="agent_canvas_fenced_lease",
            ) from self._error
        self._service.assert_current(self.lease)

    def run(self, operation: Callable[[], T]) -> T:
        with self:
            result = operation()
            self.assert_current()
            return result

    def __enter__(self) -> "NodeLeaseGuard":
        self.assert_current()
        self._thread = Thread(target=self._renew_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._service.renewal_interval_seconds + 1)
        if exc_type is None:
            self.assert_current()

    def _renew_loop(self) -> None:
        while not self._stop.wait(self._service.renewal_interval_seconds):
            try:
                self.heartbeat()
            except BaseException as error:
                self._error = error
                self._stop.set()
                return
