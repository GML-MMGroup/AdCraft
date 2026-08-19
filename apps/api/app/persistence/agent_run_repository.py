"""Transactional persistence for idempotent Pi Agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Literal

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.models import AgentCanvasChatTurnRow, AgentRunRow
from app.schemas.agent_runtime import AgentRunRequest


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_MAX_AUDIT_BYTES = 16_384
_MAX_VALIDATION_CONTEXT_BYTES = 16_384
_MAX_TOOL_RESULTS_BYTES = 65_536
_SENSITIVE_KEYS = ("api_key", "authorization", "credential", "secret", "token")
_SAFE_TOKEN_METADATA_KEYS = {
    "input_tokens",
    "max_output_tokens",
    "output_tokens",
    "reasoning_tokens",
    "thinking_budget_tokens",
}
_UNSAFE_CONTENT_KEYS = (
    "function_arguments",
    "provider_payload",
    "raw_prompt",
    "raw_response",
    "request_headers",
)


class AgentRunRepositoryError(RuntimeError):
    """Stable bounded error raised by Agent run persistence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentRunRecord:
    run_id: str
    request_id: str
    parent_run_id: str | None
    conversation_id: str | None
    workflow_id: str | None
    agent_name: str
    operation: str
    contract_name: str | None
    validation_profile: str | None
    validation_context: dict[str, Any]
    deadline_at: datetime | None
    status: str
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    last_event_seq: int
    expected_target_revision: int | None
    terminal_result: dict[str, Any] | None
    tool_results: dict[str, Any]
    safe_error_code: str | None
    frozen_policy_digest: str
    frozen_input_digest: str
    retry_attempt_no: int
    attempt_metadata: dict[str, Any]
    safe_failure: dict[str, Any]
    operation_stage: str
    completed_result_identity: str | None
    audit_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class AgentRunRepository:
    """Own Agent run request deduplication, leases, and replay metadata."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def load_validation_source_message(
        self,
        *,
        workflow_id: str | None,
        conversation_id: str | None,
        turn_id: str,
    ) -> str | None:
        if workflow_id is None or conversation_id is None:
            return None
        with self._database.engine.connect() as connection:
            request_json = connection.execute(
                select(AgentCanvasChatTurnRow.request_json).where(
                    AgentCanvasChatTurnRow.workflow_id == workflow_id,
                    AgentCanvasChatTurnRow.conversation_id == conversation_id,
                    AgentCanvasChatTurnRow.turn_id == turn_id,
                )
            ).scalar_one_or_none()
        if request_json is None:
            return None
        try:
            request = json.loads(request_json)
        except (TypeError, json.JSONDecodeError):
            return None
        source_message = request.get("text") if isinstance(request, dict) else None
        return source_message if isinstance(source_message, str) and source_message else None

    def create_or_load(
        self,
        request: AgentRunRequest,
        *,
        lease_owner_id: str,
        lease_duration_seconds: float,
        now: datetime | None = None,
    ) -> tuple[AgentRunRecord, bool]:
        timestamp = _utc(now)
        _validate_metadata(request.audit_metadata)
        _validate_validation_context(request.validation_context)
        lease_expiry = timestamp + timedelta(seconds=_lease_duration(lease_duration_seconds))
        context = request.context
        values = {
            "run_id": request.run_id,
            "request_id": request.request_id,
            "parent_run_id": request.parent_run_id,
            "conversation_id": getattr(context, "conversation_id", None),
            "workflow_id": getattr(context, "workflow_id", None),
            "agent_name": request.agent_name,
            "operation": request.operation,
            "contract_name": request.contract_name,
            "validation_profile": request.validation_profile,
            "validation_context_json": _json(request.validation_context),
            "deadline_at": _iso(request.deadline_at),
            "status": "running",
            "lease_owner_id": lease_owner_id,
            "lease_generation": 1,
            "lease_expires_at": _iso(lease_expiry),
            "last_event_seq": 0,
            "expected_target_revision": _expected_target_revision(request),
            "terminal_result_json": None,
            "tool_results_json": "{}",
            "safe_error_code": None,
            "frozen_policy_digest": _frozen_policy_digest(request),
            "frozen_input_digest": _frozen_input_digest(request),
            "retry_attempt_no": _retry_attempt_no(request),
            "attempt_metadata_json": "{}",
            "safe_failure_json": "{}",
            "operation_stage": "running",
            "completed_result_identity": None,
            "audit_metadata_json": _json(request.audit_metadata),
            "created_at": _iso(timestamp),
            "updated_at": _iso(timestamp),
            "finished_at": None,
        }
        try:
            with self._database.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(AgentRunRow).where(AgentRunRow.request_id == request.request_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    record = _record(existing)
                    _validate_matching_request(record, request)
                    return record, False
                connection.execute(insert(AgentRunRow).values(**values))
                row = _get_row(connection, request.run_id)
        except IntegrityError:
            record = self._load_by_request_id(request.request_id)
            _validate_matching_request(record, request)
            return record, False
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(row), True

    def load(self, run_id: str) -> AgentRunRecord:
        """Load one durable Agent run without changing its lease or status."""

        try:
            with self._database.engine.connect() as connection:
                row = _get_row(connection, run_id)
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(row)

    def list_for_workflow(self, workflow_id: str) -> list[AgentRunRecord]:
        """Return Agent runs for one workflow in stable creation order."""

        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentRunRow)
                        .where(AgentRunRow.workflow_id == workflow_id)
                        .order_by(AgentRunRow.created_at, AgentRunRow.run_id)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return [_record(row) for row in rows]

    def acquire_lease(
        self,
        run_id: str,
        *,
        lease_owner_id: str,
        lease_duration_seconds: float,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        timestamp = _utc(now)
        lease_expiry = timestamp + timedelta(seconds=_lease_duration(lease_duration_seconds))
        try:
            with self._database.engine.begin() as connection:
                row = _get_row(connection, run_id)
                _require_nonterminal(row)
                current_owner = row["lease_owner_id"]
                current_expiry = _datetime(row["lease_expires_at"])
                if (
                    current_owner not in {None, lease_owner_id}
                    and current_expiry is not None
                    and current_expiry > timestamp
                ):
                    raise _error(
                        "agent_run_lease_active",
                        "Agent run has a live lease owned by another worker.",
                    )
                interrupted = (
                    current_owner is not None
                    and current_owner != lease_owner_id
                    and current_expiry is not None
                    and current_expiry <= timestamp
                )
                audit_metadata = _object(row["audit_metadata_json"])
                if interrupted:
                    audit_metadata = {
                        **audit_metadata,
                        "interruption_count": int(audit_metadata.get("interruption_count", 0)) + 1,
                        "last_interruption_code": "agent_run_interrupted",
                    }
                result = connection.execute(
                    update(AgentRunRow)
                    .where(
                        AgentRunRow.run_id == run_id,
                        AgentRunRow.status.not_in(_TERMINAL_STATUSES),
                        AgentRunRow.updated_at == row["updated_at"],
                    )
                    .values(
                        status="running",
                        operation_stage=(
                            "publishing"
                            if row["completed_result_identity"] is not None
                            else "running"
                        ),
                        lease_owner_id=lease_owner_id,
                        lease_generation=int(row["lease_generation"]) + 1,
                        lease_expires_at=_iso(lease_expiry),
                        safe_error_code=(
                            "agent_run_interrupted" if interrupted else row["safe_error_code"]
                        ),
                        audit_metadata_json=_json(audit_metadata),
                        updated_at=_iso(timestamp),
                    )
                )
                if result.rowcount != 1:
                    raise _error(
                        "agent_run_lease_active",
                        "Agent run lease was acquired by another worker.",
                    )
                updated = _get_row(connection, run_id)
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(updated)

    def record_event_seq(
        self,
        run_id: str,
        *,
        lease_owner_id: str,
        lease_generation: int,
        seq: int,
        operation_stage: str | None = None,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        timestamp = _utc(now)
        if seq < 1:
            raise _error("agent_event_sequence_invalid", "Agent event sequence must be positive.")
        try:
            with self._database.engine.begin() as connection:
                row = _get_owned_row(
                    connection,
                    run_id,
                    lease_owner_id,
                    lease_generation,
                    timestamp,
                )
                if seq <= int(row["last_event_seq"]):
                    raise _error(
                        "agent_event_sequence_invalid",
                        "Agent event sequence must increase monotonically.",
                    )
                connection.execute(
                    update(AgentRunRow)
                    .where(AgentRunRow.run_id == run_id)
                    .values(
                        last_event_seq=seq,
                        operation_stage=operation_stage or row["operation_stage"],
                        updated_at=_iso(timestamp),
                    )
                )
                updated = _get_row(connection, run_id)
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(updated)

    def finish(
        self,
        run_id: str,
        *,
        lease_owner_id: str,
        lease_generation: int,
        status: Literal["completed", "failed", "cancelled"],
        terminal_result: dict[str, Any],
        safe_error_code: str | None = None,
        audit_metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        timestamp = _utc(now)
        if status not in _TERMINAL_STATUSES:
            raise _error("agent_run_status_invalid", "Agent run terminal status is invalid.")
        _validate_safe_json(terminal_result, maximum_bytes=_MAX_TOOL_RESULTS_BYTES)
        _validate_metadata(audit_metadata or {})
        try:
            with self._database.engine.begin() as connection:
                row = _get_owned_row(
                    connection,
                    run_id,
                    lease_owner_id,
                    lease_generation,
                    timestamp,
                )
                merged_audit = {
                    **_object(row["audit_metadata_json"]),
                    **(audit_metadata or {}),
                }
                _validate_metadata(merged_audit)
                connection.execute(
                    update(AgentRunRow)
                    .where(AgentRunRow.run_id == run_id)
                    .values(
                        status=status,
                        lease_owner_id=None,
                        lease_expires_at=None,
                        terminal_result_json=_json(terminal_result),
                        completed_result_identity=(
                            row["completed_result_identity"]
                            or (_digest(terminal_result) if status == "completed" else None)
                        ),
                        audit_metadata_json=_json(merged_audit),
                        attempt_metadata_json=_json(audit_metadata or {}),
                        safe_error_code=safe_error_code,
                        safe_failure_json=(
                            "{}" if status == "completed" else _json(terminal_result)
                        ),
                        operation_stage=status,
                        updated_at=_iso(timestamp),
                        finished_at=_iso(timestamp),
                    )
                )
                updated = _get_row(connection, run_id)
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(updated)

    def stage_completed_result(
        self,
        run_id: str,
        *,
        lease_owner_id: str,
        lease_generation: int,
        seq: int,
        terminal_result: dict[str, Any],
        attempt_metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        """Persist a validated result before any external publication side effect."""

        timestamp = _utc(now)
        if seq < 1:
            raise _error("agent_event_sequence_invalid", "Agent event sequence must be positive.")
        _validate_safe_json(terminal_result, maximum_bytes=_MAX_TOOL_RESULTS_BYTES)
        _validate_metadata(attempt_metadata or {})
        result_identity = _digest(terminal_result)
        try:
            with self._database.engine.begin() as connection:
                row = _get_owned_row(
                    connection,
                    run_id,
                    lease_owner_id,
                    lease_generation,
                    timestamp,
                )
                existing_identity = row["completed_result_identity"]
                if existing_identity is not None and existing_identity != result_identity:
                    raise _error(
                        "agent_completed_result_conflict",
                        "Agent run already staged a different completed result.",
                    )
                if seq < int(row["last_event_seq"]):
                    raise _error(
                        "agent_event_sequence_invalid",
                        "Agent event sequence cannot move backwards.",
                    )
                connection.execute(
                    update(AgentRunRow)
                    .where(AgentRunRow.run_id == run_id)
                    .values(
                        terminal_result_json=_json(terminal_result),
                        completed_result_identity=result_identity,
                        attempt_metadata_json=_json(attempt_metadata or {}),
                        operation_stage="publishing",
                        last_event_seq=seq,
                        updated_at=_iso(timestamp),
                    )
                )
                updated = _get_row(connection, run_id)
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(updated)

    def release_for_recovery(
        self,
        run_id: str,
        *,
        lease_owner_id: str,
        lease_generation: int,
        safe_error_code: str,
        now: datetime | None = None,
    ) -> AgentRunRecord:
        """Release an owned staged result so another worker can replay publication."""

        timestamp = _utc(now)
        try:
            with self._database.engine.begin() as connection:
                row = _get_owned_row(
                    connection,
                    run_id,
                    lease_owner_id,
                    lease_generation,
                    timestamp,
                )
                if row["completed_result_identity"] is None:
                    raise _error(
                        "agent_completed_result_missing",
                        "Agent run has no completed result to recover.",
                    )
                connection.execute(
                    update(AgentRunRow)
                    .where(AgentRunRow.run_id == run_id)
                    .values(
                        lease_owner_id=None,
                        lease_expires_at=None,
                        operation_stage="publishing",
                        safe_error_code=safe_error_code,
                        updated_at=_iso(timestamp),
                    )
                )
                updated = _get_row(connection, run_id)
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return _record(updated)

    def store_tool_result(
        self,
        run_id: str,
        *,
        lease_owner_id: str,
        lease_generation: int,
        idempotency_key: str,
        request_digest: str,
        result: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = _utc(now)
        if not idempotency_key or len(idempotency_key) > 256:
            raise _error(
                "agent_tool_idempotency_invalid",
                "Agent tool idempotency key is invalid.",
            )
        entry = {"request_digest": request_digest, "result": result}
        _validate_safe_json(entry, maximum_bytes=_MAX_TOOL_RESULTS_BYTES)
        try:
            with self._database.engine.begin() as connection:
                row = _get_owned_row(
                    connection,
                    run_id,
                    lease_owner_id,
                    lease_generation,
                    timestamp,
                )
                stored = _object(row["tool_results_json"])
                existing = stored.get(idempotency_key)
                if existing is not None:
                    if existing.get("request_digest") != request_digest:
                        raise _error(
                            "agent_tool_idempotency_conflict",
                            "Agent tool idempotency key was reused with different input.",
                        )
                    return dict(existing["result"])
                stored[idempotency_key] = entry
                _validate_safe_json(stored, maximum_bytes=_MAX_TOOL_RESULTS_BYTES)
                connection.execute(
                    update(AgentRunRow)
                    .where(AgentRunRow.run_id == run_id)
                    .values(tool_results_json=_json(stored), updated_at=_iso(timestamp))
                )
        except AgentRunRepositoryError:
            raise
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        return dict(result)

    def _load_by_request_id(self, request_id: str) -> AgentRunRecord:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentRunRow).where(AgentRunRow.request_id == request_id)
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _persistence_error() from error
        if row is None:
            raise _persistence_error()
        return _record(row)


def _get_row(connection: Any, run_id: str) -> Any:
    row = (
        connection.execute(select(AgentRunRow).where(AgentRunRow.run_id == run_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("agent_run_not_found", "Agent run was not found.")
    return row


def _get_owned_row(
    connection: Any,
    run_id: str,
    lease_owner_id: str,
    lease_generation: int,
    now: datetime,
) -> Any:
    row = _get_row(connection, run_id)
    _require_nonterminal(row)
    if int(row["lease_generation"]) != lease_generation:
        raise _error(
            "agent_run_lease_stale",
            "Agent run lease generation has been superseded.",
        )
    if row["lease_owner_id"] != lease_owner_id:
        raise _error("agent_run_lease_not_owned", "Agent run lease is not owned by this worker.")
    expires_at = _datetime(row["lease_expires_at"])
    if expires_at is None or expires_at < now:
        raise _error("agent_run_lease_expired", "Agent run lease has expired.")
    return row


def _require_nonterminal(row: Any) -> None:
    if row["status"] in _TERMINAL_STATUSES:
        raise _error("agent_run_terminal", "Agent run is already terminal.")


def _record(row: Any) -> AgentRunRecord:
    return AgentRunRecord(
        run_id=row["run_id"],
        request_id=row["request_id"],
        parent_run_id=row["parent_run_id"],
        conversation_id=row["conversation_id"],
        workflow_id=row["workflow_id"],
        agent_name=row["agent_name"],
        operation=row["operation"],
        contract_name=row["contract_name"],
        validation_profile=row["validation_profile"],
        validation_context=_object(row["validation_context_json"]),
        deadline_at=_datetime(row["deadline_at"]),
        status=row["status"],
        lease_owner_id=row["lease_owner_id"],
        lease_generation=int(row["lease_generation"]),
        lease_expires_at=_datetime(row["lease_expires_at"]),
        last_event_seq=int(row["last_event_seq"]),
        expected_target_revision=row["expected_target_revision"],
        terminal_result=(
            _object(row["terminal_result_json"])
            if row["terminal_result_json"] is not None
            else None
        ),
        tool_results=_object(row["tool_results_json"]),
        safe_error_code=row["safe_error_code"],
        frozen_policy_digest=row["frozen_policy_digest"],
        frozen_input_digest=row["frozen_input_digest"],
        retry_attempt_no=int(row["retry_attempt_no"]),
        attempt_metadata=_object(row["attempt_metadata_json"]),
        safe_failure=_object(row["safe_failure_json"]),
        operation_stage=row["operation_stage"],
        completed_result_identity=row["completed_result_identity"],
        audit_metadata=_object(row["audit_metadata_json"]),
        created_at=_required_datetime(row["created_at"]),
        updated_at=_required_datetime(row["updated_at"]),
        finished_at=_datetime(row["finished_at"]),
    )


def _validate_metadata(metadata: dict[str, Any]) -> None:
    try:
        _validate_safe_json(metadata, maximum_bytes=_MAX_AUDIT_BYTES)
    except (TypeError, ValueError) as error:
        raise _error(
            "agent_run_metadata_invalid",
            "Agent run audit metadata is not safe to persist.",
        ) from error


def _validate_matching_request(
    record: AgentRunRecord,
    request: AgentRunRequest,
) -> None:
    expected_revision = _expected_target_revision(request)
    stored_digest = record.audit_metadata.get("request_identity_digest")
    request_digest = request.audit_metadata.get("request_identity_digest")
    if (
        record.agent_name != request.agent_name
        or record.operation != request.operation
        or record.contract_name != request.contract_name
        or record.validation_profile != request.validation_profile
        or record.expected_target_revision != expected_revision
        or (
            bool(record.frozen_policy_digest)
            and record.frozen_policy_digest != _frozen_policy_digest(request)
        )
        or (
            bool(record.frozen_input_digest)
            and record.frozen_input_digest != _frozen_input_digest(request)
        )
        or (
            stored_digest is not None
            and request_digest is not None
            and stored_digest != request_digest
        )
    ):
        raise _error(
            "agent_run_request_conflict",
            "Agent request identity was reused with different semantic input.",
        )


def _expected_target_revision(request: AgentRunRequest) -> int | None:
    target = getattr(request.context, "target", None)
    value = (
        target.expected_revision
        if target is not None
        else request.audit_metadata.get("expected_target_revision")
    )
    return int(value) if value is not None else None


def _frozen_policy_digest(request: AgentRunRequest) -> str:
    policy = request.audit_metadata.get("agent_operation_policy")
    return _digest(policy if isinstance(policy, dict) else request.policy.model_dump(mode="json"))


def _frozen_input_digest(request: AgentRunRequest) -> str:
    return _digest(
        {
            "context": request.context.model_dump(mode="json"),
            "context_snapshot_id": request.context_snapshot_id,
            "contract_digest": request.contract_digest,
            "validation_context": request.validation_context,
        }
    )


def _retry_attempt_no(request: AgentRunRequest) -> int:
    value = request.audit_metadata.get("retry_attempt_no", 1)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 1


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _validate_validation_context(context: dict[str, Any]) -> None:
    try:
        _validate_safe_json(context, maximum_bytes=_MAX_VALIDATION_CONTEXT_BYTES)
    except (TypeError, ValueError) as error:
        raise _error(
            "agent_run_validation_context_invalid",
            "Agent run validation context is not safe to persist.",
        ) from error


def _validate_safe_json(value: Any, *, maximum_bytes: int) -> None:
    encoded = _json(value).encode("utf-8")
    if len(encoded) > maximum_bytes:
        raise ValueError("JSON payload exceeds its persistence limit")

    def visit(current: Any, key: str | None = None) -> None:
        if key is not None:
            normalized_key = key.casefold()
            if normalized_key not in _SAFE_TOKEN_METADATA_KEYS and any(
                part in normalized_key for part in _SENSITIVE_KEYS
            ):
                raise ValueError("JSON payload contains a sensitive key")
            if normalized_key in _UNSAFE_CONTENT_KEYS:
                raise ValueError("JSON payload contains unrestricted content")
        if isinstance(current, dict):
            for child_key, child_value in current.items():
                visit(child_value, str(child_key))
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)
        elif isinstance(current, str) and current.startswith(("/", "\\\\")):
            raise ValueError("JSON payload contains an absolute path")

    visit(value)


def _lease_duration(value: float) -> float:
    if value <= 0 or value > 3_600:
        raise _error("agent_run_lease_invalid", "Agent run lease duration is invalid.")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise _persistence_error()
    return parsed


def _utc(value: datetime | None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        raise _error("agent_run_time_invalid", "Agent run timestamp must include a timezone.")
    return resolved.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _required_datetime(value: str) -> datetime:
    parsed = _datetime(value)
    if parsed is None:
        raise _persistence_error()
    return parsed


def _error(code: str, message: str) -> AgentRunRepositoryError:
    return AgentRunRepositoryError(code, message)


def _persistence_error() -> AgentRunRepositoryError:
    return _error("agent_run_persistence_failed", "Agent run persistence failed.")
