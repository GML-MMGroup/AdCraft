"""Read-only SQLite projection for V2 runtime disposition audits."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select

from app.persistence.database import V2Database
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasEditingExportRow,
    AgentCanvasExecutionMemberRow,
    AgentCanvasExecutionRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidedActionRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasNodeLeaseRow,
    AgentCanvasProviderTaskRow,
    AgentCanvasSkillRunRow,
    AgentRunRow,
    PresentationStreamRow,
)
from app.services.v2_stale_runtime_record_reconciliation import (
    RuntimeIdleAuditV1,
    RuntimeRecordClass,
    RuntimeRecordObservationV1,
    build_disposition_inventory,
)


_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "superseded"}
_PROCESS_KEY = tuple[RuntimeRecordClass, str]


class V2RuntimeDispositionRepository:
    """Read existing runtime tables without owning any mutation path."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def read_inventory(
        self,
        *,
        observed_at: str,
        process_ids: Mapping[_PROCESS_KEY, int] | None = None,
    ) -> tuple[RuntimeRecordObservationV1, ...]:
        """Read non-terminal-looking records and explicit source evidence."""

        processes = process_ids or {}
        with self._database.engine.connect() as connection:
            turn_rows = (
                connection.execute(
                    select(AgentCanvasChatTurnRow).where(
                        AgentCanvasChatTurnRow.status.in_(("queued", "running"))
                    )
                )
                .mappings()
                .all()
            )
            continuation_rows = (
                connection.execute(select(AgentCanvasContinuationOutboxRow)).mappings().all()
            )
            action_rows = (
                connection.execute(
                    select(AgentCanvasGuidedActionRow).where(
                        AgentCanvasGuidedActionRow.state == "applying"
                    )
                )
                .mappings()
                .all()
            )
            skill_rows = (
                connection.execute(
                    select(AgentCanvasSkillRunRow).where(AgentCanvasSkillRunRow.status == "active")
                )
                .mappings()
                .all()
            )
            stream_rows = (
                connection.execute(
                    select(PresentationStreamRow).where(PresentationStreamRow.status == "open")
                )
                .mappings()
                .all()
            )
            interaction_rows = (
                connection.execute(
                    select(AgentCanvasGuidedInteractionRow).where(
                        AgentCanvasGuidedInteractionRow.status == "open"
                    )
                )
                .mappings()
                .all()
            )
            awaiting_rows = (
                connection.execute(select(AgentCanvasGuidanceAwaitingRow)).mappings().all()
            )

        turns_by_id = {str(row["turn_id"]): row for row in turn_rows}
        continuations_by_source: dict[str, list[Mapping[str, Any]]] = {}
        for row in continuation_rows:
            continuations_by_source.setdefault(str(row["source_turn_id"]), []).append(row)

        records = [
            _chat_turn_observation(row, continuations_by_source, observed_at, processes)
            for row in turn_rows
        ]
        records.extend(
            _guided_action_observation(row, turns_by_id, observed_at, processes)
            for row in action_rows
        )
        records.extend(_skill_observation(row, observed_at, processes) for row in skill_rows)
        records.extend(
            _stream_observation(row, turns_by_id, observed_at, processes) for row in stream_rows
        )
        awaiting_by_interaction = {
            str(row["interaction_id"]): row
            for row in awaiting_rows
            if row["interaction_id"] is not None
        }
        records.extend(
            _interaction_observation(row, awaiting_by_interaction, observed_at, processes)
            for row in interaction_rows
        )
        return tuple(records)

    def read_idle_audit(
        self,
        *,
        observed_at: str,
        process_ids: Mapping[_PROCESS_KEY, int] | None = None,
    ) -> RuntimeIdleAuditV1:
        """Return queue counts separately from legal waits and durable selections."""

        records = self.read_inventory(observed_at=observed_at, process_ids=process_ids)
        inventory = build_disposition_inventory(records)
        with self._database.engine.connect() as connection:
            counts = {
                "execution": _count_active(
                    connection, AgentCanvasExecutionRow, ("queued", "running", "waiting")
                ),
                "member": _count_active(
                    connection,
                    AgentCanvasExecutionMemberRow,
                    ("queued", "waiting", "blocked", "running"),
                    field=AgentCanvasExecutionMemberRow.state,
                ),
                "continuation": _count_active(
                    connection,
                    AgentCanvasContinuationOutboxRow,
                    ("queued", "leased", "retry_wait"),
                ),
                "agent_run": _count_active(connection, AgentRunRow, ("queued", "running")),
                "provider": _count_active(
                    connection,
                    AgentCanvasProviderTaskRow,
                    ("submitted", "waiting", "recovering"),
                ),
                "editing": _count_active(
                    connection,
                    AgentCanvasEditingExportRow,
                    ("queued", "exporting"),
                ),
                "node_lease": connection.execute(
                    select(func.count()).select_from(AgentCanvasNodeLeaseRow)
                ).scalar_one(),
            }
        return RuntimeIdleAuditV1(
            execution_queue_count=counts["execution"],
            member_queue_count=counts["member"],
            continuation_queue_count=counts["continuation"],
            agent_run_queue_count=counts["agent_run"],
            provider_queue_count=counts["provider"],
            editing_export_queue_count=counts["editing"],
            node_lease_count=counts["node_lease"],
            legal_wait_count=inventory.classification_counts.get("legal_wait", 0),
            durable_selection_count=inventory.classification_counts.get("durable_selection", 0),
            blocked_liveness_count=inventory.classification_counts.get("unknown", 0),
        )


def _chat_turn_observation(
    row: Mapping[str, Any],
    continuations_by_source: Mapping[str, list[Mapping[str, Any]]],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    continuations = continuations_by_source.get(str(row["turn_id"]), [])
    continuation = continuations[0] if continuations else None
    continuation_status = str(continuation["status"]) if continuation else None
    return RuntimeRecordObservationV1(
        record_class="chat_turn",
        record_id=str(row["turn_id"]),
        workflow_id=str(row["workflow_id"]),
        status=str(row["status"]),
        observed_at=observed_at,
        process_id=process_ids.get(("chat_turn", str(row["turn_id"]))),
        continuation_id=str(continuation["continuation_id"]) if continuation else None,
        continuation_status=continuation_status,
        has_reliable_terminal_evidence=bool(
            continuation is not None
            and continuation_status in _TERMINAL_STATUSES
            and row["operation_failure_json"] is not None
        ),
    )


def _guided_action_observation(
    row: Mapping[str, Any],
    turns_by_id: Mapping[str, Mapping[str, Any]],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    source_turn_id = row["apply_turn_id"] or row["creating_turn_id"]
    source_turn = turns_by_id.get(str(source_turn_id))
    return RuntimeRecordObservationV1(
        record_class="guided_action",
        record_id=str(row["action_id"]),
        workflow_id=str(row["workflow_id"]),
        status=str(row["state"]),
        observed_at=observed_at,
        process_id=process_ids.get(("guided_action", str(row["action_id"]))),
        source_workflow_id=str(row["workflow_id"]),
        source_status=str(source_turn["status"]) if source_turn else None,
        has_source_proof=source_turn is not None
        and str(source_turn["status"]) in _TERMINAL_STATUSES,
    )


def _skill_observation(
    row: Mapping[str, Any],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    return RuntimeRecordObservationV1(
        record_class="skill_run",
        record_id=str(row["skill_run_id"]),
        workflow_id=str(row["workflow_id"]),
        status=str(row["status"]),
        observed_at=observed_at,
        process_id=process_ids.get(("skill_run", str(row["skill_run_id"]))),
    )


def _stream_observation(
    row: Mapping[str, Any],
    turns_by_id: Mapping[str, Mapping[str, Any]],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    source_turn = turns_by_id.get(str(row["turn_id"])) if row["turn_id"] else None
    return RuntimeRecordObservationV1(
        record_class="presentation_stream",
        record_id=str(row["stream_id"]),
        workflow_id=str(row["workflow_id"]),
        status=str(row["status"]),
        observed_at=observed_at,
        process_id=process_ids.get(("presentation_stream", str(row["stream_id"]))),
        has_source_proof=source_turn is not None
        and str(source_turn["status"]) in _TERMINAL_STATUSES,
    )


def _interaction_observation(
    row: Mapping[str, Any],
    awaiting_by_interaction: Mapping[str, Mapping[str, Any]],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    interaction_id = str(row["interaction_id"])
    return RuntimeRecordObservationV1(
        record_class="guided_interaction",
        record_id=interaction_id,
        workflow_id=str(row["workflow_id"]),
        session_id=str(row["session_id"]),
        status=str(row["status"]),
        observed_at=observed_at,
        process_id=process_ids.get(("guided_interaction", interaction_id)),
        has_current_awaiting=interaction_id in awaiting_by_interaction,
    )


def _count_active(
    connection: Any,
    model: Any,
    statuses: tuple[str, ...],
    *,
    field: Any | None = None,
) -> int:
    status_field = field or model.status
    return int(
        connection.execute(
            select(func.count()).select_from(model).where(status_field.in_(statuses))
        ).scalar_one()
    )
