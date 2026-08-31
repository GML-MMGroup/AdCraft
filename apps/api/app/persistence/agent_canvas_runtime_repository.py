"""SQLite ownership and compare-and-set operations for Agent Canvas runtime."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasExecutionAdmissionRow,
    AgentCanvasExecutionMemberRow,
    AgentCanvasExecutionRow,
    AgentCanvasNodeRow,
    AgentCanvasNodeLeaseRow,
    AgentCanvasProviderTaskRow,
    AgentCanvasProviderSubmissionIntentRow,
    AgentCanvasVideoParameterCompilationSnapshotRow,
    AgentCanvasWorkflowRow,
    AssetVersionRow,
)
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_runtime import (
    CanvasExecutionMembershipV2,
    CanvasExecutionRecordV2,
    CanvasProviderTaskV2,
    EffectiveMediaParameterSnapshotV2,
    NodeRunIntentSnapshotV2,
    NodeExecutionLeaseV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.schemas.agent_canvas_video_parameters import VideoParameterCompilationSnapshotV2
from app.schemas.agent_canvas_runtime_authority import (
    CanvasExecutionMemberIntentV2,
    CanvasExecutionStartCommandV2,
    CanvasExecutionStartResultV2,
    ProviderSubmissionIntentV2,
)


_ACTIVE_EXECUTION_STATES = ("queued", "running", "waiting")
_TERMINAL_EXECUTION_STATES = ("completed", "partial_completed", "failed", "cancelled")
_TERMINAL_MEMBER_STATES = ("succeeded", "failed", "skipped_dependency", "cancelled")


class AgentCanvasRuntimeRepository:
    """Persist executions and leases without process-local ownership state."""

    def __init__(self, database: V2Database, events: EventRepository) -> None:
        if events.database is not database:
            raise ValueError("Runtime and event repositories must share one database.")
        self._database = database
        self._events = events

    @property
    def database(self) -> V2Database:
        return self._database

    def event_cursor(self, workflow_id: str) -> int:
        return self._events.max_seq(workflow_id)

    def record_provider_task_event(
        self,
        task: CanvasProviderTaskV2,
        *,
        event_type: str,
        now: datetime,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._events.append(
            V2EventInsert(
                workflow_id=task.workflow_id,
                execution_id=task.execution_id,
                node_id=task.node_id,
                event_type=event_type,
                created_at=now.isoformat(),
                payload={
                    "provider_task_id": task.task_id,
                    "remote_task_id": task.remote_task_id,
                    **(payload or {}),
                },
            )
        )

    def put_parameter_compilation_snapshot(
        self,
        snapshot: VideoParameterCompilationSnapshotV2,
    ) -> VideoParameterCompilationSnapshotV2:
        try:
            with self._database.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(AgentCanvasVideoParameterCompilationSnapshotRow).where(
                            AgentCanvasVideoParameterCompilationSnapshotRow.snapshot_id
                            == snapshot.snapshot_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if str(existing["snapshot_digest"]) != snapshot.snapshot_digest:
                        raise _error(
                            "parameter_compilation_snapshot_conflict",
                            "Parameter compilation snapshot content is immutable.",
                        )
                    return VideoParameterCompilationSnapshotV2.model_validate_json(
                        str(existing["snapshot_json"])
                    )
                connection.execute(
                    insert(AgentCanvasVideoParameterCompilationSnapshotRow).values(
                        snapshot_id=snapshot.snapshot_id,
                        workflow_id=snapshot.workflow_id,
                        execution_id=snapshot.execution_id,
                        member_id=snapshot.member_id,
                        node_id=snapshot.node_id,
                        snapshot_digest=snapshot.snapshot_digest,
                        snapshot_json=snapshot.model_dump_json(),
                        created_at=snapshot.created_at.isoformat(),
                    )
                )
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "parameter_compilation_snapshot_conflict",
                "Parameter compilation snapshot content is immutable.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Execution storage is unavailable.",
            ) from error
        return snapshot

    def get_parameter_compilation_snapshot(
        self,
        snapshot_id: str,
    ) -> VideoParameterCompilationSnapshotV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasVideoParameterCompilationSnapshotRow).where(
                            AgentCanvasVideoParameterCompilationSnapshotRow.snapshot_id
                            == snapshot_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Execution storage is unavailable.",
            ) from error
        if row is None:
            raise _error(
                "parameter_compilation_snapshot_not_found",
                "Parameter compilation snapshot was not found.",
            )
        return VideoParameterCompilationSnapshotV2.model_validate_json(str(row["snapshot_json"]))

    def create_execution(
        self,
        *,
        workflow_id: str,
        scope: str,
        node_ids: tuple[str, ...],
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> CanvasExecutionRecordV2:
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasExecutionRow).where(
                                AgentCanvasExecutionRow.idempotency_key == idempotency_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        if (
                            str(existing["workflow_id"]) != workflow_id
                            or str(existing["request_fingerprint"]) != request_fingerprint
                        ):
                            raise _error(
                                "idempotency_conflict",
                                "Idempotency key was reused with another run request.",
                            )
                        connection.commit()
                        return _execution(existing)
                    active = self._active_execution_in_transaction(connection, workflow_id)
                    if active is not None:
                        next_member_order = self._next_member_order(connection, active.execution_id)
                        for node_id in node_ids:
                            if self._member_exists(connection, active.execution_id, node_id):
                                continue
                            self._insert_member(
                                connection,
                                execution_id=active.execution_id,
                                workflow_id=workflow_id,
                                node_id=node_id,
                                member_order=next_member_order,
                                now=now.isoformat(),
                            )
                            next_member_order += 1
                        connection.commit()
                        return self.get_execution(active.execution_id)
                    execution_id = f"exec_{uuid4().hex}"
                    timestamp = now.isoformat()
                    connection.execute(
                        insert(AgentCanvasExecutionRow).values(
                            execution_id=execution_id,
                            workflow_id=workflow_id,
                            scope=scope,
                            status="queued",
                            cancel_requested=False,
                            idempotency_key=idempotency_key,
                            request_fingerprint=request_fingerprint,
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            execution_id=execution_id,
                            event_type="execution_queued",
                            created_at=timestamp,
                            payload={"scope": scope, "node_ids": list(node_ids)},
                        ),
                    )
                    for member_order, node_id in enumerate(node_ids):
                        self._insert_member(
                            connection,
                            execution_id=execution_id,
                            workflow_id=workflow_id,
                            node_id=node_id,
                            member_order=member_order,
                            now=timestamp,
                        )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "execution_persistence_failed",
                "Execution membership could not be persisted.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Execution storage is unavailable.",
            ) from error
        return self.get_execution(execution_id)

    def start_or_join_execution(
        self,
        command: CanvasExecutionStartCommandV2,
    ) -> CanvasExecutionStartResultV2:
        """Atomically replay, join, or create one Workflow execution."""

        timestamp = command.created_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    replay = self._load_admission(connection, command)
                    if replay is not None:
                        connection.commit()
                        return replay
                    self._validate_start_intent(connection, command)
                    active = self._active_execution_in_transaction(connection, command.workflow_id)
                    created = active is None
                    if active is None:
                        execution_id = f"exec_{uuid4().hex}"
                        connection.execute(
                            insert(AgentCanvasExecutionRow).values(
                                execution_id=execution_id,
                                workflow_id=command.workflow_id,
                                scope=command.scope,
                                status="queued",
                                cancel_requested=False,
                                idempotency_key=command.idempotency_key,
                                request_fingerprint=command.request_digest,
                                created_at=timestamp,
                                updated_at=timestamp,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=command.workflow_id,
                                execution_id=execution_id,
                                event_type="execution_queued",
                                created_at=timestamp,
                                payload={
                                    "scope": command.scope,
                                    "node_ids": [
                                        intent.node_id for intent in command.member_intents
                                    ],
                                },
                            ),
                        )
                    else:
                        execution_id = active.execution_id
                    next_order = self._next_member_order(connection, execution_id)
                    inserted: list[str] = []
                    snapshot_ids: dict[str, str] = {}
                    for intent in command.member_intents:
                        if self._member_exists(connection, execution_id, intent.node_id):
                            continue
                        member_id = f"member_{uuid4().hex}"
                        snapshot = self._snapshot_for_intent(
                            command,
                            intent,
                            execution_id=execution_id,
                            member_id=member_id,
                        )
                        self._insert_member(
                            connection,
                            execution_id=execution_id,
                            workflow_id=command.workflow_id,
                            node_id=intent.node_id,
                            member_order=next_order,
                            now=timestamp,
                            member_id=member_id,
                            run_intent_snapshot=snapshot,
                            prompt_metadata={
                                "frozen_node": intent.frozen_node,
                                **(
                                    {
                                        "execution_parameter_normalizations": list(
                                            intent.parameter_normalizations
                                        )
                                    }
                                    if intent.parameter_normalizations
                                    else {}
                                ),
                            },
                        )
                        inserted.append(intent.node_id)
                        snapshot_ids[intent.node_id] = snapshot.snapshot_id
                        next_order += 1
                    execution = self._execution_in_transaction(connection, execution_id)
                    result = CanvasExecutionStartResultV2(
                        execution=execution,
                        accepted_node_ids=tuple(inserted) if created else (),
                        joined_node_ids=() if created else tuple(inserted),
                        snapshot_ids=snapshot_ids,
                    )
                    connection.execute(
                        insert(AgentCanvasExecutionAdmissionRow).values(
                            admission_id=f"admission_{uuid4().hex}",
                            idempotency_key=command.idempotency_key,
                            request_digest=command.request_digest,
                            workflow_id=command.workflow_id,
                            execution_id=execution_id,
                            result_json=result.model_dump_json(),
                            created_at=timestamp,
                        )
                    )
                    connection.commit()
                    return result
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except IntegrityError as error:
            raise _error(
                "execution_admission_conflict",
                "Execution admission conflicted with current durable state.",
            ) from error
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Execution storage is unavailable.",
            ) from error

    def add_members(
        self,
        execution_id: str,
        node_ids: tuple[str, ...],
        *,
        now: datetime,
    ) -> tuple[str, ...]:
        if not node_ids:
            return ()
        execution = self.get_execution(execution_id)
        inserted: list[str] = []
        timestamp = now.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    next_member_order = (
                        int(
                            connection.execute(
                                select(
                                    func.coalesce(
                                        func.max(AgentCanvasExecutionMemberRow.member_order),
                                        -1,
                                    )
                                ).where(AgentCanvasExecutionMemberRow.execution_id == execution_id)
                            ).scalar_one()
                        )
                        + 1
                    )
                    for node_id in node_ids:
                        exists = connection.execute(
                            select(AgentCanvasExecutionMemberRow.member_id).where(
                                AgentCanvasExecutionMemberRow.execution_id == execution_id,
                                AgentCanvasExecutionMemberRow.node_id == node_id,
                            )
                        ).scalar_one_or_none()
                        if exists is not None:
                            continue
                        self._insert_member(
                            connection,
                            execution_id=execution_id,
                            workflow_id=execution.workflow_id,
                            node_id=node_id,
                            member_order=next_member_order,
                            now=timestamp,
                        )
                        inserted.append(node_id)
                        next_member_order += 1
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Execution membership could not be extended.",
            ) from error
        return tuple(inserted)

    def get_execution(self, execution_id: str) -> CanvasExecutionRecordV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasExecutionRow).where(
                            AgentCanvasExecutionRow.execution_id == execution_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        if row is None:
            raise _error("execution_not_found", "Execution was not found.")
        return _execution(row)

    def get_active_execution(self, workflow_id: str) -> CanvasExecutionRecordV2 | None:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasExecutionRow)
                        .where(
                            AgentCanvasExecutionRow.workflow_id == workflow_id,
                            AgentCanvasExecutionRow.status.in_(_ACTIVE_EXECUTION_STATES),
                        )
                        .order_by(AgentCanvasExecutionRow.created_at.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        return _execution(row) if row is not None else None

    def list_latest_members_for_workflow(
        self,
        workflow_id: str,
    ) -> tuple[CanvasExecutionMembershipV2, ...]:
        """Return the newest durable member facts for each Node in a Workflow."""

        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasExecutionMemberRow)
                        .join(
                            AgentCanvasExecutionRow,
                            AgentCanvasExecutionRow.execution_id
                            == AgentCanvasExecutionMemberRow.execution_id,
                        )
                        .where(AgentCanvasExecutionRow.workflow_id == workflow_id)
                        .order_by(
                            AgentCanvasExecutionRow.updated_at.desc(),
                            AgentCanvasExecutionRow.created_at.desc(),
                            AgentCanvasExecutionMemberRow.member_order.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error

        latest: dict[str, CanvasExecutionMembershipV2] = {}
        for row in rows:
            member = _member(row)
            latest.setdefault(member.node_id, member)
        return tuple(latest.values())

    def list_active_executions(self) -> tuple[CanvasExecutionRecordV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasExecutionRow)
                        .where(AgentCanvasExecutionRow.status.in_(_ACTIVE_EXECUTION_STATES))
                        .order_by(AgentCanvasExecutionRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        return tuple(_execution(row) for row in rows)

    def list_executions(self) -> tuple[CanvasExecutionRecordV2, ...]:
        """List durable executions for bounded startup reconciliation."""

        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasExecutionRow).order_by(
                            AgentCanvasExecutionRow.created_at.asc()
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        return tuple(_execution(row) for row in rows)

    def list_members(self, execution_id: str) -> tuple[CanvasExecutionMembershipV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(AgentCanvasExecutionMemberRow)
                        .where(AgentCanvasExecutionMemberRow.execution_id == execution_id)
                        .order_by(AgentCanvasExecutionMemberRow.member_order.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        return tuple(_member(row) for row in rows)

    def update_member(
        self,
        execution_id: str,
        node_id: str,
        *,
        state: str,
        phase: str | None,
        now: datetime,
        waiting_for_node_ids: tuple[str, ...] = (),
        provider_task_id: str | None = None,
        prompt_metadata: dict[str, object] | None = None,
        run_intent_snapshot: NodeRunIntentSnapshotV2 | None = None,
        resolved_input_manifest: dict[str, object] | None = None,
        resolved_input_manifest_id: str | None = None,
        resolved_input_manifest_digest: str | None = None,
        effective_parameters: EffectiveMediaParameterSnapshotV2 | None = None,
        parameter_compilation_snapshot: VideoParameterCompilationSnapshotV2 | None = None,
        omitted_optional_inputs: tuple[dict[str, object], ...] | None = None,
        error: CanvasNodeErrorV2 | None = None,
        event_type: str | None = None,
        event_payload: dict[str, object] | None = None,
        expected_state: str | None = None,
        expected_phase: str | None = None,
        expected_lease_generation: int | None = None,
        expected_provider_task_id: str | None = None,
        validate_expected_phase: bool = False,
        validate_expected_provider_task_id: bool = False,
    ) -> bool:
        timestamp = now.isoformat()
        try:
            with self._database.engine.begin() as connection:
                current = (
                    connection.execute(
                        select(AgentCanvasExecutionMemberRow).where(
                            AgentCanvasExecutionMemberRow.execution_id == execution_id,
                            AgentCanvasExecutionMemberRow.node_id == node_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if current is None:
                    raise _error("execution_member_not_found", "Execution member was not found.")
                if (
                    expected_state is not None
                    and str(current["state"]) != expected_state
                    or validate_expected_phase
                    and cast(str | None, current["phase"]) != expected_phase
                    or validate_expected_provider_task_id
                    and cast(str | None, current["provider_task_id"]) != expected_provider_task_id
                ):
                    return False
                if expected_lease_generation is not None:
                    lease = (
                        connection.execute(
                            select(AgentCanvasNodeLeaseRow).where(
                                AgentCanvasNodeLeaseRow.execution_id == execution_id,
                                AgentCanvasNodeLeaseRow.node_id == node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if lease is None or int(lease["generation"]) != expected_lease_generation:
                        return False
                row = connection.execute(
                    update(AgentCanvasExecutionMemberRow)
                    .where(
                        AgentCanvasExecutionMemberRow.execution_id == execution_id,
                        AgentCanvasExecutionMemberRow.node_id == node_id,
                    )
                    .values(
                        state=state,
                        phase=phase,
                        waiting_for_node_ids_json=json.dumps(list(waiting_for_node_ids)),
                        provider_task_id=provider_task_id,
                        **(
                            {"prompt_metadata_json": json.dumps(prompt_metadata, sort_keys=True)}
                            if prompt_metadata is not None
                            else {}
                        ),
                        **(
                            {
                                "run_intent_snapshot_id": run_intent_snapshot.snapshot_id,
                                "run_intent_snapshot_json": run_intent_snapshot.model_dump_json(),
                                "run_intent_snapshot_digest": run_intent_snapshot.snapshot_digest,
                            }
                            if run_intent_snapshot is not None
                            else {}
                        ),
                        **(
                            {
                                "resolved_input_manifest_id": resolved_input_manifest_id,
                                "resolved_input_manifest_json": json.dumps(
                                    resolved_input_manifest,
                                    sort_keys=True,
                                ),
                                "resolved_input_manifest_digest": resolved_input_manifest_digest,
                            }
                            if resolved_input_manifest is not None
                            else {}
                        ),
                        **(
                            {
                                "effective_parameters_json": effective_parameters.model_dump_json(),
                            }
                            if effective_parameters is not None
                            else {}
                        ),
                        **(
                            {
                                "parameter_compilation_snapshot_id": (
                                    parameter_compilation_snapshot.snapshot_id
                                )
                            }
                            if parameter_compilation_snapshot is not None
                            else {}
                        ),
                        **(
                            {
                                "omitted_optional_inputs_json": json.dumps(
                                    omitted_optional_inputs,
                                    sort_keys=True,
                                ),
                            }
                            if omitted_optional_inputs is not None
                            else {}
                        ),
                        error_json=error.model_dump_json() if error else None,
                        updated_at=timestamp,
                    )
                )
                if row.rowcount != 1:
                    raise _error("execution_member_not_found", "Execution member was not found.")
                if event_type:
                    execution = self._execution_in_transaction(connection, execution_id)
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=execution.workflow_id,
                            execution_id=execution_id,
                            node_id=node_id,
                            event_type=event_type,
                            created_at=timestamp,
                            payload=event_payload or {},
                        ),
                    )
                if state in {"failed", "cancelled"}:
                    self._reconcile_terminal_leases_in_transaction(
                        connection,
                        execution_id,
                        now=now,
                    )
                return True
        except V2PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from exc

    def set_execution_status(
        self,
        execution_id: str,
        status: str,
        *,
        now: datetime,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> CanvasExecutionRecordV2:
        timestamp = now.isoformat()
        try:
            with self._database.engine.begin() as connection:
                execution = self._execution_in_transaction(connection, execution_id)
                connection.execute(
                    update(AgentCanvasExecutionRow)
                    .where(AgentCanvasExecutionRow.execution_id == execution_id)
                    .values(status=status, updated_at=timestamp)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=execution.workflow_id,
                        execution_id=execution_id,
                        event_type=event_type,
                        created_at=timestamp,
                        payload=payload or {},
                    ),
                )
                if status in _TERMINAL_EXECUTION_STATES:
                    self._reconcile_terminal_leases_in_transaction(
                        connection,
                        execution_id,
                        now=now,
                    )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        return self.get_execution(execution_id)

    def reconcile_terminal_leases(self, execution_id: str, *, now: datetime) -> int:
        """Close current claimed leases that no longer have runnable work."""

        try:
            with self._database.engine.begin() as connection:
                return self._reconcile_terminal_leases_in_transaction(
                    connection,
                    execution_id,
                    now=now,
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Lease storage is unavailable.") from error

    def _reconcile_terminal_leases_in_transaction(
        self,
        connection: Connection,
        execution_id: str,
        *,
        now: datetime,
    ) -> int:
        execution = self._execution_in_transaction(connection, execution_id)
        members = {
            str(row["node_id"]): str(row["state"])
            for row in connection.execute(
                select(AgentCanvasExecutionMemberRow).where(
                    AgentCanvasExecutionMemberRow.execution_id == execution_id
                )
            ).mappings()
        }
        leases = connection.execute(
            select(AgentCanvasNodeLeaseRow).where(
                AgentCanvasNodeLeaseRow.execution_id == execution_id,
                AgentCanvasNodeLeaseRow.state == "claimed",
            )
        ).mappings()
        timestamp = now.isoformat()
        reconciled = 0
        for lease in leases:
            if (
                execution.status not in _TERMINAL_EXECUTION_STATES
                and members.get(str(lease["node_id"])) not in _TERMINAL_MEMBER_STATES
            ):
                continue
            expired = datetime.fromisoformat(str(lease["expires_at"])) <= now
            next_state = "expired" if expired else "released"
            changed = connection.execute(
                update(AgentCanvasNodeLeaseRow)
                .where(
                    AgentCanvasNodeLeaseRow.lease_id == lease["lease_id"],
                    AgentCanvasNodeLeaseRow.execution_id == execution_id,
                    AgentCanvasNodeLeaseRow.node_id == lease["node_id"],
                    AgentCanvasNodeLeaseRow.owner_id == lease["owner_id"],
                    AgentCanvasNodeLeaseRow.generation == lease["generation"],
                    AgentCanvasNodeLeaseRow.state == "claimed",
                )
                .values(state=next_state, heartbeat_at=timestamp)
            )
            if changed.rowcount != 1:
                continue
            reconciled += 1
            self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=execution.workflow_id,
                    execution_id=execution_id,
                    node_id=str(lease["node_id"]),
                    event_type="node_lease_reconciled",
                    created_at=timestamp,
                    payload={
                        "lease_id": str(lease["lease_id"]),
                        "owner_id": str(lease["owner_id"]),
                        "generation": int(lease["generation"]),
                        "before_state": "claimed",
                        "after_state": next_state,
                        "execution_status": execution.status,
                        "member_state": members.get(str(lease["node_id"])),
                    },
                ),
            )
        return reconciled

    def request_cancel(self, execution_id: str, *, now: datetime) -> CanvasExecutionRecordV2:
        execution = self.get_execution(execution_id)
        if execution.status not in _ACTIVE_EXECUTION_STATES:
            raise _error("execution_already_terminal", "Execution is already terminal.")
        try:
            with self._database.engine.begin() as connection:
                connection.execute(
                    update(AgentCanvasExecutionRow)
                    .where(AgentCanvasExecutionRow.execution_id == execution_id)
                    .values(cancel_requested=True, updated_at=now.isoformat())
                )
        except SQLAlchemyError as error:
            raise _error("execution_cancel_failed", "Execution cancellation failed.") from error
        return self.get_execution(execution_id)

    def claim_lease(
        self,
        execution_id: str,
        node_id: str,
        *,
        owner_id: str,
        now: datetime,
        ttl: timedelta,
    ) -> NodeExecutionLeaseV2 | None:
        timestamp = now.isoformat()
        expires_at = (now + ttl).isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    execution = self._execution_in_transaction(connection, execution_id)
                    row = (
                        connection.execute(
                            select(AgentCanvasNodeLeaseRow).where(
                                AgentCanvasNodeLeaseRow.execution_id == execution_id,
                                AgentCanvasNodeLeaseRow.node_id == node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if (
                        row is not None
                        and str(row["state"]) == "claimed"
                        and datetime.fromisoformat(str(row["expires_at"])) > now
                    ):
                        connection.rollback()
                        return None
                    generation = int(row["generation"]) + 1 if row is not None else 1
                    values = {
                        "workflow_id": execution.workflow_id,
                        "execution_id": execution_id,
                        "node_id": node_id,
                        "owner_id": owner_id,
                        "generation": generation,
                        "state": "claimed",
                        "heartbeat_at": timestamp,
                        "expires_at": expires_at,
                    }
                    if row is None:
                        connection.execute(
                            insert(AgentCanvasNodeLeaseRow).values(
                                lease_id=f"lease_{uuid4().hex}",
                                **values,
                            )
                        )
                    else:
                        connection.execute(
                            update(AgentCanvasNodeLeaseRow)
                            .where(
                                AgentCanvasNodeLeaseRow.execution_id == execution_id,
                                AgentCanvasNodeLeaseRow.node_id == node_id,
                                AgentCanvasNodeLeaseRow.generation == int(row["generation"]),
                            )
                            .values(**values)
                        )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Lease storage is unavailable.") from error
        return NodeExecutionLeaseV2(
            **values,
        )

    def complete_lease(self, lease: NodeExecutionLeaseV2, *, now: datetime) -> bool:
        try:
            with self._database.engine.begin() as connection:
                result = connection.execute(
                    update(AgentCanvasNodeLeaseRow)
                    .where(
                        AgentCanvasNodeLeaseRow.execution_id == lease.execution_id,
                        AgentCanvasNodeLeaseRow.node_id == lease.node_id,
                        AgentCanvasNodeLeaseRow.owner_id == lease.owner_id,
                        AgentCanvasNodeLeaseRow.generation == lease.generation,
                        AgentCanvasNodeLeaseRow.state == "claimed",
                    )
                    .values(
                        state="completed",
                        heartbeat_at=now.isoformat(),
                    )
                )
                return result.rowcount == 1
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Lease storage is unavailable.") from error

    def renew_lease(
        self,
        lease: NodeExecutionLeaseV2,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> NodeExecutionLeaseV2:
        expires_at = now + ttl
        try:
            with self._database.engine.begin() as connection:
                result = connection.execute(
                    update(AgentCanvasNodeLeaseRow)
                    .where(
                        AgentCanvasNodeLeaseRow.execution_id == lease.execution_id,
                        AgentCanvasNodeLeaseRow.node_id == lease.node_id,
                        AgentCanvasNodeLeaseRow.owner_id == lease.owner_id,
                        AgentCanvasNodeLeaseRow.generation == lease.generation,
                        AgentCanvasNodeLeaseRow.state == "claimed",
                        AgentCanvasNodeLeaseRow.expires_at > now.isoformat(),
                    )
                    .values(
                        heartbeat_at=now.isoformat(),
                        expires_at=expires_at.isoformat(),
                    )
                )
                if result.rowcount != 1:
                    raise _error(
                        "stale_execution_lease",
                        "Execution lease ownership was lost.",
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Lease storage is unavailable.") from error
        return lease.model_copy(update={"heartbeat_at": now, "expires_at": expires_at})

    def assert_current_lease(
        self,
        lease: NodeExecutionLeaseV2,
        *,
        now: datetime,
    ) -> None:
        try:
            with self._database.engine.connect() as connection:
                exists = connection.execute(
                    select(AgentCanvasNodeLeaseRow.lease_id).where(
                        AgentCanvasNodeLeaseRow.execution_id == lease.execution_id,
                        AgentCanvasNodeLeaseRow.node_id == lease.node_id,
                        AgentCanvasNodeLeaseRow.owner_id == lease.owner_id,
                        AgentCanvasNodeLeaseRow.generation == lease.generation,
                        AgentCanvasNodeLeaseRow.state == "claimed",
                        AgentCanvasNodeLeaseRow.expires_at > now.isoformat(),
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Lease storage is unavailable.") from error
        if exists is None:
            raise _error("stale_execution_lease", "Execution lease ownership was lost.")

    def put_provider_task(self, task: CanvasProviderTaskV2, *, now: datetime) -> bool:
        """Persist one provider transition unless a newer terminal lease won."""

        values = {
            **task.model_dump(mode="json"),
            "result_descriptor_json": json.dumps(task.result_descriptor, sort_keys=True),
            "error_json": task.error.model_dump_json() if task.error else None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        values.pop("result_descriptor")
        values.pop("error")
        try:
            with self._database.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(AgentCanvasProviderTaskRow).where(
                            AgentCanvasProviderTaskRow.task_id == task.task_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None:
                    connection.execute(insert(AgentCanvasProviderTaskRow).values(**values))
                else:
                    existing_generation = int(existing["lease_generation"])
                    existing_status = str(existing["status"])
                    if existing_generation > task.lease_generation or (
                        existing_status == "succeeded" and task.status != "succeeded"
                    ):
                        return False
                    values.pop("created_at")
                    connection.execute(
                        update(AgentCanvasProviderTaskRow)
                        .where(AgentCanvasProviderTaskRow.task_id == task.task_id)
                        .values(**values)
                    )
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Provider task storage failed.") from error
        return True

    def put_submission_intent(
        self,
        intent: ProviderSubmissionIntentV2,
    ) -> ProviderSubmissionIntentV2:
        values = intent.model_dump(mode="json")
        try:
            with self._database.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(AgentCanvasProviderSubmissionIntentRow).where(
                            AgentCanvasProviderSubmissionIntentRow.logical_operation_key
                            == intent.logical_operation_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    stored = _submission_intent(existing)
                    if stored.request_digest != intent.request_digest:
                        raise _error(
                            "provider_submission_intent_conflict",
                            "Provider submission intent content is immutable.",
                        )
                    return stored
                connection.execute(insert(AgentCanvasProviderSubmissionIntentRow).values(**values))
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Provider submission intent storage failed.",
            ) from error
        return intent

    def get_submission_intent(self, intent_id: str) -> ProviderSubmissionIntentV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasProviderSubmissionIntentRow).where(
                            AgentCanvasProviderSubmissionIntentRow.intent_id == intent_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Provider submission intent storage failed.",
            ) from error
        if row is None:
            raise _error(
                "provider_submission_intent_not_found",
                "Provider submission intent was not found.",
            )
        return _submission_intent(row)

    def list_submission_intents(
        self,
        *,
        execution_id: str | None = None,
    ) -> tuple[ProviderSubmissionIntentV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                statement = select(AgentCanvasProviderSubmissionIntentRow)
                if execution_id is not None:
                    statement = statement.where(
                        AgentCanvasProviderSubmissionIntentRow.execution_id == execution_id
                    )
                rows = (
                    connection.execute(
                        statement.order_by(AgentCanvasProviderSubmissionIntentRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Provider submission intent storage failed.",
            ) from error
        return tuple(_submission_intent(row) for row in rows)

    def update_submission_intent(
        self,
        intent: ProviderSubmissionIntentV2,
        *,
        expected_state: str,
    ) -> ProviderSubmissionIntentV2:
        values = intent.model_dump(mode="json")
        values.pop("intent_id")
        try:
            with self._database.engine.begin() as connection:
                result = connection.execute(
                    update(AgentCanvasProviderSubmissionIntentRow)
                    .where(
                        AgentCanvasProviderSubmissionIntentRow.intent_id == intent.intent_id,
                        AgentCanvasProviderSubmissionIntentRow.state == expected_state,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    row = (
                        connection.execute(
                            select(AgentCanvasProviderSubmissionIntentRow).where(
                                AgentCanvasProviderSubmissionIntentRow.intent_id == intent.intent_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise _error(
                            "provider_submission_intent_not_found",
                            "Provider submission intent was not found.",
                        )
                    current = _submission_intent(row)
                    if current.request_digest == intent.request_digest and current == intent:
                        return current
                    raise _error(
                        "provider_submission_intent_transition_conflict",
                        "Provider submission intent is no longer in the expected state.",
                    )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Provider submission intent storage failed.",
            ) from error
        return intent

    def list_recoverable_tasks(self) -> tuple[CanvasProviderTaskV2, ...]:
        return self.list_provider_tasks(
            statuses=("submitted", "waiting", "recovering"),
        )

    def list_provider_tasks(
        self,
        *,
        execution_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[CanvasProviderTaskV2, ...]:
        try:
            with self._database.engine.connect() as connection:
                statement = select(AgentCanvasProviderTaskRow)
                if execution_id is not None:
                    statement = statement.where(
                        AgentCanvasProviderTaskRow.execution_id == execution_id
                    )
                if statuses is not None:
                    statement = statement.where(AgentCanvasProviderTaskRow.status.in_(statuses))
                rows = (
                    connection.execute(
                        statement.order_by(AgentCanvasProviderTaskRow.created_at.asc())
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise _error("execution_persistence_failed", "Provider task storage failed.") from error
        return tuple(_provider_task(row) for row in rows)

    def get_provider_task(self, task_id: str) -> CanvasProviderTaskV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasProviderTaskRow).where(
                            AgentCanvasProviderTaskRow.task_id == task_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed",
                "Provider task storage failed.",
            ) from error
        if row is None:
            raise _error("provider_task_not_found", "Provider task was not found.")
        return _provider_task(row)

    def _insert_member(
        self,
        connection: Connection,
        *,
        execution_id: str,
        workflow_id: str,
        node_id: str,
        member_order: int,
        now: str,
        member_id: str | None = None,
        run_intent_snapshot: NodeRunIntentSnapshotV2 | None = None,
        prompt_metadata: dict[str, object] | None = None,
    ) -> None:
        connection.execute(
            insert(AgentCanvasExecutionMemberRow).values(
                member_id=member_id or f"member_{uuid4().hex}",
                execution_id=execution_id,
                workflow_id=workflow_id,
                node_id=node_id,
                member_order=member_order,
                state="queued",
                phase="queued",
                attempt_no=0,
                waiting_for_node_ids_json="[]",
                provider_task_id=None,
                run_intent_snapshot_id=(
                    run_intent_snapshot.snapshot_id if run_intent_snapshot else None
                ),
                run_intent_snapshot_json=(
                    run_intent_snapshot.model_dump_json() if run_intent_snapshot else None
                ),
                run_intent_snapshot_digest=(
                    run_intent_snapshot.snapshot_digest if run_intent_snapshot else None
                ),
                resolved_input_manifest_id=None,
                resolved_input_manifest_json=None,
                resolved_input_manifest_digest=None,
                effective_parameters_json=None,
                omitted_optional_inputs_json="[]",
                prompt_metadata_json=json.dumps(prompt_metadata or {}, sort_keys=True),
                error_json=None,
                updated_at=now,
            )
        )
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node_id,
                event_type="node_run_queued",
                created_at=now,
                payload={},
            ),
        )

    @staticmethod
    def _next_member_order(connection: Connection, execution_id: str) -> int:
        return (
            int(
                connection.execute(
                    select(
                        func.coalesce(func.max(AgentCanvasExecutionMemberRow.member_order), -1)
                    ).where(AgentCanvasExecutionMemberRow.execution_id == execution_id)
                ).scalar_one()
            )
            + 1
        )

    @staticmethod
    def _member_exists(connection: Connection, execution_id: str, node_id: str) -> bool:
        return (
            connection.execute(
                select(AgentCanvasExecutionMemberRow.member_id).where(
                    AgentCanvasExecutionMemberRow.execution_id == execution_id,
                    AgentCanvasExecutionMemberRow.node_id == node_id,
                )
            ).scalar_one_or_none()
            is not None
        )

    @staticmethod
    def _active_execution_in_transaction(
        connection: Connection,
        workflow_id: str,
    ) -> CanvasExecutionRecordV2 | None:
        row = (
            connection.execute(
                select(AgentCanvasExecutionRow)
                .where(
                    AgentCanvasExecutionRow.workflow_id == workflow_id,
                    AgentCanvasExecutionRow.status.in_(_ACTIVE_EXECUTION_STATES),
                )
                .order_by(AgentCanvasExecutionRow.created_at.asc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        return _execution(row) if row is not None else None

    @staticmethod
    def _load_admission(
        connection: Connection,
        command: CanvasExecutionStartCommandV2,
    ) -> CanvasExecutionStartResultV2 | None:
        row = (
            connection.execute(
                select(AgentCanvasExecutionAdmissionRow).where(
                    AgentCanvasExecutionAdmissionRow.idempotency_key == command.idempotency_key
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if (
            str(row["workflow_id"]) != command.workflow_id
            or str(row["request_digest"]) != command.request_digest
        ):
            raise _error(
                "idempotency_conflict",
                "Idempotency key was reused with another run request.",
            )
        return CanvasExecutionStartResultV2.model_validate_json(str(row["result_json"]))

    @staticmethod
    def _validate_start_intent(
        connection: Connection,
        command: CanvasExecutionStartCommandV2,
    ) -> None:
        workflow_revision = connection.execute(
            select(AgentCanvasWorkflowRow.revision).where(
                AgentCanvasWorkflowRow.workflow_id == command.workflow_id
            )
        ).scalar_one_or_none()
        if workflow_revision is None:
            raise _error("workflow_not_found", "Workflow was not found.")
        if int(workflow_revision) != command.expected_workflow_revision:
            raise _error(
                "run_intent_stale",
                "Workflow authoring changed before Run admission.",
            )
        for intent in command.member_intents:
            node_revision = connection.execute(
                select(AgentCanvasNodeRow.revision).where(
                    AgentCanvasNodeRow.workflow_id == command.workflow_id,
                    AgentCanvasNodeRow.node_id == intent.node_id,
                )
            ).scalar_one_or_none()
            if node_revision is None or int(node_revision) != intent.node_revision:
                raise _error("run_intent_stale", "Node authoring changed before Run admission.")
            current_bindings = (
                connection.execute(
                    select(AgentCanvasBindingRow).where(
                        AgentCanvasBindingRow.workflow_id == command.workflow_id,
                        AgentCanvasBindingRow.target_node_id == intent.node_id,
                        AgentCanvasBindingRow.enabled.is_(True),
                    )
                )
                .mappings()
                .all()
            )
            current_ids = {str(row["binding_id"]) for row in current_bindings}
            expected_ids = {binding.binding_id for binding in intent.binding_snapshots}
            if current_ids != expected_ids:
                raise _error("run_intent_stale", "Bindings changed before Run admission.")
            for asset_id, expected_digest in intent.expected_source_asset_digests.items():
                digest = connection.execute(
                    select(AssetVersionRow.sha256)
                    .where(AssetVersionRow.asset_id == asset_id)
                    .order_by(AssetVersionRow.version_no.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if digest is None or str(digest) != expected_digest:
                    raise _error("run_intent_stale", "Source Asset changed before Run admission.")

    @staticmethod
    def _snapshot_for_intent(
        command: CanvasExecutionStartCommandV2,
        intent: CanvasExecutionMemberIntentV2,
        *,
        execution_id: str,
        member_id: str,
    ) -> NodeRunIntentSnapshotV2:
        node = intent.frozen_node
        return NodeRunIntentSnapshotV2(
            snapshot_id=intent.snapshot_id,
            workflow_id=command.workflow_id,
            execution_id=execution_id,
            member_id=member_id,
            node_id=intent.node_id,
            node_revision=intent.node_revision,
            node_type=cast(str, node["node_type"]),
            creative_role=cast(str, node["creative_role"]),
            role_contract_version=cast(str, node["role_contract_version"]),
            summary_prompt=cast(str | None, node.get("summary_prompt")),
            generation_prompt=cast(str | None, node.get("generation_prompt")),
            structured_content_digest=_json_digest(node.get("structured_content", {})),
            model_selection_mode=cast(str, node["model_selection_mode"]),
            model_ref=cast(str | None, node.get("model_ref")),
            requested_parameters=cast(dict[str, object], node.get("parameters", {})),
            binding_snapshots=intent.binding_snapshots,
            snapshot_digest=intent.snapshot_digest,
            created_at=command.created_at,
        )

    @staticmethod
    def _execution_in_transaction(
        connection: Connection,
        execution_id: str,
    ) -> CanvasExecutionRecordV2:
        row = (
            connection.execute(
                select(AgentCanvasExecutionRow).where(
                    AgentCanvasExecutionRow.execution_id == execution_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _error("execution_not_found", "Execution was not found.")
        return _execution(row)


def _execution(row: RowMapping) -> CanvasExecutionRecordV2:
    return CanvasExecutionRecordV2(
        execution_id=str(row["execution_id"]),
        workflow_id=str(row["workflow_id"]),
        status=cast(str, row["status"]),
        scope=cast(str, row["scope"]),
        cancel_requested=bool(row["cancel_requested"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _member(row: RowMapping) -> CanvasExecutionMembershipV2:
    error_json = cast(str | None, row["error_json"])
    return CanvasExecutionMembershipV2(
        member_id=str(row["member_id"]),
        execution_id=str(row["execution_id"]),
        workflow_id=str(row["workflow_id"]),
        node_id=str(row["node_id"]),
        state=cast(str, row["state"]),
        phase=cast(str | None, row["phase"]),
        attempt_no=int(row["attempt_no"]),
        waiting_for_node_ids=tuple(json.loads(str(row["waiting_for_node_ids_json"]))),
        provider_task_id=cast(str | None, row["provider_task_id"]),
        run_intent_snapshot_id=cast(str | None, row["run_intent_snapshot_id"]),
        run_intent_snapshot=(
            NodeRunIntentSnapshotV2.model_validate_json(str(row["run_intent_snapshot_json"]))
            if row["run_intent_snapshot_json"]
            else None
        ),
        run_intent_snapshot_digest=cast(str | None, row["run_intent_snapshot_digest"]),
        resolved_input_manifest_id=cast(str | None, row["resolved_input_manifest_id"]),
        resolved_input_manifest=(
            json.loads(str(row["resolved_input_manifest_json"]))
            if row["resolved_input_manifest_json"]
            else None
        ),
        resolved_input_manifest_digest=cast(
            str | None,
            row["resolved_input_manifest_digest"],
        ),
        effective_parameters=(
            EffectiveMediaParameterSnapshotV2.model_validate_json(
                str(row["effective_parameters_json"])
            )
            if row["effective_parameters_json"]
            else None
        ),
        parameter_compilation_snapshot_id=cast(
            str | None, row["parameter_compilation_snapshot_id"]
        ),
        omitted_optional_inputs=tuple(json.loads(str(row["omitted_optional_inputs_json"]))),
        prompt_metadata=json.loads(str(row["prompt_metadata_json"])),
        error=CanvasNodeErrorV2.model_validate_json(error_json) if error_json else None,
        updated_at=str(row["updated_at"]),
    )


def _provider_task(row: RowMapping) -> CanvasProviderTaskV2:
    error_json = cast(str | None, row["error_json"])
    return CanvasProviderTaskV2(
        task_id=str(row["task_id"]),
        workflow_id=str(row["workflow_id"]),
        execution_id=str(row["execution_id"]),
        node_id=str(row["node_id"]),
        submission_intent_id=cast(str | None, row["submission_intent_id"]),
        provider=str(row["provider"]),
        remote_task_id=cast(str | None, row["remote_task_id"]),
        status=cast(str, row["status"]),
        lease_generation=int(row["lease_generation"]),
        next_poll_at=cast(str | None, row["next_poll_at"]),
        recovery_deadline=str(row["recovery_deadline"]),
        result_descriptor=json.loads(str(row["result_descriptor_json"])),
        error=CanvasNodeErrorV2.model_validate_json(error_json) if error_json else None,
    )


def _submission_intent(row: RowMapping) -> ProviderSubmissionIntentV2:
    return ProviderSubmissionIntentV2(
        intent_id=str(row["intent_id"]),
        logical_operation_key=str(row["logical_operation_key"]),
        request_digest=str(row["request_digest"]),
        workflow_id=str(row["workflow_id"]),
        execution_id=str(row["execution_id"]),
        member_id=str(row["member_id"]),
        node_id=str(row["node_id"]),
        provider=str(row["provider"]),
        model_id=str(row["model_id"]),
        attempt_no=int(row["attempt_no"]),
        supports_idempotency_token=bool(row["supports_idempotency_token"]),
        supports_remote_task_lookup=bool(row["supports_remote_task_lookup"]),
        provider_idempotency_token=cast(str | None, row["provider_idempotency_token"]),
        remote_task_id=cast(str | None, row["remote_task_id"]),
        provider_task_id=cast(str | None, row["provider_task_id"]),
        state=cast(str, row["state"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_runtime_repository")


def _json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
