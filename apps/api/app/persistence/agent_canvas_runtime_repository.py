"""SQLite ownership and compare-and-set operations for Agent Canvas runtime."""

from __future__ import annotations

import json
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
    AgentCanvasExecutionMemberRow,
    AgentCanvasExecutionRow,
    AgentCanvasNodeLeaseRow,
    AgentCanvasProviderTaskRow,
    AgentCanvasVideoParameterCompilationSnapshotRow,
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


_ACTIVE_EXECUTION_STATES = ("queued", "running", "waiting")


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
        except SQLAlchemyError as error:
            raise _error(
                "execution_persistence_failed", "Execution storage is unavailable."
            ) from error
        return self.get_execution(execution_id)

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
    ) -> None:
        connection.execute(
            insert(AgentCanvasExecutionMemberRow).values(
                member_id=f"member_{uuid4().hex}",
                execution_id=execution_id,
                workflow_id=workflow_id,
                node_id=node_id,
                member_order=member_order,
                state="queued",
                phase="queued",
                attempt_no=0,
                waiting_for_node_ids_json="[]",
                provider_task_id=None,
                run_intent_snapshot_id=None,
                run_intent_snapshot_json=None,
                run_intent_snapshot_digest=None,
                resolved_input_manifest_id=None,
                resolved_input_manifest_json=None,
                resolved_input_manifest_digest=None,
                effective_parameters_json=None,
                omitted_optional_inputs_json="[]",
                prompt_metadata_json="{}",
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
        provider=str(row["provider"]),
        remote_task_id=cast(str | None, row["remote_task_id"]),
        status=cast(str, row["status"]),
        lease_generation=int(row["lease_generation"]),
        next_poll_at=cast(str | None, row["next_poll_at"]),
        recovery_deadline=str(row["recovery_deadline"]),
        result_descriptor=json.loads(str(row["result_descriptor_json"])),
        error=CanvasNodeErrorV2.model_validate_json(error_json) if error_json else None,
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_runtime_repository")
