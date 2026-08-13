"""Single SQLite authority for terminal Agent Canvas node results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import cast

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasExecutionMemberRow,
    AgentCanvasExecutionResultCommitRow,
    AgentCanvasExecutionRow,
    AgentCanvasNodeLeaseRow,
    AgentCanvasNodeRow,
    AgentCanvasPostReadyEffectRow,
    AgentCanvasProviderTaskRow,
)
from app.schemas.agent_canvas_runtime_authority import (
    CanvasExecutionResultCommitCommandV2,
    CanvasExecutionResultCommitReceiptV2,
    CanvasPostReadyEffectV2,
)
from app.schemas.v2_asset_library import AssetRecordCreate, AssetVersionCreate
from app.schemas.v2_persistence import V2EventInsert


FaultInjector = Callable[[str], None]
_TERMINAL_MEMBER_STATES = ("succeeded", "failed", "cancelled")


class AgentCanvasResultCommitRepository:
    """Publish one fenced terminal result and all projections in one transaction."""

    def __init__(
        self,
        database: V2Database,
        assets: V2AssetLibraryRepository,
        events: EventRepository,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        if assets.database is not database or events.database is not database:
            raise ValueError("Result authority repositories must share one database.")
        self._database = database
        self._assets = assets
        self._events = events
        self._fault = fault_injector or (lambda _boundary: None)

    def commit(
        self,
        command: CanvasExecutionResultCommitCommandV2,
    ) -> CanvasExecutionResultCommitReceiptV2:
        timestamp = command.committed_at.isoformat()
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing = (
                        connection.execute(
                            select(AgentCanvasExecutionResultCommitRow).where(
                                AgentCanvasExecutionResultCommitRow.logical_result_key
                                == command.logical_result_key
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is not None:
                        receipt = _receipt(existing)
                        if receipt.payload_digest != command.payload_digest:
                            raise _error(
                                "execution_result_payload_conflict",
                                "Execution result identity is immutable.",
                            )
                        connection.commit()
                        return receipt
                    self._assert_current_lease(connection, command)
                    member = (
                        connection.execute(
                            select(AgentCanvasExecutionMemberRow).where(
                                AgentCanvasExecutionMemberRow.member_id == command.member_id,
                                AgentCanvasExecutionMemberRow.execution_id == command.execution_id,
                                AgentCanvasExecutionMemberRow.node_id == command.node_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if member is None:
                        raise _error(
                            "execution_member_not_found",
                            "Execution member was not found.",
                        )
                    if str(member["state"]) in _TERMINAL_MEMBER_STATES:
                        raise _error(
                            "execution_result_terminal_conflict",
                            "Execution member already has a terminal result.",
                        )
                    asset_id, version_id = self._register_asset(connection, command)
                    self._fault("after_asset")
                    node_status = {
                        "succeeded": "ready",
                        "failed": "failed",
                        "cancelled": "draft",
                    }[command.outcome]
                    node_values: dict[str, object] = {
                        "status": node_status,
                        "error_json": command.error.model_dump_json() if command.error else None,
                        "updated_at": timestamp,
                    }
                    prepared = command.prepared_result
                    if command.outcome == "succeeded" and prepared is not None:
                        if asset_id is not None:
                            node_values["output_asset_id"] = asset_id
                        if prepared.structured_content is not None:
                            node_values["structured_content_json"] = json.dumps(
                                prepared.structured_content,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                    changed = connection.execute(
                        update(AgentCanvasNodeRow)
                        .where(
                            AgentCanvasNodeRow.workflow_id == command.workflow_id,
                            AgentCanvasNodeRow.node_id == command.node_id,
                            AgentCanvasNodeRow.status != "ready",
                        )
                        .values(**node_values)
                    )
                    if changed.rowcount != 1:
                        raise _error(
                            "execution_result_terminal_conflict",
                            "Canvas Node already has a terminal Ready result.",
                        )
                    self._fault("after_node")
                    connection.execute(
                        update(AgentCanvasExecutionMemberRow)
                        .where(AgentCanvasExecutionMemberRow.member_id == command.member_id)
                        .values(
                            state=command.outcome,
                            phase=None,
                            error_json=(command.error.model_dump_json() if command.error else None),
                            updated_at=timestamp,
                        )
                    )
                    self._fault("after_member")
                    provider_task_id = command.provider_task_id or (
                        prepared.provider_task_id if prepared is not None else None
                    )
                    if provider_task_id is not None:
                        provider_status = command.outcome
                        connection.execute(
                            update(AgentCanvasProviderTaskRow)
                            .where(
                                AgentCanvasProviderTaskRow.task_id == provider_task_id,
                                AgentCanvasProviderTaskRow.lease_generation
                                <= command.lease_generation,
                            )
                            .values(
                                status=provider_status,
                                lease_generation=command.lease_generation,
                                next_poll_at=None,
                                error_json=(
                                    command.error.model_dump_json() if command.error else None
                                ),
                                updated_at=timestamp,
                            )
                        )
                    self._fault("after_provider_task")
                    aggregate = self._derive_execution_status(connection, command.execution_id)
                    connection.execute(
                        update(AgentCanvasExecutionRow)
                        .where(AgentCanvasExecutionRow.execution_id == command.execution_id)
                        .values(status=aggregate, updated_at=timestamp)
                    )
                    connection.execute(
                        update(AgentCanvasNodeLeaseRow)
                        .where(
                            AgentCanvasNodeLeaseRow.execution_id == command.execution_id,
                            AgentCanvasNodeLeaseRow.node_id == command.node_id,
                            AgentCanvasNodeLeaseRow.owner_id == command.lease_owner_id,
                            AgentCanvasNodeLeaseRow.generation == command.lease_generation,
                            AgentCanvasNodeLeaseRow.state == "claimed",
                        )
                        .values(state="completed", heartbeat_at=timestamp)
                    )
                    self._fault("after_runtime")
                    event_cursor = self._append_events(
                        connection,
                        command,
                        asset_id=asset_id,
                        version_id=version_id,
                        execution_status=aggregate,
                    )
                    commit_id = (
                        "result_commit_"
                        + hashlib.sha256(command.logical_result_key.encode("utf-8")).hexdigest()[
                            :32
                        ]
                    )
                    receipt = CanvasExecutionResultCommitReceiptV2(
                        commit_id=commit_id,
                        logical_result_key=command.logical_result_key,
                        payload_digest=command.payload_digest,
                        outcome=command.outcome,
                        asset_id=asset_id,
                        version_id=version_id,
                        event_cursor=event_cursor,
                        committed_at=command.committed_at,
                    )
                    connection.execute(
                        insert(AgentCanvasExecutionResultCommitRow).values(
                            commit_id=commit_id,
                            logical_result_key=command.logical_result_key,
                            payload_digest=command.payload_digest,
                            workflow_id=command.workflow_id,
                            execution_id=command.execution_id,
                            member_id=command.member_id,
                            node_id=command.node_id,
                            outcome=command.outcome,
                            asset_id=asset_id,
                            version_id=version_id,
                            event_cursor=event_cursor,
                            receipt_json=receipt.model_dump_json(),
                            committed_at=timestamp,
                        )
                    )
                    self._insert_effects(connection, command, commit_id=commit_id)
                    self._fault("before_commit")
                    connection.commit()
                    return receipt
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "execution_result_commit_failed",
                "Execution result could not be committed.",
            ) from error

    def list_receipts(self, execution_id: str) -> tuple[CanvasExecutionResultCommitReceiptV2, ...]:
        with self._database.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(AgentCanvasExecutionResultCommitRow)
                    .where(AgentCanvasExecutionResultCommitRow.execution_id == execution_id)
                    .order_by(AgentCanvasExecutionResultCommitRow.committed_at.asc())
                )
                .mappings()
                .all()
            )
        return tuple(_receipt(row) for row in rows)

    def list_post_ready_effects(self, execution_id: str) -> tuple[CanvasPostReadyEffectV2, ...]:
        with self._database.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(AgentCanvasPostReadyEffectRow)
                    .join(
                        AgentCanvasExecutionResultCommitRow,
                        AgentCanvasExecutionResultCommitRow.commit_id
                        == AgentCanvasPostReadyEffectRow.source_commit_id,
                    )
                    .where(AgentCanvasExecutionResultCommitRow.execution_id == execution_id)
                    .order_by(AgentCanvasPostReadyEffectRow.effect_id.asc())
                )
                .mappings()
                .all()
            )
        return tuple(_effect(row) for row in rows)

    @staticmethod
    def _assert_current_lease(connection, command) -> None:
        lease = connection.execute(
            select(AgentCanvasNodeLeaseRow.lease_id).where(
                AgentCanvasNodeLeaseRow.execution_id == command.execution_id,
                AgentCanvasNodeLeaseRow.node_id == command.node_id,
                AgentCanvasNodeLeaseRow.owner_id == command.lease_owner_id,
                AgentCanvasNodeLeaseRow.generation == command.lease_generation,
                AgentCanvasNodeLeaseRow.state == "claimed",
                AgentCanvasNodeLeaseRow.expires_at > command.committed_at.isoformat(),
            )
        ).scalar_one_or_none()
        if lease is None:
            raise _error("stale_execution_lease", "Execution lease ownership was lost.")

    def _register_asset(self, connection, command):
        prepared = command.prepared_result
        if prepared is None or prepared.prepared_object is None:
            return None, None
        if prepared.asset_id is None or prepared.version_id is None:
            raise _error(
                "prepared_asset_identity_missing",
                "Prepared media is missing Asset identity.",
            )
        content = prepared.prepared_object
        facts = content.media_facts
        version = self._assets.register_asset_version_in_transaction(
            connection,
            AssetRecordCreate(
                asset_id=prepared.asset_id,
                media_type=content.media_type,
                source_type=prepared.asset_source_type,
                display_name=prepared.asset_display_name or content.filename,
            ),
            AssetVersionCreate(
                version_id=prepared.version_id,
                asset_id=prepared.asset_id,
                storage_key=content.storage_key,
                sha256=content.sha256,
                size_bytes=content.size_bytes,
                mime_type=content.mime_type,
                width=cast(int | None, facts.get("width")),
                height=cast(int | None, facts.get("height")),
                duration_seconds=cast(float | None, facts.get("duration_seconds")),
                provider=cast(str | None, prepared.asset_metadata.get("provider")),
                model_id=cast(str | None, prepared.asset_metadata.get("model_id")),
                source_workflow_id=command.workflow_id,
                source_node_id=command.node_id,
                metadata=prepared.asset_metadata,
                created_at=command.committed_at.isoformat(),
            ),
        )
        return version.asset_id, version.version_id

    def _append_events(
        self,
        connection,
        command,
        *,
        asset_id,
        version_id,
        execution_status,
    ) -> int:
        event_types = []
        if command.outcome == "succeeded":
            if asset_id is not None:
                event_types.append("asset_published")
            event_types.extend(("node_output_published", "node_ready"))
        elif command.outcome == "failed":
            event_types.append("node_failed")
        else:
            event_types.append("node_cancelled")
        last = None
        for ordinal, event_type in enumerate(event_types):
            last = self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=command.workflow_id,
                    execution_id=command.execution_id,
                    node_id=command.node_id,
                    asset_id=asset_id,
                    version_id=version_id,
                    transition_key=(f"result:{command.logical_result_key}:{ordinal}:{event_type}"),
                    event_type=event_type,
                    created_at=command.committed_at.isoformat(),
                    payload={"asset_id": asset_id, "version_id": version_id},
                ),
            )
        last = self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=command.workflow_id,
                execution_id=command.execution_id,
                node_id=command.node_id,
                asset_id=asset_id,
                version_id=version_id,
                transition_key=f"result:{command.logical_result_key}:runtime",
                event_type="runtime_snapshot_updated",
                created_at=command.committed_at.isoformat(),
                payload={"execution_status": execution_status},
            ),
        )
        terminal_event = {
            "completed": "execution_completed",
            "partial_completed": "execution_partial_completed",
            "failed": "execution_failed",
            "cancelled": "execution_cancelled",
        }.get(execution_status)
        if terminal_event is not None:
            last = self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=command.workflow_id,
                    execution_id=command.execution_id,
                    transition_key=(
                        f"result:{command.logical_result_key}:execution:{terminal_event}"
                    ),
                    event_type=terminal_event,
                    created_at=command.committed_at.isoformat(),
                    payload={"execution_status": execution_status},
                ),
            )
        return last.seq

    @staticmethod
    def _derive_execution_status(connection, execution_id: str) -> str:
        states = tuple(
            connection.execute(
                select(AgentCanvasExecutionMemberRow.state).where(
                    AgentCanvasExecutionMemberRow.execution_id == execution_id
                )
            ).scalars()
        )
        if any(state in {"queued", "running", "waiting"} for state in states):
            return "running"
        succeeded = sum(state == "succeeded" for state in states)
        if succeeded == len(states):
            return "completed"
        if succeeded:
            return "partial_completed"
        if states and all(state == "cancelled" for state in states):
            return "cancelled"
        return "failed"

    @staticmethod
    def _insert_effects(connection, command, *, commit_id: str) -> None:
        prepared = command.prepared_result
        if command.outcome != "succeeded" or prepared is None:
            return
        for ordinal, effect in enumerate(prepared.post_ready_effects):
            effect_id = (
                "effect_"
                + hashlib.sha256(
                    f"{commit_id}:{effect.effect_type}:{ordinal}".encode("utf-8")
                ).hexdigest()[:32]
            )
            payload_digest = _digest(effect.payload)
            connection.execute(
                insert(AgentCanvasPostReadyEffectRow).values(
                    effect_id=effect_id,
                    effect_type=effect.effect_type,
                    source_commit_id=commit_id,
                    workflow_id=command.workflow_id,
                    node_id=command.node_id,
                    payload_digest=payload_digest,
                    payload_json=json.dumps(effect.payload, sort_keys=True),
                    status="queued",
                    attempt_no=0,
                    lease_owner_id=None,
                    lease_generation=0,
                    lease_expires_at=None,
                    error_json=None,
                    created_at=command.committed_at.isoformat(),
                    updated_at=command.committed_at.isoformat(),
                )
            )


def _receipt(row: RowMapping) -> CanvasExecutionResultCommitReceiptV2:
    return CanvasExecutionResultCommitReceiptV2.model_validate_json(str(row["receipt_json"]))


def _effect(row: RowMapping) -> CanvasPostReadyEffectV2:
    return CanvasPostReadyEffectV2(
        effect_id=str(row["effect_id"]),
        effect_type=cast(str, row["effect_type"]),
        source_commit_id=str(row["source_commit_id"]),
        workflow_id=str(row["workflow_id"]),
        node_id=str(row["node_id"]),
        payload_digest=str(row["payload_digest"]),
        payload=json.loads(str(row["payload_json"])),
        status=cast(str, row["status"]),
        attempt_no=int(row["attempt_no"]),
        lease_owner_id=cast(str | None, row["lease_owner_id"]),
        lease_generation=int(row["lease_generation"]),
        lease_expires_at=cast(str | None, row["lease_expires_at"]),
        error=None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_result_commit_repository")
