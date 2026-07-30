"""Durable, idempotent execution for Agent Canvas Pi invocations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Literal, Mapping
from uuid import uuid4

from app.core.config import Settings
from app.persistence.agent_run_repository import (
    AgentRunRecord,
    AgentRunRepository,
    AgentRunRepositoryError,
)
from app.persistence.database import create_v2_database
from app.schemas.agent_runtime import AgentRunRequest, AgentRuntimeEvent
from app.services.pi_agent_runtime_client import (
    PiAgentRuntimeClient,
    PiAgentRuntimeError,
)
from app.services.v2_agent_event_projector import V2AgentEventProjector


_TERMINAL_STATUS_BY_EVENT = {
    "run_completed": "completed",
    "run_failed": "failed",
    "run_cancelled": "cancelled",
}
_SAFE_AUDIT_IDENTITY_FIELDS = {
    "agent_name",
    "conversation_id",
    "execution_id",
    "node_id",
    "node_revision",
    "operation",
    "turn_id",
    "workflow_id",
}
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DurablePiRunResult:
    """A terminal Pi result that was executed once or replayed from SQLite."""

    run_id: str
    status: Literal["completed", "failed", "cancelled"]
    terminal_payload: dict[str, Any]
    last_event_seq: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class DurablePiRunIdentity:
    """Stable identifiers derived from a canonical Agent Canvas invocation scope."""

    request_id: str
    run_id: str
    digest: str
    audit_metadata: dict[str, Any]


def derive_durable_pi_run_identity(
    identity_fields: Mapping[str, str | int],
) -> DurablePiRunIdentity:
    """Create bounded stable IDs without persisting volatile or sensitive input."""

    canonical = {
        str(key): value
        for key, value in sorted(identity_fields.items())
        if isinstance(value, (str, int))
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    readable_scope = {
        key: value for key, value in canonical.items() if key in _SAFE_AUDIT_IDENTITY_FIELDS
    }
    return DurablePiRunIdentity(
        request_id=f"request_{digest}",
        run_id=f"arun_{digest}",
        digest=digest,
        audit_metadata={
            "request_identity_digest": digest,
            "invocation_scope": readable_scope,
        },
    )


class DurablePiRunService:
    """Persist a Pi invocation before the Sidecar can submit structured output."""

    def __init__(
        self,
        *,
        settings: Settings,
        client: PiAgentRuntimeClient,
    ) -> None:
        self._settings = settings
        self._client = client

    def run(
        self,
        request: AgentRunRequest,
        *,
        identity_fields: Mapping[str, str | int],
        model_id: str | None = None,
    ) -> DurablePiRunResult:
        """Run or replay one stable Agent invocation through the existing repository."""

        identity = derive_durable_pi_run_identity(identity_fields)
        request = request.model_copy(
            update={
                "request_id": identity.request_id,
                "run_id": identity.run_id,
                "audit_metadata": {
                    **request.audit_metadata,
                    **identity.audit_metadata,
                },
            }
        )
        database = create_v2_database(self._settings.media_data_dir)
        repository = AgentRunRepository(database)
        event_projector = V2AgentEventProjector(self._settings.media_data_dir)
        lease_owner_id = f"python_{uuid4().hex}"
        lease_duration = max(60.0, self._settings.agent_runtime_run_timeout_seconds * 2)
        owns_lease = False
        lease_generation = 0

        def persist_event(event: AgentRuntimeEvent) -> None:
            nonlocal lease_generation
            if event.event_type == "heartbeat":
                renewed = repository.acquire_lease(
                    request.run_id,
                    lease_owner_id=lease_owner_id,
                    lease_duration_seconds=lease_duration,
                )
                lease_generation = renewed.lease_generation
            repository.record_event_seq(
                request.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                seq=event.seq,
            )
            event_projector.consume(
                event,
                workflow_id=getattr(request.context, "workflow_id", None),
                model_id=model_id,
            )

        try:
            record, created = repository.create_or_load(
                request,
                lease_owner_id=lease_owner_id,
                lease_duration_seconds=lease_duration,
            )
            owns_lease = created
            lease_generation = record.lease_generation
            if not created:
                if record.status in {"completed", "failed", "cancelled"}:
                    return self._replayed_result(record)
                if _has_live_lease(record):
                    raise PiAgentRuntimeError(
                        "agent_run_in_progress",
                        "The matching Agent action is already running.",
                        retryable=True,
                    )
                record = repository.acquire_lease(
                    record.run_id,
                    lease_owner_id=lease_owner_id,
                    lease_duration_seconds=lease_duration,
                )
                owns_lease = True
                lease_generation = record.lease_generation
                request = request.model_copy(update={"run_id": record.run_id})

            outcome = self._client.run(request, on_event=persist_event)
            terminal = outcome.terminal_event
            status = _TERMINAL_STATUS_BY_EVENT.get(terminal.event_type)
            if status is None:
                raise PiAgentRuntimeError(
                    "agent_protocol_mismatch",
                    "Agent runtime did not emit a terminal event.",
                )
            repository.finish(
                request.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                status=status,
                terminal_result=terminal.payload,
                audit_metadata=_safe_audit_metadata(terminal.payload),
                safe_error_code=(
                    _safe_error_code(terminal.payload) if status != "completed" else None
                ),
            )
            owns_lease = False
            result = DurablePiRunResult(
                run_id=request.run_id,
                status=status,
                terminal_payload=dict(terminal.payload),
                last_event_seq=outcome.last_seq,
                replayed=False,
            )
            if status != "completed":
                self._raise_terminal_error(result)
            return result
        except PiAgentRuntimeError as error:
            self._log_structured_rejection(request, error)
            if owns_lease:
                self._finish_failed(
                    repository,
                    request.run_id,
                    lease_owner_id,
                    lease_generation,
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                )
            raise
        except AgentRunRepositoryError as error:
            self._log_structured_rejection(
                request,
                PiAgentRuntimeError(error.code, error.message),
            )
            if owns_lease:
                self._finish_failed(
                    repository,
                    request.run_id,
                    lease_owner_id,
                    lease_generation,
                    code=error.code,
                    message=error.message,
                    retryable=False,
                )
            raise PiAgentRuntimeError(error.code, error.message) from error
        except Exception as error:
            if owns_lease:
                self._finish_failed(
                    repository,
                    request.run_id,
                    lease_owner_id,
                    lease_generation,
                    code="agent_runtime_unavailable",
                    message="Agent runtime is unavailable.",
                    retryable=True,
                )
            raise PiAgentRuntimeError(
                "agent_runtime_unavailable",
                "Agent runtime is unavailable.",
                retryable=True,
            ) from error
        finally:
            database.dispose()

    @staticmethod
    def _log_structured_rejection(
        request: AgentRunRequest,
        error: PiAgentRuntimeError,
    ) -> None:
        if error.code != "agent_structured_output_invalid":
            return
        scope = request.audit_metadata.get("invocation_scope")
        safe_scope = scope if isinstance(scope, Mapping) else {}
        _LOGGER.warning(
            "durable_pi_structured_rejection run_id=%s workflow_id=%s "
            "conversation_id=%s execution_id=%s node_id=%s agent_name=%s "
            "operation=%s stage=%s safe_error_code=%s exception_class=%s retryable=%s",
            request.run_id,
            _safe_scope_value(safe_scope, "workflow_id"),
            _safe_scope_value(safe_scope, "conversation_id"),
            _safe_scope_value(safe_scope, "execution_id"),
            _safe_scope_value(safe_scope, "node_id"),
            request.agent_name,
            request.operation,
            "structured_submission",
            error.code,
            error.__class__.__name__,
            error.retryable,
        )

    @staticmethod
    def _replayed_result(record: AgentRunRecord) -> DurablePiRunResult:
        payload = dict(record.terminal_result or {})
        result = DurablePiRunResult(
            run_id=record.run_id,
            status=record.status,
            terminal_payload=payload,
            last_event_seq=record.last_event_seq,
            replayed=True,
        )
        if result.status != "completed":
            DurablePiRunService._raise_terminal_error(result, record.safe_error_code)
        return result

    @staticmethod
    def _raise_terminal_error(
        result: DurablePiRunResult,
        safe_error_code: str | None = None,
    ) -> None:
        payload = result.terminal_payload
        raise PiAgentRuntimeError(
            safe_error_code or _safe_error_code(payload),
            _safe_error_message(payload),
            retryable=bool(payload.get("retryable")),
        )

    @staticmethod
    def _finish_failed(
        repository: AgentRunRepository,
        run_id: str,
        lease_owner_id: str,
        lease_generation: int,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        try:
            repository.finish(
                run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                status="failed",
                terminal_result={
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                },
                safe_error_code=code,
                audit_metadata={
                    "durable_pi_stage": "runtime_failure",
                    "safe_error_code": code,
                },
            )
        except AgentRunRepositoryError:
            return


def _has_live_lease(record: AgentRunRecord) -> bool:
    return bool(
        record.lease_owner_id
        and record.lease_expires_at
        and record.lease_expires_at > datetime.now(timezone.utc)
    )


def _safe_scope_value(scope: Mapping[str, Any], key: str) -> str | int | None:
    value = scope.get(key)
    return value if isinstance(value, (str, int)) else None


def _safe_audit_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    audit = payload.get("audit")
    return dict(audit) if isinstance(audit, dict) else {}


def _safe_error_code(payload: Mapping[str, Any]) -> str:
    value = payload.get("code")
    return str(value) if isinstance(value, str) and value else "agent_runtime_unavailable"


def _safe_error_message(payload: Mapping[str, Any]) -> str:
    value = payload.get("message")
    return str(value) if isinstance(value, str) and value else "Agent runtime failed."
