"""Dry-run-first correction for one proven orphaned historical Proposal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection

from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasBindingRow,
    AgentCanvasChatTurnRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasEditingExportRow,
    AgentCanvasExecutionRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidedInteractionRow,
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
from app.schemas.agent_canvas_orphaned_proposal_repair import (
    OrphanedGuidedProposalRepairAuditV1,
    OrphanedGuidedProposalRepairReceiptV1,
    OrphanedProposalProtectedDigestsV1,
    OrphanedProposalRepairQueueCountsV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.v2_storage_adapter import StorageAdapter


_WORKFLOW_ID = "adwf_v2_53f852d837b10a24"
_PROPOSAL_ID = "proposal_606e79e5713ed578665e2a39e894527b"
_TURN_ID = "turn_6f7f1877bcfc43a49bfafdc2763a14ec"
_ACTIVITY_ID = "activity_41d9f6bb5f8cdc29592ac781"
_CONTINUATION_ID = "continuation_9aa2f77841d9f6bb5f8cdc29"
_PARENT_TURN_ID = "turn_84d8e0913c179fa31de2d5f9433b9f6a"
_PARENT_CONTINUATION_ID = "continuation_d748a23912df26f5eff8b5fa"
_ENVELOPE_ID = "envelope_9aa2f77841d9f6bb5f8cdc29592ac781"
_SESSION_ID = "guidance_2a63bce845f34e2e909c1afbdd74c9b5"
_ACTIVE_ACTION_ID = f"journey-action:{_PARENT_TURN_ID}"


class OrphanedGuidedProposalRepairService:
    """Audit and correct only the explicitly allowlisted historical Proposal."""

    def __init__(self, database: V2Database, data_dir: Path) -> None:
        self._database = database
        self._requirements = AgentCanvasRequirementRepository(database)
        self._events = EventRepository(database)
        self._storage = StorageAdapter(data_dir)

    def audit(
        self,
        *,
        workflow_id: str,
        proposal_id: str,
    ) -> OrphanedGuidedProposalRepairAuditV1:
        self._require_target(workflow_id, proposal_id)
        with self._database.engine.connect() as connection:
            return self._audit_in_transaction(connection)

    def protected_digests(self, workflow_id: str) -> OrphanedProposalProtectedDigestsV1:
        if workflow_id != _WORKFLOW_ID:
            raise _not_proven("The requested Workflow is not allowlisted for correction.")
        with self._database.engine.connect() as connection:
            return self._protected_digests(connection)

    def apply(
        self,
        *,
        workflow_id: str,
        proposal_id: str,
        expected_audit_digest: str,
    ) -> OrphanedGuidedProposalRepairReceiptV1:
        self._require_target(workflow_id, proposal_id)
        if len(expected_audit_digest) != 64:
            raise _conflict("The expected audit digest is invalid.")
        transition_key = _transition_key(expected_audit_digest)
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
                plan = self._audit_in_transaction(connection)
                if plan.audit_digest != expected_audit_digest:
                    raise _conflict("Historical correction authority changed before apply.")
                applied_at = datetime.now(timezone.utc).isoformat()
                self._supersede_exact_lineage(connection, applied_at)
                if self._protected_digests(connection) != plan.protected_digests:
                    raise _conflict("Protected authoring or media state changed during correction.")
                receipt_payload = {
                    "correction_receipt_id": _receipt_id(expected_audit_digest),
                    "workflow_id": _WORKFLOW_ID,
                    "proposal_id": _PROPOSAL_ID,
                    "turn_id": _TURN_ID,
                    "activity_id": _ACTIVITY_ID,
                    "continuation_id": _CONTINUATION_ID,
                    "parent_turn_id": _PARENT_TURN_ID,
                    "parent_continuation_id": _PARENT_CONTINUATION_ID,
                    "cleared_action_id": _ACTIVE_ACTION_ID,
                    "evidence_digest": expected_audit_digest,
                    "transition_key": transition_key,
                    "replacement_status": "superseded",
                    "previous_session_revision": 8,
                    "replacement_session_revision": 9,
                    "protected_digests": plan.protected_digests.model_dump(mode="json"),
                    "applied_at": applied_at,
                    "replayed": False,
                }
                event = self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=_WORKFLOW_ID,
                        turn_id=_TURN_ID,
                        event_type="orphaned_guided_proposal_corrected",
                        transition_key=transition_key,
                        created_at=applied_at,
                        payload=receipt_payload,
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return OrphanedGuidedProposalRepairReceiptV1.model_validate(
            {**receipt_payload, "event_id": f"event:{event.seq}"}
        )

    def _audit_in_transaction(
        self,
        connection: Connection,
    ) -> OrphanedGuidedProposalRepairAuditV1:
        workflow = _one(
            connection,
            select(AgentCanvasWorkflowRow).where(
                AgentCanvasWorkflowRow.workflow_id == _WORKFLOW_ID
            ),
            "The allowlisted Workflow is missing.",
        )
        proposal = _one(
            connection,
            select(AgentCanvasConceptProposalRow).where(
                AgentCanvasConceptProposalRow.proposal_id == _PROPOSAL_ID,
                AgentCanvasConceptProposalRow.workflow_id == _WORKFLOW_ID,
            ),
            "The allowlisted Proposal is missing.",
        )
        turn = _one(
            connection,
            select(AgentCanvasChatTurnRow).where(
                AgentCanvasChatTurnRow.turn_id == _TURN_ID,
                AgentCanvasChatTurnRow.workflow_id == _WORKFLOW_ID,
            ),
            "The allowlisted Turn is missing.",
        )
        activity = _one(
            connection,
            select(AgentCanvasExpertActivityRow).where(
                AgentCanvasExpertActivityRow.activity_id == _ACTIVITY_ID,
                AgentCanvasExpertActivityRow.turn_id == _TURN_ID,
            ),
            "The allowlisted expert activity is missing.",
        )
        continuation = _one(
            connection,
            select(AgentCanvasContinuationOutboxRow).where(
                AgentCanvasContinuationOutboxRow.continuation_id == _CONTINUATION_ID,
                AgentCanvasContinuationOutboxRow.continuation_turn_id == _TURN_ID,
            ),
            "The allowlisted Continuation is missing.",
        )
        parent_turn = _one(
            connection,
            select(AgentCanvasChatTurnRow).where(
                AgentCanvasChatTurnRow.turn_id == _PARENT_TURN_ID,
                AgentCanvasChatTurnRow.workflow_id == _WORKFLOW_ID,
            ),
            "The allowlisted parent Turn is missing.",
        )
        parent_continuation = _one(
            connection,
            select(AgentCanvasContinuationOutboxRow).where(
                AgentCanvasContinuationOutboxRow.continuation_id == _PARENT_CONTINUATION_ID,
                AgentCanvasContinuationOutboxRow.continuation_turn_id == _PARENT_TURN_ID,
            ),
            "The allowlisted parent Continuation is missing.",
        )
        envelope = _one(
            connection,
            select(AgentCanvasOperationEnvelopeRow).where(
                AgentCanvasOperationEnvelopeRow.envelope_id == _ENVELOPE_ID,
                AgentCanvasOperationEnvelopeRow.turn_id == _TURN_ID,
            ),
            "The allowlisted capability envelope is missing.",
        )
        session = _one(
            connection,
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.session_id == _SESSION_ID,
                AgentCanvasGuidanceSessionRow.workflow_id == _WORKFLOW_ID,
            ),
            "The allowlisted Guidance Session is missing.",
        )
        options = (
            connection.execute(
                select(AgentCanvasConceptOptionRow)
                .where(AgentCanvasConceptOptionRow.proposal_id == _PROPOSAL_ID)
                .order_by(AgentCanvasConceptOptionRow.display_order)
            )
            .mappings()
            .all()
        )
        envelope_json = _json_object(envelope["envelope_json"])
        journey = _json_object(session["journey_state_json"])
        current_requirements = self._requirements.get_current_in_transaction(
            connection,
            _WORKFLOW_ID,
        )
        queue_counts = _active_queue_counts(connection)
        product_node_count = int(
            connection.execute(
                select(func.count())
                .select_from(AgentCanvasNodeRow)
                .where(
                    AgentCanvasNodeRow.workflow_id == _WORKFLOW_ID,
                    AgentCanvasNodeRow.creative_role == "product",
                )
            ).scalar_one()
        )
        open_interactions = int(
            connection.execute(
                select(func.count())
                .select_from(AgentCanvasGuidedInteractionRow)
                .where(
                    AgentCanvasGuidedInteractionRow.workflow_id == _WORKFLOW_ID,
                    AgentCanvasGuidedInteractionRow.status == "open",
                )
            ).scalar_one()
        )
        awaiting_count = int(
            connection.execute(
                select(func.count())
                .select_from(AgentCanvasGuidanceAwaitingRow)
                .where(AgentCanvasGuidanceAwaitingRow.workflow_id == _WORKFLOW_ID)
            ).scalar_one()
        )
        expected = {
            "proposal_turn_id": proposal["turn_id"],
            "proposal_kind": proposal["proposal_kind"],
            "proposal_capability": proposal["capability_id"],
            "proposal_availability": proposal["availability"],
            "proposal_schema": proposal["proposal_card_schema_version"],
            "proposal_materialization": proposal["materialization_id"],
            "turn_status": turn["status"],
            "turn_guidance_revision": turn["guidance_session_revision"],
            "activity_status": activity["status"],
            "activity_capability": activity["capability_id"],
            "activity_operation": activity["operation"],
            "continuation_status": continuation["status"],
            "continuation_operation": continuation["operation"],
            "continuation_source_turn": continuation["source_turn_id"],
            "parent_turn_status": parent_turn["status"],
            "parent_turn_kind": parent_turn["turn_kind"],
            "parent_turn_stage": parent_turn["operation_stage"],
            "parent_turn_guidance_revision": parent_turn["guidance_session_revision"],
            "parent_continuation_status": parent_continuation["status"],
            "parent_continuation_operation": parent_continuation["operation"],
            "session_status": session["status"],
            "session_revision": session["revision"],
            "session_topic": session["current_topic_id"],
            "session_active_proposal": session["active_proposal_id"],
            "journey_stage": journey.get("stage"),
            "journey_stage_status": journey.get("stage_status"),
            "journey_stage_revision": journey.get("stage_revision"),
            "journey_active_action": journey.get("active_action"),
            "candidate_count": envelope_json.get("candidate_count"),
            "envelope_capability": envelope_json.get("capability_id"),
            "envelope_operation": envelope_json.get("operation"),
            "proposal_requirement_revision": proposal["requirement_revision_id"],
            "proposal_requirement_digest": proposal["requirement_digest"],
            "envelope_requirement_revision": envelope_json.get("requirement_revision_id"),
            "envelope_requirement_digest": envelope_json.get("requirement_digest"),
            "current_requirement_revision": current_requirements.revision_id,
            "current_requirement_digest": current_requirements.digest,
            "option_count": len(options),
            "product_node_count": product_node_count,
            "open_interactions": open_interactions,
            "awaiting_count": awaiting_count,
        }
        required = {
            "proposal_turn_id": _TURN_ID,
            "proposal_kind": "product",
            "proposal_capability": "product_design",
            "proposal_availability": "open",
            "proposal_schema": 2,
            "proposal_materialization": None,
            "turn_status": "completed",
            "turn_guidance_revision": 8,
            "activity_status": "completed",
            "activity_capability": "product_design",
            "activity_operation": "propose_product_options",
            "continuation_status": "completed",
            "continuation_operation": "capability_command",
            "continuation_source_turn": _PARENT_TURN_ID,
            "parent_turn_status": "completed",
            "parent_turn_kind": "next_action",
            "parent_turn_stage": "completed",
            "parent_turn_guidance_revision": 6,
            "parent_continuation_status": "completed",
            "parent_continuation_operation": "next_action",
            "session_status": "active",
            "session_revision": 8,
            "session_topic": "topic_product_design",
            "session_active_proposal": None,
            "journey_stage": "product",
            "journey_stage_status": "ready",
            "journey_stage_revision": 4,
            "journey_active_action": {
                "action_id": _ACTIVE_ACTION_ID,
                "action_kind": "invoke_capability:product_design",
                "occurrence_id": None,
                "stage": "product",
                "stage_revision": 4,
                "status": "reserved",
                "turn_id": _PARENT_TURN_ID,
            },
            "candidate_count": 1,
            "envelope_capability": "product_design",
            "envelope_operation": None,
            "proposal_requirement_revision": current_requirements.revision_id,
            "proposal_requirement_digest": current_requirements.digest,
            "envelope_requirement_revision": current_requirements.revision_id,
            "envelope_requirement_digest": current_requirements.digest,
            "current_requirement_revision": current_requirements.revision_id,
            "current_requirement_digest": current_requirements.digest,
            "option_count": 1,
            "product_node_count": 0,
            "open_interactions": 0,
            "awaiting_count": 0,
        }
        if expected != required:
            raise _not_proven("The allowlisted Proposal lineage no longer matches its evidence.")
        if any(queue_counts.model_dump().values()):
            raise _not_proven("Nonterminal work prevents the historical correction.")
        protected = self._protected_digests(connection)
        audited_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "workflow_id": _WORKFLOW_ID,
            "proposal_id": _PROPOSAL_ID,
            "turn_id": _TURN_ID,
            "activity_id": _ACTIVITY_ID,
            "continuation_id": _CONTINUATION_ID,
            "parent_turn_id": _PARENT_TURN_ID,
            "parent_continuation_id": _PARENT_CONTINUATION_ID,
            "active_action_id": _ACTIVE_ACTION_ID,
            "envelope_id": _ENVELOPE_ID,
            "session_id": _SESSION_ID,
            "workflow_revision": int(workflow["revision"]),
            "session_revision": int(session["revision"]),
            "journey_stage": str(journey["stage"]),
            "journey_stage_revision": int(journey["stage_revision"]),
            "proposal_card_schema_version": int(proposal["proposal_card_schema_version"]),
            "option_count": len(options),
            "candidate_count": int(envelope_json["candidate_count"]),
            "product_node_count": product_node_count,
            "active_queue_counts": queue_counts.model_dump(mode="json"),
            "protected_digests": protected.model_dump(mode="json"),
        }
        return OrphanedGuidedProposalRepairAuditV1.model_validate(
            {**payload, "audited_at": audited_at, "audit_digest": _digest(payload)}
        )

    def _supersede_exact_lineage(self, connection: Connection, now: str) -> None:
        session = _one(
            connection,
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.session_id == _SESSION_ID,
                AgentCanvasGuidanceSessionRow.workflow_id == _WORKFLOW_ID,
            ),
            "The allowlisted Guidance Session is missing.",
        )
        journey = _json_object(session["journey_state_json"])
        journey["active_action"] = None
        updates = (
            connection.execute(
                update(AgentCanvasConceptProposalRow)
                .where(
                    AgentCanvasConceptProposalRow.proposal_id == _PROPOSAL_ID,
                    AgentCanvasConceptProposalRow.availability == "open",
                    AgentCanvasConceptProposalRow.proposal_card_schema_version == 2,
                    AgentCanvasConceptProposalRow.materialization_id.is_(None),
                )
                .values(availability="superseded", updated_at=now)
            ),
            connection.execute(
                update(AgentCanvasChatTurnRow)
                .where(
                    AgentCanvasChatTurnRow.turn_id == _TURN_ID,
                    AgentCanvasChatTurnRow.status == "completed",
                    AgentCanvasChatTurnRow.guidance_session_revision == 8,
                )
                .values(
                    status="superseded",
                    retryable=False,
                    operation_stage="superseded",
                    updated_at=now,
                )
            ),
            connection.execute(
                update(AgentCanvasExpertActivityRow)
                .where(
                    AgentCanvasExpertActivityRow.activity_id == _ACTIVITY_ID,
                    AgentCanvasExpertActivityRow.turn_id == _TURN_ID,
                    AgentCanvasExpertActivityRow.status == "completed",
                )
                .values(status="superseded", updated_at=now)
            ),
            connection.execute(
                update(AgentCanvasContinuationOutboxRow)
                .where(
                    AgentCanvasContinuationOutboxRow.continuation_id == _CONTINUATION_ID,
                    AgentCanvasContinuationOutboxRow.continuation_turn_id == _TURN_ID,
                    AgentCanvasContinuationOutboxRow.status == "completed",
                )
                .values(
                    status="superseded",
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code="continuation_superseded",
                    last_error_message="Orphaned guided Proposal was superseded.",
                    updated_at=now,
                )
            ),
            connection.execute(
                update(AgentCanvasGuidanceSessionRow)
                .where(
                    AgentCanvasGuidanceSessionRow.session_id == _SESSION_ID,
                    AgentCanvasGuidanceSessionRow.revision == 8,
                    AgentCanvasGuidanceSessionRow.journey_state_json
                    == session["journey_state_json"],
                )
                .values(
                    revision=9,
                    journey_state_json=json.dumps(journey, sort_keys=True),
                    updated_at=now,
                )
            ),
        )
        if any(result.rowcount != 1 for result in updates):
            raise _conflict("Historical Proposal lineage changed before correction.")

    def _protected_digests(
        self,
        connection: Connection,
    ) -> OrphanedProposalProtectedDigestsV1:
        workflow = _rows(
            connection,
            select(AgentCanvasWorkflowRow).where(
                AgentCanvasWorkflowRow.workflow_id == _WORKFLOW_ID
            ),
        )
        session = _rows(
            connection,
            select(AgentCanvasGuidanceSessionRow).where(
                AgentCanvasGuidanceSessionRow.workflow_id == _WORKFLOW_ID
            ),
        )
        for row in session:
            journey = _json_object(row["journey_state_json"])
            journey["active_action"] = None
            row["journey_state_json"] = journey
            row.pop("revision", None)
            row.pop("updated_at", None)
        current_requirements = self._requirements.get_current_in_transaction(
            connection,
            _WORKFLOW_ID,
        )
        nodes = _rows(
            connection,
            select(AgentCanvasNodeRow)
            .where(AgentCanvasNodeRow.workflow_id == _WORKFLOW_ID)
            .order_by(AgentCanvasNodeRow.node_id),
        )
        canvas_bindings = _rows(
            connection,
            select(AgentCanvasBindingRow)
            .where(AgentCanvasBindingRow.workflow_id == _WORKFLOW_ID)
            .order_by(AgentCanvasBindingRow.binding_id),
        )
        asset_bindings = _rows(
            connection,
            select(AssetBindingRow)
            .where(AssetBindingRow.workflow_id == _WORKFLOW_ID)
            .order_by(AssetBindingRow.binding_id),
        )
        options = _rows(
            connection,
            select(AgentCanvasConceptOptionRow)
            .where(AgentCanvasConceptOptionRow.proposal_id == _PROPOSAL_ID)
            .order_by(AgentCanvasConceptOptionRow.display_order),
        )
        asset_ids = {
            str(row["source_asset_id"]) for row in canvas_bindings if row.get("source_asset_id")
        }
        asset_ids.update(str(row["asset_id"]) for row in asset_bindings if row.get("asset_id"))
        asset_ids.update(str(row["output_asset_id"]) for row in nodes if row.get("output_asset_id"))
        assets: list[dict[str, Any]] = []
        versions: list[dict[str, Any]] = []
        media: list[dict[str, Any]] = []
        if asset_ids:
            assets = _rows(
                connection,
                select(AssetRow)
                .where(AssetRow.asset_id.in_(asset_ids))
                .order_by(AssetRow.asset_id),
            )
            versions = _rows(
                connection,
                select(AssetVersionRow)
                .where(AssetVersionRow.asset_id.in_(asset_ids))
                .order_by(AssetVersionRow.version_id),
            )
            for version in versions:
                path = self._storage.resolve_local_path(str(version["storage_key"]))
                if not path.is_file():
                    raise _not_proven("A protected AssetVersion media object is missing.")
                body = path.read_bytes()
                media.append(
                    {
                        "version_id": version["version_id"],
                        "size_bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
        return OrphanedProposalProtectedDigestsV1(
            workflow=_digest(workflow),
            session=_digest(session),
            requirements=_digest(current_requirements.model_dump(mode="json")),
            nodes=_digest(nodes),
            bindings=_digest({"canvas": canvas_bindings, "asset": asset_bindings}),
            proposal_options=_digest(options),
            assets=_digest({"assets": assets, "versions": versions}),
            media=_digest(media),
        )

    @staticmethod
    def _require_target(workflow_id: str, proposal_id: str) -> None:
        if workflow_id != _WORKFLOW_ID or proposal_id != _PROPOSAL_ID:
            raise _not_proven("The requested Proposal is not allowlisted for correction.")


def _active_queue_counts(connection: Connection) -> OrphanedProposalRepairQueueCountsV1:
    return OrphanedProposalRepairQueueCountsV1(
        executions=_count_nonterminal(
            connection,
            AgentCanvasExecutionRow,
            {"completed", "partial_completed", "failed", "cancelled"},
        ),
        continuations=_count_nonterminal(
            connection,
            AgentCanvasContinuationOutboxRow,
            {"completed", "failed", "superseded", "cancelled"},
        ),
        agent_runs=_count_nonterminal(
            connection,
            AgentRunRow,
            {"completed", "failed", "cancelled"},
        ),
        provider_tasks=_count_nonterminal(
            connection,
            AgentCanvasProviderTaskRow,
            {"succeeded", "failed", "cancelled"},
        ),
        editing_exports=_count_nonterminal(
            connection,
            AgentCanvasEditingExportRow,
            {"completed", "failed", "cancelled"},
        ),
    )


def _count_nonterminal(
    connection: Connection,
    model: Any,
    terminal: set[str],
) -> int:
    return int(
        connection.execute(
            select(func.count()).select_from(model).where(model.status.not_in(terminal))
        ).scalar_one()
    )


def _rows(connection: Connection, statement: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(statement).mappings().all()]


def _one(connection: Connection, statement: Any, message: str) -> dict[str, Any]:
    rows = _rows(connection, statement)
    if len(rows) != 1:
        raise _not_proven(message)
    return rows[0]


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError) as error:
        raise _not_proven("Required persisted JSON is invalid.") from error
    if not isinstance(value, dict):
        raise _not_proven("Required persisted JSON is not an object.")
    return value


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _receipt_id(audit_digest: str) -> str:
    identity = f"{_WORKFLOW_ID}:{_PROPOSAL_ID}:{audit_digest}"
    return f"correction_{hashlib.sha256(identity.encode()).hexdigest()[:32]}"


def _transition_key(audit_digest: str) -> str:
    return f"orphaned-guided-proposal-correction:{_receipt_id(audit_digest)}"


def _correction_event(connection: Connection, transition_key: str) -> dict[str, Any] | None:
    row = (
        connection.execute(
            select(WorkflowEventRow).where(
                WorkflowEventRow.workflow_id == _WORKFLOW_ID,
                WorkflowEventRow.event_type == "orphaned_guided_proposal_corrected",
                WorkflowEventRow.transition_key == transition_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _receipt_from_event(
    row: dict[str, Any],
    *,
    replayed: bool,
) -> OrphanedGuidedProposalRepairReceiptV1:
    payload = _json_object(row["payload_json"])
    payload.pop("_agent_canvas_event_envelope", None)
    if payload.get("workflow_id") != _WORKFLOW_ID or payload.get("proposal_id") != _PROPOSAL_ID:
        raise _conflict("Existing correction receipt does not match the exact target.")
    return OrphanedGuidedProposalRepairReceiptV1.model_validate(
        {**payload, "event_id": f"event:{int(row['seq'])}", "replayed": replayed}
    )


def _not_proven(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "orphaned_guided_proposal_repair_not_proven",
        message,
        stage="orphaned_guided_proposal_repair",
    )


def _conflict(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "orphaned_guided_proposal_repair_conflict",
        message,
        stage="orphaned_guided_proposal_repair",
    )
