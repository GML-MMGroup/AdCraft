"""Bounded internal NDJSON client for the private Pi Agent runtime."""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any, Callable

import httpx
from pydantic import ValidationError

from app.schemas.agent_runtime import AgentRunRequest, AgentRuntimeEvent, AgentRuntimeHealth
from app.services.v2_agent_runtime_manifest import V2AgentRuntimeManifestService


_TERMINAL_EVENTS = {"run_completed", "run_failed", "run_cancelled"}


class PiAgentRuntimeError(RuntimeError):
    """Stable internal Agent runtime client failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


class PiAgentRuntimeClient:
    """Validate the complete internal protocol before returning Agent events."""

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        protocol_version: str = "1",
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 30.0,
        run_timeout_seconds: float = 120.0,
        max_event_bytes: int = 65_536,
        max_stream_bytes: int = 1_048_576,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._internal_token = internal_token
        self._protocol_version = protocol_version
        self._run_timeout_seconds = run_timeout_seconds
        self._max_event_bytes = max_event_bytes
        self._max_stream_bytes = max_stream_bytes
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=read_timeout_seconds,
                pool=connect_timeout_seconds,
            ),
            transport=transport,
        )

    def health(self) -> AgentRuntimeHealth:
        try:
            response = self._client.get(
                f"{self._base_url}/internal/v1/health",
                headers={"authorization": f"Bearer {self._internal_token}"},
            )
            response.raise_for_status()
            health = AgentRuntimeHealth.model_validate(response.json())
        except (httpx.HTTPError, OSError, ValueError, ValidationError) as error:
            raise PiAgentRuntimeError(
                "agent_runtime_unavailable",
                "Agent runtime health is unavailable.",
                retryable=True,
            ) from error
        expected = V2AgentRuntimeManifestService().expected()
        actual = {
            field: getattr(health, field)
            for field in type(expected).model_fields
        }
        if actual != expected.model_dump(mode="python"):
            raise _protocol_error()
        return health

    def run(
        self,
        request: AgentRunRequest,
        *,
        on_event: Callable[[AgentRuntimeEvent], None] | None = None,
    ) -> tuple[AgentRuntimeEvent, ...]:
        if request.protocol_version != self._protocol_version:
            raise _protocol_error()
        payload = request.model_dump_json().encode("utf-8")
        events: list[AgentRuntimeEvent] = []
        total_bytes = 0
        terminal_count = 0
        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/internal/v1/agent-runs",
                content=payload,
                headers={
                    "authorization": f"Bearer {self._internal_token}",
                    "content-type": "application/json",
                    "accept": "application/x-ndjson",
                },
                timeout=self._run_timeout_seconds,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    line_bytes = line.encode("utf-8")
                    total_bytes += len(line_bytes) + 1
                    if (
                        len(line_bytes) > self._max_event_bytes
                        or total_bytes > self._max_stream_bytes
                    ):
                        raise PiAgentRuntimeError(
                            "agent_stream_backpressure_exceeded",
                            "Agent runtime stream exceeded its byte budget.",
                        )
                    if not line:
                        continue
                    event = _parse_event(line)
                    expected_seq = len(events) + 1
                    if (
                        event.protocol_version != self._protocol_version
                        or event.run_id != request.run_id
                        or event.agent_name != request.agent_name
                        or event.seq != expected_seq
                    ):
                        raise _protocol_error()
                    if event.event_type in _TERMINAL_EVENTS:
                        terminal_count += 1
                    elif terminal_count:
                        raise _protocol_error()
                    events.append(event)
                    if on_event is not None:
                        on_event(event)
        except PiAgentRuntimeError:
            raise
        except (httpx.HTTPError, OSError) as error:
            raise PiAgentRuntimeError(
                "agent_runtime_unavailable",
                "Agent runtime is unavailable.",
                retryable=True,
            ) from error
        if terminal_count != 1 or not events or events[-1].event_type not in _TERMINAL_EVENTS:
            raise _protocol_error()
        return tuple(events)

    def cancel(self, run_id: str, *, reason: str = "client_cancelled") -> dict[str, Any]:
        try:
            response = self._client.post(
                f"{self._base_url}/internal/v1/agent-runs/{run_id}/cancel",
                json={"reason": reason},
                headers={"authorization": f"Bearer {self._internal_token}"},
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            raise PiAgentRuntimeError(
                "agent_runtime_unavailable",
                "Agent runtime cancellation failed.",
                retryable=True,
            ) from error
        if not isinstance(result, dict):
            raise _protocol_error()
        return result

    def close(self) -> None:
        self._client.close()


def _parse_event(line: str) -> AgentRuntimeEvent:
    try:
        return AgentRuntimeEvent.model_validate_json(line)
    except ValidationError as error:
        raise _protocol_error() from error


def terminal_event(events: Sequence[AgentRuntimeEvent]) -> AgentRuntimeEvent:
    if not events or events[-1].event_type not in _TERMINAL_EVENTS:
        raise _protocol_error()
    return events[-1]


def _protocol_error() -> PiAgentRuntimeError:
    return PiAgentRuntimeError(
        "agent_protocol_mismatch",
        "Agent runtime protocol validation failed.",
    )
