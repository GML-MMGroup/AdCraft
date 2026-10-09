"""Atomic admission of a frozen Brand Treatment into the existing journey."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasNodeRow,
    AgentCanvasWorkflowRow,
    BrandRow,
    ProjectRow,
)
from app.schemas.agent_canvas_creative_session import CreativeElementDecisionV2, CreativeGoalV2
from app.schemas.agent_canvas_production_journey import GuidedProductionJourneyV2, JourneyEvidenceV2
from app.schemas.brand_professional_mode import BrandTreatmentDocumentV1
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_production_journey import (
    GuidedProductionJourneyPolicyService,
    initial_production_journey,
)


class BrandProductionAdmissionRepository:
    """Do not reset work that already crossed the Brand-to-production boundary."""

    def __init__(self, database: V2Database) -> None:
        self._database = database

    def admit_in_transaction(
        self,
        connection: Connection,
        workflow_id: str,
        brand_id: str,
        document: BrandTreatmentDocumentV1,
    ) -> bool:
        from app.services.brand_decision_document import BrandDecisionDocumentService

        mode = connection.execute(
            select(ProjectRow.mode)
            .join(
                AgentCanvasWorkflowRow, AgentCanvasWorkflowRow.project_id == ProjectRow.project_id
            )
            .join(BrandRow, BrandRow.project_id == ProjectRow.project_id)
            .where(
                AgentCanvasWorkflowRow.workflow_id == workflow_id,
                BrandRow.brand_id == brand_id,
            )
        ).scalar_one_or_none()
        if mode != "brand":
            raise _conflict()
        frozen = BrandDecisionDocumentService(self._database).frozen_in_transaction(
            connection, brand_id
        )
        if frozen is None or frozen.content_digest != document.content_digest:
            raise _conflict()
        row = (
            connection.execute(
                select(AgentCanvasGuidanceSessionRow).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            )
            .mappings()
            .one_or_none()
        )
        # Historical planning-only fixtures have no generic guided session.
        if row is None:
            return False
        current = GuidedProductionJourneyV2.model_validate_json(row["journey_state_json"])
        if current.stage != "intake":
            return False
        if row["status"] != "active" or current.active_action or current.suspended_action:
            raise _conflict()
        guards = (
            select(AgentCanvasNodeRow.node_id).where(AgentCanvasNodeRow.workflow_id == workflow_id),
            select(AgentCanvasChatTurnRow.turn_id).where(
                AgentCanvasChatTurnRow.workflow_id == workflow_id,
                AgentCanvasChatTurnRow.status.in_(("queued", "running")),
            ),
            select(AgentCanvasContinuationOutboxRow.continuation_id).where(
                AgentCanvasContinuationOutboxRow.workflow_id == workflow_id,
                AgentCanvasContinuationOutboxRow.status.in_(("queued", "leased", "retry_wait")),
            ),
        )
        if any(connection.execute(query.limit(1)).first() is not None for query in guards):
            raise _conflict()
        elements = tuple(
            CreativeElementDecisionV2.model_validate(item)
            for item in json.loads(row["element_decisions_json"])
        )
        journey = current.model_copy(
            update={"decisions": initial_production_journey(elements).decisions}
        )
        now = datetime.now(timezone.utc)
        identity = f"brand-context:{document.content_digest}"
        policy = GuidedProductionJourneyPolicyService()
        for kind in ("creative_goal_validated", "world_view_excluded"):
            journey = policy.apply_evidence(
                journey,
                JourneyEvidenceV2(
                    evidence_id=f"{identity}:{kind}",
                    evidence_kind=kind,
                    source_id=identity,
                    stage=journey.stage,
                    stage_revision=journey.stage_revision,
                    actor="system",
                ),
                recorded_at=now,
            )
        goal = CreativeGoalV2.model_validate_json(row["creative_goal_json"])
        facts = {value.slot_id: value.value for value in document.brand_profile.values}
        goal = goal.model_copy(
            update={
                "summary": f"Create the reviewed advertisement for {facts.get('brand_product_identity', 'the confirmed product')}. Preserve Treatment {document.content_digest}."
            }
        )
        revision = int(row["revision"]) + 1
        connection.execute(
            update(AgentCanvasGuidanceSessionRow)
            .where(AgentCanvasGuidanceSessionRow.session_id == row["session_id"])
            .values(
                journey_state_json=journey.model_dump_json(),
                creative_goal_json=goal.model_dump_json(),
                revision=revision,
                updated_at=now.isoformat(),
            )
        )
        EventRepository(self._database).append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=workflow_id,
                event_type="journey_stage_changed",
                transition_key=f"brand-admission:{workflow_id}:{document.content_digest}",
                created_at=now.isoformat(),
                payload={
                    "session_id": row["session_id"],
                    "session_revision": revision,
                    "previous_stage": "intake",
                    "next_stage": "product",
                    "stage": "product",
                    "stage_revision": journey.stage_revision,
                    "action_owner": "system",
                    "source_content_digest": document.content_digest,
                    "evidence_kind": "world_view_excluded",
                },
            ),
        )
        return True


def _conflict() -> V2PersistenceError:
    return V2PersistenceError(
        "brand_handoff_conflict",
        "Brand production cannot restart intake while its reviewed authority or active work conflicts.",
        stage="brand_production_admission",
    )
