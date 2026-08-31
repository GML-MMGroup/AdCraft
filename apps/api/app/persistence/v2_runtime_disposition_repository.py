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
    AgentCanvasGuidanceSessionRow,
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
            all_turn_rows = connection.execute(select(AgentCanvasChatTurnRow)).mappings().all()
            turn_rows = [
                row for row in all_turn_rows if str(row["status"]) in {"queued", "running"}
            ]
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
            session_rows = (
                connection.execute(select(AgentCanvasGuidanceSessionRow)).mappings().all()
            )
            active_execution_workflows = _active_workflow_ids(
                connection,
                AgentCanvasExecutionRow,
                ("queued", "running", "waiting"),
            )
            active_continuation_workflows = _active_workflow_ids(
                connection,
                AgentCanvasContinuationOutboxRow,
                ("queued", "leased", "retry_wait"),
            )
            active_agent_run_workflows = _active_workflow_ids(
                connection,
                AgentRunRow,
                ("queued", "running"),
            )
            active_provider_workflows = _active_workflow_ids(
                connection,
                AgentCanvasProviderTaskRow,
                ("submitted", "waiting", "recovering"),
            )
            active_lease_workflows = _active_workflow_ids(
                connection,
                AgentCanvasNodeLeaseRow,
                ("claimed",),
                field=AgentCanvasNodeLeaseRow.state,
            )

        turns_by_id = {str(row["turn_id"]): row for row in all_turn_rows}
        continuations_by_source: dict[str, list[Mapping[str, Any]]] = {}
        continuations_by_target: dict[str, list[Mapping[str, Any]]] = {}
        for row in continuation_rows:
            continuations_by_source.setdefault(str(row["source_turn_id"]), []).append(row)
            continuations_by_target.setdefault(str(row["continuation_turn_id"]), []).append(row)
        sessions_by_workflow = {str(row["workflow_id"]): row for row in session_rows}

        records = [
            _chat_turn_observation(
                row,
                continuations_by_source,
                continuations_by_target,
                turns_by_id,
                observed_at,
                processes,
            )
            for row in turn_rows
        ]
        records.extend(
            _guided_action_observation(
                row,
                turns_by_id,
                sessions_by_workflow,
                observed_at,
                processes,
            )
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
            _interaction_observation(
                row,
                awaiting_by_interaction,
                sessions_by_workflow,
                active_execution_workflows,
                active_continuation_workflows,
                active_agent_run_workflows,
                active_provider_workflows,
                active_lease_workflows,
                observed_at,
                processes,
            )
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
                "node_lease": _count_active(
                    connection,
                    AgentCanvasNodeLeaseRow,
                    ("claimed",),
                    field=AgentCanvasNodeLeaseRow.state,
                ),
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
            audit_only_count=sum(
                disposition.quiescence_impact == "audit_only"
                for disposition in inventory.dispositions
            ),
            blocked_liveness_count=sum(
                disposition.quiescence_impact == "blocking"
                for disposition in inventory.dispositions
            ),
        )


def _chat_turn_observation(
    row: Mapping[str, Any],
    continuations_by_source: Mapping[str, list[Mapping[str, Any]]],
    continuations_by_target: Mapping[str, list[Mapping[str, Any]]],
    turns_by_id: Mapping[str, Mapping[str, Any]],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    turn_id = str(row["turn_id"])
    outbound = continuations_by_source.get(turn_id, [])
    inbound = continuations_by_target.get(turn_id, [])
    continuation = outbound[0] if len(outbound) == 1 else None
    continuation_status = str(continuation["status"]) if continuation else None
    inbound_terminal = len(inbound) == 1 and str(inbound[0]["status"]) == "completed"
    downstream = (
        turns_by_id.get(str(continuation["continuation_turn_id"]))
        if continuation is not None
        else None
    )
    return RuntimeRecordObservationV1(
        record_class="chat_turn",
        record_id=turn_id,
        workflow_id=str(row["workflow_id"]),
        status=str(row["status"]),
        observed_at=observed_at,
        process_id=process_ids.get(("chat_turn", turn_id)),
        revision=(
            int(row["guidance_session_revision"])
            if row["guidance_session_revision"] is not None
            else None
        ),
        continuation_id=str(continuation["continuation_id"]) if continuation else None,
        continuation_status=continuation_status,
        has_reliable_terminal_evidence=bool(
            str(row["turn_kind"]) == "next_action"
            and inbound_terminal
            and continuation is not None
            and continuation_status == "completed"
            and downstream is not None
            and str(downstream["status"]) == "completed"
        ),
    )


def _guided_action_observation(
    row: Mapping[str, Any],
    turns_by_id: Mapping[str, Mapping[str, Any]],
    sessions_by_workflow: Mapping[str, Mapping[str, Any]],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    source_turn_id = row["apply_turn_id"] or row["creating_turn_id"]
    source_turn = turns_by_id.get(str(source_turn_id))
    session = sessions_by_workflow.get(str(row["workflow_id"]))
    return RuntimeRecordObservationV1(
        record_class="guided_action",
        record_id=str(row["action_id"]),
        workflow_id=str(row["workflow_id"]),
        status=str(row["state"]),
        observed_at=observed_at,
        process_id=process_ids.get(("guided_action", str(row["action_id"]))),
        session_id=str(session["session_id"]) if session else None,
        source_session_id=str(session["session_id"]) if session else None,
        revision=int(row["expected_session_revision"]),
        expected_revision=int(row["expected_session_revision"]),
        source_revision=int(session["revision"]) if session else None,
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
        generation_id=str(row["generation_id"]),
        revision=int(row["node_revision"]) if row["node_revision"] is not None else None,
        source_workflow_id=(str(source_turn["workflow_id"]) if source_turn else None),
        source_status=str(source_turn["status"]) if source_turn else None,
        has_source_proof=source_turn is not None
        and str(source_turn["status"]) in _TERMINAL_STATUSES,
    )


def _interaction_observation(
    row: Mapping[str, Any],
    awaiting_by_interaction: Mapping[str, Mapping[str, Any]],
    sessions_by_workflow: Mapping[str, Mapping[str, Any]],
    active_execution_workflows: set[str],
    active_continuation_workflows: set[str],
    active_agent_run_workflows: set[str],
    active_provider_workflows: set[str],
    active_lease_workflows: set[str],
    observed_at: str,
    process_ids: Mapping[_PROCESS_KEY, int],
) -> RuntimeRecordObservationV1:
    interaction_id = str(row["interaction_id"])
    workflow_id = str(row["workflow_id"])
    session = sessions_by_workflow.get(workflow_id)
    expected_revision = int(row["expected_session_revision"])
    source_revision = int(session["revision"]) if session else None
    awaiting = awaiting_by_interaction.get(interaction_id)
    identity_matches = bool(
        session is not None
        and str(session["workflow_id"]) == workflow_id
        and str(session["session_id"]) == str(row["session_id"])
        and awaiting is not None
        and str(awaiting["workflow_id"]) == workflow_id
        and str(awaiting["session_id"]) == str(row["session_id"])
    )
    return RuntimeRecordObservationV1(
        record_class="guided_interaction",
        record_id=interaction_id,
        workflow_id=workflow_id,
        session_id=str(row["session_id"]),
        status=str(row["status"]),
        observed_at=observed_at,
        process_id=process_ids.get(("guided_interaction", interaction_id)),
        revision=int(row["revision"]),
        expected_revision=expected_revision,
        source_revision=source_revision,
        source_workflow_id=str(session["workflow_id"]) if session else None,
        source_session_id=str(session["session_id"]) if session else None,
        has_active_continuation=workflow_id in active_continuation_workflows,
        has_active_execution_dependency=workflow_id in active_execution_workflows,
        has_active_agent_run=workflow_id in active_agent_run_workflows,
        has_active_provider_task=workflow_id in active_provider_workflows,
        has_active_lease=workflow_id in active_lease_workflows,
        has_current_awaiting=awaiting is not None,
        submit_revision_fail_closed=(
            identity_matches
            and source_revision is not None
            and expected_revision != source_revision
        ),
        audit_record_preserved=True,
        identity_matches=identity_matches,
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


def _active_workflow_ids(
    connection: Any,
    model: Any,
    statuses: tuple[str, ...],
    *,
    field: Any | None = None,
) -> set[str]:
    status_field = field or model.status
    return {
        str(workflow_id)
        for workflow_id in connection.execute(
            select(model.workflow_id).where(status_field.in_(statuses))
        ).scalars()
    }
