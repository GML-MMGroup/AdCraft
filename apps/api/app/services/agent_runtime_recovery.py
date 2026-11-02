"""Bounded availability waits for durable Agent authoring work, not media retries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.services.pi_agent_runtime_client import PiAgentRuntimeClient, PiAgentRuntimeError

RUNTIME_WAIT_MESSAGE = (
    "Waiting for the Agent runtime to recover. This task will resume automatically."
)
RUNTIME_WAIT_EXPIRED_MESSAGE = (
    "The Agent runtime did not recover within 30 minutes. Restore the service and retry this task."
)
RUNTIME_WAIT_LIMIT = timedelta(minutes=30)


@dataclass(frozen=True)
class RuntimeRecoveryWait:
    started_at: datetime
    count: int
    available_at: datetime


def runtime_recovery_wait(
    *,
    now: datetime,
    started_at: datetime | None,
    count: int,
) -> RuntimeRecoveryWait | None:
    start = started_at or now
    if now >= start + RUNTIME_WAIT_LIMIT:
        return None
    delay = timedelta(seconds=min(5 * 2 ** min(count, 4), 60))
    return RuntimeRecoveryWait(start, count + 1, min(now + delay, start + RUNTIME_WAIT_LIMIT))


def recoverable_runtime_outage(error: Exception) -> bool:
    """Only an unavailable runtime with proof of no model submission can wait."""

    if (
        isinstance(error, V2PersistenceError)
        and error.code == "agent_runtime_unavailable"
        and isinstance(error.__cause__, PiAgentRuntimeError)
    ):
        error = error.__cause__
    return (
        isinstance(error, PiAgentRuntimeError)
        and error.code == "agent_runtime_unavailable"
        and error.retryable
        and error.details.get("model_submission_count") == 0
        and error.details.get("failure_boundary")
        in {
            "runtime_unreachable",
            "runtime_config_unreachable",
            "runtime_readiness",
        }
    )


def require_agent_runtime_ready(settings: Settings) -> None:
    """A bounded health-only probe; never submit a model or expose private diagnostics."""

    client = PiAgentRuntimeClient(
        base_url=settings.agent_runtime_base_url,
        internal_token=settings.agent_runtime_internal_token or "",
        protocol_version=settings.agent_runtime_protocol_version,
        connect_timeout_seconds=2,
        read_timeout_seconds=2,
    )
    try:
        client.health()
    except PiAgentRuntimeError as error:
        cause = error.__cause__
        if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code < 500:
            raise PiAgentRuntimeError(
                "agent_protocol_mismatch",
                "Agent runtime readiness was rejected. Check the internal runtime configuration.",
                retryable=False,
            ) from error
        if error.code != "agent_runtime_unavailable" or not isinstance(
            cause, (httpx.HTTPError, OSError)
        ):
            raise
        raise PiAgentRuntimeError(
            "agent_runtime_unavailable",
            RUNTIME_WAIT_MESSAGE,
            retryable=True,
            details={"model_submission_count": 0, "failure_boundary": "runtime_readiness"},
        ) from error
    finally:
        client.close()
