"""Digest-bound Treatment confirmation and recoverable production handoff."""

from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import BrandOptionCardRow
from app.schemas.brand_professional_mode import BrandDecisionLogEntryV1, BrandJourneyStateV1
from app.services.brand_decision_document import BrandDecisionDocumentService
from app.services.brand_journey_state import advance_brand_stage
from app.services.brand_question_state import BrandQuestionState, stale_context


class BrandTreatmentConfirmationService:
    def __init__(self, database: V2Database) -> None:
        self._database = database
        self._repository = BrandDecisionRepository(database)
        self._documents = BrandDecisionDocumentService(database)

    def confirm(self, brand_id: str, content_digest: str | None) -> BrandJourneyStateV1:
        repository = self._repository
        with self._database.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            observed = repository.get_journey_in_transaction(connection, brand_id)
            if observed is None or observed.stage not in {"treatment", "production"}:
                raise V2PersistenceError(
                    "brand_stage_action_mismatch", "Treatment is not ready for confirmation."
                )
            frozen = self._documents.frozen_in_transaction(connection, brand_id)
            if observed.stage == "production" and frozen is None:
                raise V2PersistenceError(
                    "brand_stage_action_mismatch", "Legacy Treatment is already locked."
                )
            document = frozen or self._documents.read_in_transaction(connection, brand_id)
            if not document.complete:
                raise V2PersistenceError(
                    "brand_treatment_incomplete",
                    "Complete the missing Treatment decisions before confirming.",
                )
            if not content_digest:
                raise V2PersistenceError(
                    "brand_treatment_review_required",
                    "Review the final Treatment and submit its content_digest.",
                )
            if content_digest != document.content_digest:
                raise stale_context()
            if observed.stage == "production":
                return observed
            if frozen is None:
                repository.append_decision_log_in_transaction(
                    connection,
                    BrandDecisionLogEntryV1(
                        log_id=f"blog_{uuid4().hex}",
                        stage="treatment",
                        action="confirm",
                        target_type="treatment_document",
                        target_id=document.content_digest,
                        detail={"document": document.model_dump(mode="json")},
                        created_at=datetime.now(timezone.utc),
                    ),
                    brand_id=brand_id,
                )

        # The immutable snapshot is the durable recovery identity. Failure here
        # leaves the journey in Treatment; retry uses the same reviewed content.
        from app.services.brand_production_handoff import BrandProductionHandoffService

        workflow_id = repository.workflow_id_for_brand(brand_id)
        if workflow_id is not None:
            BrandProductionHandoffService(self._database).prepare_guided_production(
                workflow_id, brand_id
            )
        with self._database.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            journey = repository.get_journey_in_transaction(connection, brand_id)
            if journey.stage == "production":
                return journey
            BrandQuestionState(self._database).claim(connection, brand_id, observed.stage_revision)
            locked = advance_brand_stage(journey)
            repository.save_journey_in_transaction(connection, brand_id, locked)
            connection.execute(
                BrandOptionCardRow.__table__.update()
                .where(BrandOptionCardRow.brand_id == brand_id, BrandOptionCardRow.status == "open")
                .values(status="superseded")
            )
            repository.append_decision_log_in_transaction(
                connection,
                BrandDecisionLogEntryV1(
                    log_id=f"blog_{uuid4().hex}",
                    stage="treatment",
                    action="lock",
                    target_type="treatment",
                    target_id=document.content_digest,
                    detail={"stage": "production", "content_digest": document.content_digest},
                    created_at=datetime.now(timezone.utc),
                ),
                brand_id=brand_id,
            )
        return locked
