"""Dry-run-first correction for one proven stale guided capability result."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasAutomaticRunCommandRow,
    AgentCanvasBindingRow,
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasEditingExportRow,
    AgentCanvasExecutionRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedMediaResumeDeliveryRow,
    AgentCanvasNodeRow,
    AgentCanvasOperationEnvelopeRow,
    AgentCanvasProviderTaskRow,
    AgentCanvasWorkflowRow,
    AgentRunRow,
    AssetBindingRow,
    AssetRow,
    AssetVersionRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_capability_supersession_repair import (
    GuidedCapabilityRepairProtectedDigestsV1,
    GuidedCapabilityRepairQueueCountsV1,
    GuidedCapabilitySupersessionAuditV1,
    GuidedCapabilitySupersessionReceiptV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import FIXED_JOURNEY_STAGE_DESCRIPTORS
from app.services.agent_canvas_user_presentation import build_presentation_metadata
from app.services.v2_storage_adapter import StorageAdapter


@dataclass(frozen=True, slots=True)
class _HistoricalTarget:
    workflow_id: str
    turn_id: str
    activity_id: str
    continuation_id: str
    confirmation_id: str
    storyboard_node_id: str
    expected_session_revision: int
    minimum_current_session_revision: int


_TARGET = _HistoricalTarget(
    workflow_id="adwf_v2_758d5ac55c609dc3",
    turn_id="turn_dc1bb96625479e5b5611342feb002ae3",
    activity_id="activity_3e1afe96959272bf1b1d515c",
    continuation_id="continuation_f4f85a763e1afe96959272bf",
    confirmation_id="confirmation_29d38d88c25a190f1b47561558843d03",
    storyboard_node_id="node_2cc89f7ad2d96f86766b8eedf3781091",
    expected_session_revision=31,
    minimum_current_session_revision=35,
)


class GuidedCapabilitySupersessionRepairService:
    """Audit and correct only the explicitly approved historical lineage."""

    def __init__(
        self,
        database: V2Database,
        data_dir: Path,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._database = database
        self._storage = StorageAdapter(data_dir)
        self._events = EventRepository(database)
        self._fault_injector = fault_injector

    def audit(
        self,
        *,
        workflow_id: str,
        turn_id: str,
    ) -> GuidedCapabilitySupersessionAuditV1:
        self._require_exact_target(workflow_id, turn_id)
        with self._database.engine.connect() as connection:
            return self._audit_in_transaction(connection)

    def apply(
        self,
        *,
        workflow_id: str,
        turn_id: str,
        expected_audit_digest: str,
    ) -> GuidedCapabilitySupersessionReceiptV1:
        self._require_exact_target(workflow_id, turn_id)
        if len(expected_audit_digest) != 64:
            raise _conflict("The expected audit digest is invalid.")
        transition_key = _correction_transition_key(expected_audit_digest)
        with self._database.engine.connect() as connection:
            replay = _correction_event(connection, transition_key)
            if replay is not None:
                return _receipt_from_event(replay, replayed=True)
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                replay = _correction_event(connection, transition_key)
                if replay is not None:
                    connection.commit()
                    return _receipt_from_event(replay, replayed=True)
                try:
                    report = self._audit_in_transaction(connection)
                except V2PersistenceError as error:
                    if _target_is_already_superseded(connection):
                        raise _conflict(
                            "Historical correction identity or digest does not match."
                        ) from error
                    raise
                if report.audit_digest != expected_audit_digest:
                    raise _conflict("Historical correction authority changed before apply.")
                corrected_at = datetime.now(timezone.utc).isoformat()
                receipt_id = _correction_receipt_id(expected_audit_digest)
                self._update_terminal_projections(connection, corrected_at)
                receipt_payload = {
                    "correction_receipt_id": receipt_id,
                    "workflow_id": workflow_id,
                    "turn_id": turn_id,
                    "activity_id": report.activity_id,
                    "continuation_id": report.continuation_id,
                    "previous_status": report.turn_status,
                    "previous_error_code": report.previous_error_code,
                    "replacement_status": "superseded",
                    "evidence_digest": expected_audit_digest,
                    "transition_key": transition_key,
                    "corrected_at": corrected_at,
                    "replayed": False,
                }
                correction_event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=workflow_id,
                        conversation_id=report.conversation_id,
                        turn_id=turn_id,
                        event_type="guided_capability_supersession_corrected",
                        transition_key=transition_key,
                        created_at=corrected_at,
                        payload=receipt_payload,
                    ),
                )
                self._inject_fault("correction_event")
                self._append_superseded_timeline(
                    connection,
                    report=report,
                    corrected_at=corrected_at,
                    evidence_digest=expected_audit_digest,
                )
                self._inject_fault("timeline")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return GuidedCapabilitySupersessionReceiptV1.model_validate(
            {**receipt_payload, "event_id": f"event:{correction_event.seq}"}
        )

    def _update_terminal_projections(self, connection: Connection, now: str) -> None:
        turn_result = connection.execute(
            update(AgentCanvasChatTurnRow)
            .where(
                AgentCanvasChatTurnRow.turn_id == _TARGET.turn_id,
                AgentCanvasChatTurnRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasChatTurnRow.status == "failed",
                AgentCanvasChatTurnRow.error_code == "guidance_revision_conflict",
            )
            .values(
                status="superseded",
                retryable=False,
                operation_stage="superseded",
                operation_failure_json=None,
                error_code=None,
                error_message=None,
                updated_at=now,
            )
        )
        if turn_result.rowcount != 1:
            raise _conflict("Historical Turn changed before correction.")
        self._inject_fault("turn")
        activity_result = connection.execute(
            update(AgentCanvasExpertActivityRow)
            .where(
                AgentCanvasExpertActivityRow.activity_id == _TARGET.activity_id,
                AgentCanvasExpertActivityRow.turn_id == _TARGET.turn_id,
                AgentCanvasExpertActivityRow.status == "failed",
                AgentCanvasExpertActivityRow.error_code == "guidance_revision_conflict",
            )
            .values(
                status="superseded",
                error_code=None,
                error_message=None,
                updated_at=now,
            )
        )
        if activity_result.rowcount != 1:
            raise _conflict("Historical activity changed before correction.")
        self._inject_fault("activity")
        continuation_result = connection.execute(
            update(AgentCanvasContinuationOutboxRow)
            .where(
                AgentCanvasContinuationOutboxRow.continuation_id == _TARGET.continuation_id,
                AgentCanvasContinuationOutboxRow.continuation_turn_id == _TARGET.turn_id,
                AgentCanvasContinuationOutboxRow.status == "failed",
                AgentCanvasContinuationOutboxRow.last_error_code == "guidance_revision_conflict",
            )
            .values(
                status="superseded",
                lease_owner=None,
                lease_expires_at=None,
                last_error_code="continuation_superseded",
                last_error_message="Guided capability work was superseded.",
                updated_at=now,
            )
        )
        if continuation_result.rowcount != 1:
            raise _conflict("Historical Continuation changed before correction.")
        self._inject_fault("continuation")

    def _append_superseded_timeline(
        self,
        connection: Connection,
        *,
        report: GuidedCapabilitySupersessionAuditV1,
        corrected_at: str,
        evidence_digest: str,
    ) -> None:
        event_payload = {
            "activity_id": report.activity_id,
            "workflow_id": report.workflow_id,
            "turn_id": report.turn_id,
            "capability_id": report.capability_id,
            "operation": report.operation,
            "capability_display_name": "Storyboard Artist",
            "status": "superseded",
            "error_code": None,
            "conversation_id": report.conversation_id,
            "evidence_digest": evidence_digest,
            "created_at": corrected_at,
        }
        self._events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=report.workflow_id,
                conversation_id=report.conversation_id,
                turn_id=report.turn_id,
                event_type="expert_activity_superseded",
                transition_key=(f"conversation:{report.turn_id}:expert_activity_superseded"),
                created_at=corrected_at,
                payload=event_payload,
            ),
        )
        sequence_no = (
            int(
                connection.execute(
                    select(func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)).where(
                        AgentCanvasChatEntryRow.conversation_id == report.conversation_id
                    )
                ).scalar_one()
            )
            + 1
        )
        connection.execute(
            insert(AgentCanvasChatEntryRow).values(
                entry_id=(
                    f"entry_guided_capability_supersession_"
                    f"{_correction_receipt_id(evidence_digest)}"
                ),
                conversation_id=report.conversation_id,
                workflow_id=report.workflow_id,
                sequence_no=sequence_no,
                entry_type="expert_activity",
                speaker=None,
                content="Storyboard Artist",
                metadata_json=json.dumps(
                    build_presentation_metadata(
                        message_key="expert_activity.superseded",
                        message_args={"capability_display_name": "Storyboard Artist"},
                        response_locale="und",
                        presentation_key=f"activity:{report.activity_id}",
                        base=event_payload,
                    ),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                created_at=corrected_at,
            )
        )

    def _inject_fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    def _audit_in_transaction(
        self,
        connection: Connection,
    ) -> GuidedCapabilitySupersessionAuditV1:
        turn = _one(
            connection,
            select(AgentCanvasChatTurnRow).where(
                AgentCanvasChatTurnRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasChatTurnRow.turn_id == _TARGET.turn_id,
            ),
            "Guided capability Turn was not found.",
        )
        activity = _one(
            connection,
            select(AgentCanvasExpertActivityRow).where(
                AgentCanvasExpertActivityRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasExpertActivityRow.turn_id == _TARGET.turn_id,
                AgentCanvasExpertActivityRow.activity_id == _TARGET.activity_id,
            ),
            "Guided capability activity was not found.",
        )
        continuation = _one(
            connection,
            select(AgentCanvasContinuationOutboxRow).where(
                AgentCanvasContinuationOutboxRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasContinuationOutboxRow.continuation_turn_id == _TARGET.turn_id,
                AgentCanvasContinuationOutboxRow.continuation_id == _TARGET.continuation_id,
            ),
            "Guided capability Continuation was not found.",
        )
        envelope_row = _one(
            connection,
            select(AgentCanvasOperationEnvelopeRow).where(
                AgentCanvasOperationEnvelopeRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasOperationEnvelopeRow.turn_id == _TARGET.turn_id,
            ),
            "Guided capability envelope was not found.",
        )
        envelope = _json_object(envelope_row["envelope_json"])
        session = _one(
            connection,
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == _TARGET.workflow_id
            ),
            "Guidance Session was not found.",
        )
        journey = _json_object(session["journey_state_json"])
        delivery = _one(
            connection,
            select(AgentCanvasGuidedMediaResumeDeliveryRow).where(
                AgentCanvasGuidedMediaResumeDeliveryRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasGuidedMediaResumeDeliveryRow.confirmation_id == _TARGET.confirmation_id,
            ),
            "Accepted media resume delivery was not found.",
        )
        node = _one(
            connection,
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.workflow_id == _TARGET.workflow_id,
                AgentCanvasNodeRow.node_id == _TARGET.storyboard_node_id,
            ),
            "Ready Storyboard node was not found.",
        )
        asset_id = str(node["output_asset_id"] or "")
        asset = _one(
            connection,
            select(AssetRow).where(AssetRow.asset_id == asset_id),
            "Ready Storyboard Asset was not found.",
        )
        version = _one(
            connection,
            select(AssetVersionRow)
            .where(
                AssetVersionRow.asset_id == asset_id,
                AssetVersionRow.source_workflow_id == _TARGET.workflow_id,
                AssetVersionRow.source_node_id == _TARGET.storyboard_node_id,
            )
            .order_by(AssetVersionRow.version_no.desc())
            .limit(1),
            "Ready Storyboard Asset version was not found.",
        )
        self._require_proof(turn, activity, continuation, envelope, session, journey, delivery)
        if (
            str(node["status"]) != "ready"
            or str(node["creative_role"]) != "storyboard_sequence"
            or str(asset["status"]) != "active"
            or str(version["status"]) != "ready"
            or not self._storage.content_exists(str(version["storage_key"]), str(version["sha256"]))
        ):
            raise _not_proven("Ready Storyboard media proof is incomplete.")
        queue_counts = _active_queue_counts(connection, _TARGET.workflow_id)
        if any(queue_counts.model_dump().values()):
            raise _not_proven("The Workflow still owns nonterminal runtime work.")
        protected = _protected_digests(connection, _TARGET.workflow_id)
        audited_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "workflow_id": _TARGET.workflow_id,
            "turn_id": _TARGET.turn_id,
            "conversation_id": str(turn["conversation_id"]),
            "activity_id": _TARGET.activity_id,
            "continuation_id": _TARGET.continuation_id,
            "envelope_id": str(envelope_row["envelope_id"]),
            "capability_id": str(activity["capability_id"]),
            "operation": str(activity["operation"]),
            "turn_status": str(turn["status"]),
            "activity_status": str(activity["status"]),
            "continuation_status": str(continuation["status"]),
            "previous_error_code": "guidance_revision_conflict",
            "expected_session_revision": int(envelope["expected_session_revision"]),
            "current_session_revision": int(session["revision"]),
            "current_journey_stage": str(journey["stage"]),
            "current_journey_stage_revision": int(journey["stage_revision"]),
            "resume_delivery_id": str(delivery["delivery_id"]),
            "resume_confirmation_id": str(delivery["confirmation_id"]),
            "resume_delivery_status": str(delivery["status"]),
            "storyboard_node_id": _TARGET.storyboard_node_id,
            "storyboard_node_status": str(node["status"]),
            "storyboard_asset_id": asset_id,
            "storyboard_version_id": str(version["version_id"]),
            "storyboard_asset_sha256": str(version["sha256"]),
            "storyboard_asset_size_bytes": int(version["size_bytes"]),
            "active_queue_counts": queue_counts,
            "protected_digests": protected,
            "audited_at": audited_at,
        }
        return GuidedCapabilitySupersessionAuditV1.model_validate(
            {**payload, "audit_digest": _digest(payload, excluded={"audited_at"})}
        )

    @staticmethod
    def _require_exact_target(workflow_id: str, turn_id: str) -> None:
        if (workflow_id, turn_id) != (_TARGET.workflow_id, _TARGET.turn_id):
            raise _not_proven("The requested historical correction is not approved.")

    @staticmethod
    def _require_proof(
        turn: Any,
        activity: Any,
        continuation: Any,
        envelope: dict[str, object],
        session: Any,
        journey: dict[str, object],
        delivery: Any,
    ) -> None:
        stage_order = tuple(FIXED_JOURNEY_STAGE_DESCRIPTORS)
        stage = str(journey.get("stage") or "")
        if stage not in stage_order or stage_order.index(stage) <= stage_order.index(
            "storyboard_grids"
        ):
            raise _not_proven("The current Journey is not beyond Storyboard Grids.")
        facts = (
            str(turn["status"]) == "failed",
            str(turn["error_code"]) == "guidance_revision_conflict",
            str(activity["status"]) == "failed",
            str(activity["error_code"]) == "guidance_revision_conflict",
            str(activity["capability_id"]) == "storyboard_design",
            str(activity["operation"]) == "propose_storyboard_options",
            str(continuation["status"]) == "failed",
            str(continuation["last_error_code"]) == "guidance_revision_conflict",
            envelope.get("capability_id") == "storyboard_design",
            int(envelope.get("expected_session_revision") or 0)
            == _TARGET.expected_session_revision,
            int(session["revision"]) >= _TARGET.minimum_current_session_revision,
            str(delivery["status"]) == "completed",
        )
        if not all(facts):
            raise _not_proven("Historical guided capability supersession is not proven.")


def _active_queue_counts(
    connection: Connection,
    workflow_id: str,
) -> GuidedCapabilityRepairQueueCountsV1:
    return GuidedCapabilityRepairQueueCountsV1(
        executions=_count_statuses(
            connection,
            AgentCanvasExecutionRow,
            workflow_id,
            "status",
            ("queued", "running", "waiting"),
        ),
        continuations=_count_statuses(
            connection,
            AgentCanvasContinuationOutboxRow,
            workflow_id,
            "status",
            ("queued", "leased", "retry_wait"),
        ),
        agent_runs=_count_statuses(
            connection, AgentRunRow, workflow_id, "status", ("queued", "running")
        ),
        provider_tasks=_count_statuses(
            connection,
            AgentCanvasProviderTaskRow,
            workflow_id,
            "status",
            ("submitted", "waiting", "recovering"),
        ),
        guided_media_resumes=_count_statuses(
            connection,
            AgentCanvasGuidedMediaResumeDeliveryRow,
            workflow_id,
            "status",
            ("queued", "running"),
        ),
        automatic_runs=_count_statuses(
            connection,
            AgentCanvasAutomaticRunCommandRow,
            workflow_id,
            "state",
            ("pending", "claimed"),
        ),
        editing_exports=_count_statuses(
            connection,
            AgentCanvasEditingExportRow,
            workflow_id,
            "status",
            ("queued", "exporting"),
        ),
    )


def _count_statuses(
    connection: Connection,
    model: Any,
    workflow_id: str,
    field_name: str,
    statuses: tuple[str, ...],
) -> int:
    field = getattr(model, field_name)
    return int(
        connection.execute(
            select(func.count())
            .select_from(model)
            .where(
                model.workflow_id == workflow_id,
                field.in_(statuses),
            )
        ).scalar_one()
    )


def _protected_digests(
    connection: Connection,
    workflow_id: str,
) -> GuidedCapabilityRepairProtectedDigestsV1:
    workflow = _rows_digest(
        connection,
        select(AgentCanvasWorkflowRow).where(AgentCanvasWorkflowRow.workflow_id == workflow_id),
    )
    nodes = _rows_digest(
        connection,
        select(AgentCanvasNodeRow)
        .where(AgentCanvasNodeRow.workflow_id == workflow_id)
        .order_by(AgentCanvasNodeRow.node_id),
    )
    bindings = _digest(
        {
            "canvas": _rows_digest(
                connection,
                select(AgentCanvasBindingRow)
                .where(AgentCanvasBindingRow.workflow_id == workflow_id)
                .order_by(AgentCanvasBindingRow.binding_id),
            ),
            "assets": _rows_digest(
                connection,
                select(AssetBindingRow)
                .where(AssetBindingRow.workflow_id == workflow_id)
                .order_by(AssetBindingRow.binding_id),
            ),
        }
    )
    assets = _digest(
        {
            "assets": _rows_digest(
                connection,
                select(AssetRow)
                .join(AssetVersionRow, AssetVersionRow.asset_id == AssetRow.asset_id)
                .where(AssetVersionRow.source_workflow_id == workflow_id)
                .order_by(AssetRow.asset_id),
            ),
            "versions": _rows_digest(
                connection,
                select(AssetVersionRow)
                .where(AssetVersionRow.source_workflow_id == workflow_id)
                .order_by(AssetVersionRow.version_id),
            ),
        }
    )
    session_row = _one(
        connection,
        select(AgentCanvasGuidanceSessionRow).where(
            AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
        ),
        "Guidance Session was not found.",
    )
    return GuidedCapabilityRepairProtectedDigestsV1(
        workflow=workflow,
        nodes=nodes,
        bindings=bindings,
        assets=assets,
        session=_digest(
            {
                "session_id": session_row["session_id"],
                "revision": session_row["revision"],
                "status": session_row["status"],
            }
        ),
        journey=_digest(_json_object(session_row["journey_state_json"])),
    )


def _rows_digest(connection: Connection, statement: Any) -> str:
    rows = [dict(row) for row in connection.execute(statement).mappings().all()]
    return _digest(rows)


def _digest(value: object, *, excluded: set[str] | None = None) -> str:
    if isinstance(value, dict) and excluded:
        value = {key: item for key, item in value.items() if key not in excluded}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError) as error:
        raise _not_proven("Required persisted JSON is invalid.") from error
    if not isinstance(parsed, dict):
        raise _not_proven("Required persisted JSON is not an object.")
    return parsed


def _one(connection: Connection, statement: Any, message: str):
    rows = connection.execute(statement).mappings().all()
    if len(rows) != 1:
        raise _not_proven(message)
    return rows[0]


def _not_proven(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guided_capability_supersession_not_proven",
        message,
        stage="guided_capability_supersession_repair",
    )


def _conflict(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "guided_capability_supersession_conflict",
        message,
        stage="guided_capability_supersession_repair",
    )


def _correction_receipt_id(audit_digest: str) -> str:
    identity = f"{_TARGET.workflow_id}:{_TARGET.turn_id}:{audit_digest}"
    return f"correction_{hashlib.sha256(identity.encode()).hexdigest()[:32]}"


def _correction_transition_key(audit_digest: str) -> str:
    return f"guided-capability-supersession-correction:{_correction_receipt_id(audit_digest)}"


def _correction_event(connection: Connection, transition_key: str):
    return (
        connection.execute(
            select(WorkflowEventRow).where(
                WorkflowEventRow.workflow_id == _TARGET.workflow_id,
                WorkflowEventRow.event_type == "guided_capability_supersession_corrected",
                WorkflowEventRow.transition_key == transition_key,
            )
        )
        .mappings()
        .one_or_none()
    )


def _receipt_from_event(row: Any, *, replayed: bool) -> GuidedCapabilitySupersessionReceiptV1:
    payload = _json_object(row["payload_json"])
    payload.pop("_agent_canvas_event_envelope", None)
    expected = {
        "workflow_id": _TARGET.workflow_id,
        "turn_id": _TARGET.turn_id,
        "activity_id": _TARGET.activity_id,
        "continuation_id": _TARGET.continuation_id,
        "replacement_status": "superseded",
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise _conflict("Existing correction receipt does not match the exact target.")
    return GuidedCapabilitySupersessionReceiptV1.model_validate(
        {
            **payload,
            "event_id": f"event:{int(row['seq'])}",
            "replayed": replayed,
        }
    )


def _target_is_already_superseded(connection: Connection) -> bool:
    statuses = connection.execute(
        select(
            AgentCanvasChatTurnRow.status,
            AgentCanvasExpertActivityRow.status,
            AgentCanvasContinuationOutboxRow.status,
        )
        .join(
            AgentCanvasExpertActivityRow,
            AgentCanvasExpertActivityRow.turn_id == AgentCanvasChatTurnRow.turn_id,
        )
        .join(
            AgentCanvasContinuationOutboxRow,
            AgentCanvasContinuationOutboxRow.continuation_turn_id == AgentCanvasChatTurnRow.turn_id,
        )
        .where(AgentCanvasChatTurnRow.turn_id == _TARGET.turn_id)
    ).one_or_none()
    return statuses is not None and tuple(statuses) == (
        "superseded",
        "superseded",
        "superseded",
    )
