"""Durable, idempotent execution for Agent Canvas Pi invocations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from app.core.config import Settings
from app.persistence.agent_run_repository import (
    AgentRunRecord,
    AgentRunRepository,
    AgentRunRepositoryError,
)
from app.persistence.database import create_v2_database
from app.schemas.agent_runtime import (
    AgentPresentationDeltaV1,
    AgentRunRequest,
    AgentRuntimeEvent,
)
from app.services.pi_agent_runtime_client import (
    PiAgentRuntimeClient,
    PiAgentRuntimeError,
)
from app.services.v2_agent_event_projector import (
    V2AgentEventProjector,
    safe_agent_transport_audit,
)
from app.services.agent_operation_policy import (
    AgentOperationPolicyError,
    validate_agent_run_operation_policy,
)

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
_PRE_SUBMISSION_FAILURE_CODES = {
    "agent_context_input_missing",
    "agent_model_capability_mismatch",
    "agent_model_incompatible",
    "agent_model_policy_mismatch",
    "agent_model_unavailable",
    "agent_operation_not_allowed",
    "agent_prompt_input_registry_invalid",
    "provider_credentials_invalid",
    "provider_credentials_missing",
}
_PROVIDER_FAILURE_CODES = {
    "agent_provider_timeout",
    "agent_provider_transport_failed",
}
_STRUCTURED_FAILURE_CODES = {
    "agent_contract_validation_failed",
    "agent_structured_output_invalid",
}
_SAFE_FAILURE_MESSAGES = {
    "agent_contract_validation_failed": "Agent contract validation failed.",
    "agent_context_input_missing": "Agent Prompt input is incomplete.",
    "agent_deadline_exceeded": "Agent run deadline exceeded.",
    "agent_model_capability_mismatch": ("Agent model capability does not satisfy this operation."),
    "agent_model_incompatible": "Agent model is incompatible with this operation.",
    "agent_model_policy_mismatch": "Agent model policy rejected this operation.",
    "agent_model_unavailable": "Agent model is unavailable.",
    "agent_operation_not_allowed": "Agent operation is not allowed.",
    "agent_protocol_mismatch": "Agent runtime protocol validation failed.",
    "agent_publication_failed": "Agent result publication failed.",
    "agent_provider_timeout": "Agent provider request timed out.",
    "agent_provider_transport_failed": "Agent provider transport failed.",
    "agent_run_cancelled": "Agent run was cancelled.",
    "agent_runtime_unavailable": "Agent runtime is unavailable.",
    "agent_stream_backpressure_exceeded": ("Agent runtime stream exceeded its byte budget."),
    "agent_structured_output_invalid": "Agent structured output was invalid.",
    "agent_target_revision_conflict": "Agent target revision changed.",
    "agent_tool_not_allowed": "Agent tool is not allowed.",
    "provider_credentials_invalid": "Agent provider credentials are invalid.",
    "provider_credentials_missing": "Agent provider credentials are unavailable.",
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
        model_ref: str | None = None,
        on_dispatch_owned: Callable[[AgentRunRequest], None] | None = None,
        on_presentation: Callable[[AgentPresentationDeltaV1], None] | None = None,
    ) -> DurablePiRunResult:
        """Run or replay one stable Agent invocation through the existing repository."""

        try:
            validate_agent_run_operation_policy(request)
        except AgentOperationPolicyError as error:
            raise PiAgentRuntimeError(
                "agent_model_policy_mismatch",
                "Agent request policy does not match the canonical operation registry.",
                retryable=False,
            ) from error
        identity = derive_durable_pi_run_identity(identity_fields)
        request = request.model_copy(
            update={
                "request_id": identity.request_id,
                "run_id": identity.run_id,
                "audit_metadata": {
                    **request.audit_metadata,
                    **identity.audit_metadata,
                    "model_policy_id": request.model_policy_id,
                    "result_contract_name": request.contract_name,
                    "context_snapshot_id": request.context_snapshot_id,
                    "max_handoffs": request.policy.max_handoffs,
                    **({"model_ref": model_ref} if model_ref is not None else {}),
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
            if event.event_type == "run_completed":
                repository.stage_completed_result(
                    request.run_id,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    seq=event.seq,
                    terminal_result=dict(event.payload),
                    attempt_metadata=_safe_audit_metadata(event.payload),
                )
            else:
                repository.record_event_seq(
                    request.run_id,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    seq=event.seq,
                    operation_stage=_operation_stage_for_event(event.event_type),
                )
            projected_event = event
            if event.event_type in {"run_failed", "run_cancelled"}:
                projected_event = event.model_copy(
                    update={
                        "payload": _safe_terminal_failure_payload(
                            event.payload,
                            operation=request.operation,
                        )
                    }
                )
            try:
                event_projector.consume(
                    projected_event,
                    workflow_id=getattr(request.context, "workflow_id", None),
                    model_id=model_ref,
                )
            except Exception as error:
                if event.event_type == "run_completed":
                    raise PiAgentRuntimeError(
                        "agent_publication_failed",
                        _safe_error_message_for_code("agent_publication_failed"),
                        retryable=True,
                        details=_publication_failure_audit(
                            request.operation,
                            _safe_audit_metadata(event.payload),
                        ),
                    ) from error
                if event.event_type in {"run_failed", "run_cancelled"}:
                    failure_payload = projected_event.payload
                    raise PiAgentRuntimeError(
                        _safe_error_code(failure_payload),
                        _safe_error_message_for_code(_safe_error_code(failure_payload)),
                        retryable=bool(failure_payload.get("retryable")),
                        details=_safe_audit_metadata(failure_payload),
                    ) from error
                raise

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
                request = request.model_copy(
                    update={
                        "run_id": record.run_id,
                        "deadline_at": record.deadline_at or request.deadline_at,
                    }
                )
                if record.completed_result_identity is not None:
                    replayed = self._replay_staged_result(
                        repository,
                        event_projector,
                        record,
                        lease_owner_id=lease_owner_id,
                        lease_generation=lease_generation,
                        request=request,
                        model_ref=model_ref,
                    )
                    owns_lease = False
                    return replayed

            if on_dispatch_owned is not None:
                on_dispatch_owned(request)

            def deliver_presentation(presentation: AgentPresentationDeltaV1) -> None:
                if on_presentation is None or request.presentation_channel != presentation.channel:
                    return
                try:
                    on_presentation(presentation)
                except Exception:
                    _LOGGER.warning(
                        "Presentation delivery callback failed; preserving Agent operation.",
                        extra={"run_id": request.run_id},
                    )

            if on_presentation is None:
                outcome = self._client.run(request, on_event=persist_event)
            else:
                outcome = self._client.run(
                    request,
                    on_event=persist_event,
                    on_presentation=deliver_presentation,
                )
            terminal = outcome.terminal_event
            status = _TERMINAL_STATUS_BY_EVENT.get(terminal.event_type)
            if status is None:
                raise PiAgentRuntimeError(
                    "agent_protocol_mismatch",
                    "Agent runtime did not emit a terminal event.",
                )
            if status == "completed":
                staged = repository.load(request.run_id)
                if staged.completed_result_identity is None:
                    persist_event(terminal)
                terminal_payload = dict(terminal.payload)
                terminal_audit = _safe_audit_metadata(terminal.payload)
            else:
                terminal_payload = _safe_terminal_failure_payload(
                    terminal.payload,
                    operation=request.operation,
                )
                terminal_audit = dict(terminal_payload["audit"])
            repository.finish(
                request.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                status=status,
                terminal_result=terminal_payload,
                audit_metadata=terminal_audit,
                safe_error_code=(
                    _safe_error_code(terminal_payload) if status != "completed" else None
                ),
            )
            owns_lease = False
            result = DurablePiRunResult(
                run_id=request.run_id,
                status=status,
                terminal_payload=terminal_payload,
                last_event_seq=outcome.last_seq,
                replayed=False,
            )
            if status != "completed":
                self._raise_terminal_error(result)
            return result
        except PiAgentRuntimeError as error:
            safe_error = _normalized_runtime_error(request, error)
            self._log_structured_rejection(request, safe_error)
            if owns_lease:
                if safe_error.code == "agent_publication_failed":
                    repository.release_for_recovery(
                        request.run_id,
                        lease_owner_id=lease_owner_id,
                        lease_generation=lease_generation,
                        safe_error_code=safe_error.code,
                    )
                    owns_lease = False
                    raise safe_error from error
                self._persist_local_failure(
                    repository,
                    event_projector,
                    request,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    error=safe_error,
                    model_ref=model_ref,
                )
            raise safe_error from error
        except AgentRunRepositoryError as error:
            safe_error = _normalized_runtime_error(
                request,
                PiAgentRuntimeError(error.code, error.message),
            )
            self._log_structured_rejection(request, safe_error)
            if owns_lease:
                self._persist_local_failure(
                    repository,
                    event_projector,
                    request,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    error=safe_error,
                    model_ref=model_ref,
                )
            raise safe_error from error
        except Exception as error:
            safe_error = _normalized_runtime_error(
                request,
                PiAgentRuntimeError(
                    "agent_runtime_unavailable",
                    _safe_error_message_for_code("agent_runtime_unavailable"),
                    retryable=True,
                    details={
                        "attempt_stage": "runtime_processing",
                        "failure_boundary": "runtime_internal",
                    },
                ),
            )
            if owns_lease:
                self._persist_local_failure(
                    repository,
                    event_projector,
                    request,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    error=safe_error,
                    model_ref=model_ref,
                )
            raise safe_error from error
        finally:
            database.dispose()

    @staticmethod
    def _replay_staged_result(
        repository: AgentRunRepository,
        event_projector: V2AgentEventProjector,
        record: AgentRunRecord,
        *,
        lease_owner_id: str,
        lease_generation: int,
        request: AgentRunRequest,
        model_ref: str | None,
    ) -> DurablePiRunResult:
        payload = dict(record.terminal_result or {})
        event = AgentRuntimeEvent(
            seq=max(1, record.last_event_seq),
            run_id=record.run_id,
            agent_name=request.agent_name,
            event_type="run_completed",
            created_at=datetime.now(timezone.utc),
            payload=payload,
        )
        try:
            event_projector.consume(
                event,
                workflow_id=getattr(request.context, "workflow_id", None),
                model_id=model_ref,
            )
        except Exception as error:
            repository.release_for_recovery(
                record.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                safe_error_code="agent_publication_failed",
            )
            raise PiAgentRuntimeError(
                "agent_publication_failed",
                _safe_error_message_for_code("agent_publication_failed"),
                retryable=True,
                details=_publication_failure_audit(
                    request.operation,
                    record.attempt_metadata,
                ),
            ) from error
        completed = repository.finish(
            record.run_id,
            lease_owner_id=lease_owner_id,
            lease_generation=lease_generation,
            status="completed",
            terminal_result=payload,
            audit_metadata=record.attempt_metadata,
        )
        return DurablePiRunResult(
            run_id=completed.run_id,
            status="completed",
            terminal_payload=payload,
            last_event_seq=completed.last_event_seq,
            replayed=True,
        )

    @staticmethod
    def _persist_local_failure(
        repository: AgentRunRepository,
        projector: V2AgentEventProjector,
        request: AgentRunRequest,
        *,
        lease_owner_id: str,
        lease_generation: int,
        error: PiAgentRuntimeError,
        model_ref: str | None,
    ) -> None:
        try:
            record = repository.load(request.run_id)
            event_seq = record.last_event_seq + 1
            repository.record_event_seq(
                request.run_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                seq=event_seq,
                operation_stage="failed",
            )
        except AgentRunRepositoryError:
            event_seq = 1
        try:
            DurablePiRunService._project_failed_trace(
                projector,
                request,
                seq=event_seq,
                code=error.code,
                retryable=error.retryable,
                audit=error.details,
                model_ref=model_ref,
            )
        except Exception:  # noqa: BLE001 - SQLite terminal authority must still publish.
            _LOGGER.exception(
                "Agent failure trace publication failed run_id=%s code=%s",
                request.run_id,
                error.code,
            )
        DurablePiRunService._finish_failed(
            repository,
            request.run_id,
            lease_owner_id,
            lease_generation,
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            audit=error.details,
        )

    @staticmethod
    def _project_failed_trace(
        projector: V2AgentEventProjector,
        request: AgentRunRequest,
        *,
        seq: int,
        code: str,
        retryable: bool,
        audit: Mapping[str, Any],
        model_ref: str | None,
    ) -> None:
        projector.consume(
            AgentRuntimeEvent(
                seq=seq,
                run_id=request.run_id,
                agent_name=request.agent_name,
                event_type="run_failed",
                created_at=datetime.now(timezone.utc),
                payload={
                    "code": code,
                    "message": _safe_error_message_for_code(code),
                    "retryable": retryable,
                    "audit": safe_agent_transport_audit(dict(audit)),
                },
            ),
            workflow_id=getattr(request.context, "workflow_id", None),
            model_id=model_ref,
        )

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
            _safe_error_message_for_code(safe_error_code or _safe_error_code(payload)),
            retryable=bool(payload.get("retryable")),
            details=_safe_audit_metadata(payload),
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
        audit: Mapping[str, Any],
    ) -> None:
        safe_audit = safe_agent_transport_audit(dict(audit))
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
                    "audit": safe_audit,
                },
                safe_error_code=code,
                audit_metadata=safe_audit,
            )
        except AgentRunRepositoryError:
            return


def _has_live_lease(record: AgentRunRecord) -> bool:
    return bool(
        record.lease_owner_id
        and record.lease_expires_at
        and record.lease_expires_at > datetime.now(timezone.utc)
    )


def _operation_stage_for_event(event_type: str) -> str:
    return {
        "run_started": "running",
        "heartbeat": "waiting_provider_response",
        "tool_call": "validating",
        "tool_result": "validating",
        "run_failed": "failed",
        "run_cancelled": "cancelled",
    }.get(event_type, "running")


def _safe_scope_value(scope: Mapping[str, Any], key: str) -> str | int | None:
    value = scope.get(key)
    return value if isinstance(value, (str, int)) else None


def _safe_audit_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    audit = payload.get("audit")
    return safe_agent_transport_audit(audit)


def _safe_error_code(payload: Mapping[str, Any]) -> str:
    value = payload.get("code")
    if (
        isinstance(value, str)
        and 0 < len(value) <= 120
        and value.replace("_", "").isalnum()
        and value == value.lower()
    ):
        return value
    return "agent_runtime_unavailable"


def _safe_error_message_for_code(code: str) -> str:
    return _SAFE_FAILURE_MESSAGES.get(code, "Agent runtime failed.")


def _normalized_runtime_error(
    request: AgentRunRequest,
    error: PiAgentRuntimeError,
) -> PiAgentRuntimeError:
    code = _safe_error_code({"code": error.code})
    retryable = bool(error.retryable)
    audit = _canonical_failure_audit(
        operation=request.operation,
        code=code,
        retryable=retryable,
        candidate=error.details,
    )
    return PiAgentRuntimeError(
        code,
        _safe_error_message_for_code(code),
        retryable=retryable,
        details=audit,
    )


def _safe_terminal_failure_payload(
    payload: Mapping[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    code = _safe_error_code(payload)
    retryable = bool(payload.get("retryable"))
    audit = _canonical_failure_audit(
        operation=operation,
        code=code,
        retryable=retryable,
        candidate=payload.get("audit"),
    )
    return {
        "code": code,
        "message": _safe_error_message_for_code(code),
        "retryable": retryable,
        "audit": audit,
    }


def _canonical_failure_audit(
    *,
    operation: str,
    code: str,
    retryable: bool,
    candidate: Any,
) -> dict[str, Any]:
    audit = safe_agent_transport_audit(candidate)
    audit["attempt_stage"] = str(audit.get("attempt_stage") or "initial")
    audit["failure_boundary"] = str(
        audit.get("failure_boundary") or _default_failure_boundary(code)
    )
    if "model_submission_count" not in audit and code in _PRE_SUBMISSION_FAILURE_CODES:
        audit["model_submission_count"] = 0
    audit["operation"] = operation
    if audit.get("model_submission_count") == 0:
        audit["response_activity_observed"] = False
    audit["retryable"] = retryable
    audit["terminal_code"] = code
    return audit


def _default_failure_boundary(code: str) -> str:
    if code in _PROVIDER_FAILURE_CODES:
        return "provider"
    if code in _STRUCTURED_FAILURE_CODES:
        return "structured_validation"
    if code in _PRE_SUBMISSION_FAILURE_CODES:
        return "operation_preparation"
    if code == "agent_publication_failed":
        return "terminal_publication"
    if code == "agent_protocol_mismatch":
        return "runtime_protocol"
    if code in {"agent_deadline_exceeded", "agent_run_cancelled"}:
        return "runtime_control"
    return "runtime_internal"


def _publication_failure_audit(
    operation: str,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    upstream = safe_agent_transport_audit(candidate)
    audit: dict[str, Any] = {
        "attempt_stage": "terminal_publication",
        "failure_boundary": "terminal_publication",
        "operation": operation,
        "retryable": True,
        "terminal_code": "agent_publication_failed",
    }
    for key in ("model_submission_count", "response_activity_observed"):
        if key in upstream:
            audit[key] = upstream[key]
    return audit
