"""Bounded typed worker for durable Agent Canvas post-Ready effects."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

from app.persistence.agent_canvas_post_ready_repository import (
    AgentCanvasPostReadyEffectRepository,
)
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime_authority import CanvasPostReadyEffectV2


PostReadyHandler = Callable[[CanvasPostReadyEffectV2], object]


@dataclass(frozen=True)
class PostReadyEffectCycle:
    claimed: int
    completed: int
    retried: int
    failed: int


class AgentCanvasPostReadyEffectWorker:
    """Execute only explicitly registered non-media Ready effects."""

    def __init__(
        self,
        repository: AgentCanvasPostReadyEffectRepository,
        *,
        handlers: Mapping[str, PostReadyHandler],
        worker_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        batch_limit: int = 8,
        lease_duration: timedelta = timedelta(seconds=90),
        base_backoff: timedelta = timedelta(seconds=5),
        max_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._handlers = dict(handlers)
        self._worker_id = worker_id
        self._clock = clock
        self._batch_limit = batch_limit
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._max_attempts = max_attempts

    def run_once(self) -> PostReadyEffectCycle:
        claimed = self._repository.claim_due(
            worker_id=self._worker_id,
            now=self._clock(),
            batch_limit=self._batch_limit,
            lease_duration=self._lease_duration,
        )
        completed = retried = failed = 0
        for effect in claimed:
            handler = self._handlers.get(effect.effect_type)
            stopped = Event()
            lease_lost = Event()
            interval = max(self._lease_duration.total_seconds() / 3, 0.01)

            def renew() -> None:
                while not stopped.wait(interval):
                    try:
                        self._repository.renew(
                            effect,
                            now=self._clock(),
                            lease_duration=self._lease_duration,
                        )
                    except Exception:  # noqa: BLE001 - ownership is checked at finish.
                        lease_lost.set()
                        return

            renewer = Thread(
                target=renew,
                name="agent-canvas-post-ready-lease",
                daemon=True,
            )
            renewer.start()
            try:
                if handler is None:
                    raise LookupError("Post-Ready effect handler is not registered.")
                handler(effect)
                if lease_lost.is_set():
                    raise RuntimeError("Post-Ready effect lease was lost.")
            except Exception as error:  # noqa: BLE001 - effects are isolated.
                detail = CanvasNodeErrorV2(
                    code=(
                        "post_ready_effect_handler_missing"
                        if handler is None
                        else "post_ready_effect_failed"
                    ),
                    message=str(error)[:1024] or "Post-Ready effect failed.",
                    retryable=handler is not None,
                )
                if handler is None or effect.attempt_no + 1 >= self._max_attempts:
                    self._repository.fail(effect, now=self._clock(), error=detail)
                    failed += 1
                else:
                    now = self._clock()
                    self._repository.retry(
                        effect,
                        now=now,
                        retry_at=now + self._base_backoff * (2**effect.attempt_no),
                        error=detail,
                    )
                    retried += 1
            else:
                self._repository.complete(effect, now=self._clock())
                completed += 1
            finally:
                stopped.set()
                renewer.join(timeout=min(interval, 1.0))
        return PostReadyEffectCycle(
            claimed=len(claimed),
            completed=completed,
            retried=retried,
            failed=failed,
        )
