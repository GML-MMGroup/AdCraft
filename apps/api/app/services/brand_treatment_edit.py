"""Explicit revision-bound edits to confirmed, unlocked Treatment decisions."""

from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    BrandDecisionLogEntryV1,
    BrandTreatmentEditRequestV1,
    BrandTreatmentSubstep,
    TreatmentStepResultV1,
)
from app.services.brand_decision_document import BrandDecisionDocumentService
from app.services.brand_question_state import BrandQuestionState


def edit_treatment_step(
    database: V2Database,
    brand_id: str,
    step_key: BrandTreatmentSubstep,
    request: BrandTreatmentEditRequestV1,
) -> None:
    try:
        request.detail.validate_step(step_key)
    except ValueError as error:
        raise V2PersistenceError("brand_treatment_detail_invalid", str(error)) from error
    repository = BrandDecisionRepository(database)
    now = datetime.now(timezone.utc)
    with database.engine.begin() as connection:
        BrandQuestionState(database).claim(connection, brand_id, request.expected_stage_revision)
        journey = repository.get_journey_in_transaction(connection, brand_id)
        if (
            journey.stage != "treatment"
            or BrandDecisionDocumentService(database).frozen_in_transaction(connection, brand_id)
            is not None
        ):
            raise V2PersistenceError(
                "brand_stage_action_mismatch", "A reviewed or locked Treatment cannot be edited."
            )
        steps = repository.get_treatment_steps_in_transaction(connection, brand_id)
        if not any(step.step_key == step_key for step in steps):
            raise V2PersistenceError(
                "brand_treatment_detail_invalid", "Only a confirmed Treatment step can be edited."
            )
        repository.save_treatment_step_in_transaction(
            connection,
            brand_id,
            TreatmentStepResultV1(
                step_key=step_key,
                selected_label=request.selected_label,
                detail=request.detail.render(),
                structured_detail=request.detail,
                confirmed_at=now,
            ),
        )
        repository.append_decision_log_in_transaction(
            connection,
            BrandDecisionLogEntryV1(
                log_id=f"blog_{uuid4().hex}",
                stage="treatment",
                action="edit",
                target_type="treatment_step",
                target_id=step_key,
                detail={
                    "content_version": 2,
                    "structured_detail": request.detail.model_dump(mode="json"),
                },
                created_at=now,
            ),
            brand_id=brand_id,
        )
        repository.save_journey_in_transaction(
            connection,
            brand_id,
            journey.model_copy(update={"stage_revision": journey.stage_revision + 1}),
        )
