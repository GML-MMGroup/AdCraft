"""Persist content-bound, advisory Treatment assessments without editing choices."""

from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import Settings
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    BrandDecisionLogEntryV1,
    BrandTreatmentDocumentV1,
    BrandTreatmentReviewOutputV1,
    BrandTreatmentReviewV1,
)
from app.services.brand_decision_document import BrandDecisionDocumentService
from app.services.brand_question_state import stale_context
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationSpec,
)


class BrandTreatmentReviewService:
    def __init__(
        self,
        database: V2Database,
        *,
        settings: Settings,
        generation_runtime: StructuredGenerationRuntime,
    ) -> None:
        self._database = database
        self._settings = settings
        self._runtime = generation_runtime
        self._documents = BrandDecisionDocumentService(database)
        self._repository = BrandDecisionRepository(database)

    def ensure_review(self, brand_id: str, *, response_locale: str) -> BrandTreatmentDocumentV1:
        with self._database.engine.connect() as connection:
            document = self._documents.read_in_transaction(connection, brand_id)
            if (
                not document.complete
                or document.review is not None
                or self._documents.frozen_in_transaction(connection, brand_id) is not None
            ):
                return document
        workflow_id = self._repository.workflow_id_for_brand(brand_id)
        output = self._runtime.run(
            StructuredGenerationSpec(
                stage_name="brand_treatment_review",
                contract_name="BrandTreatmentReviewOutputV1",
                model_id=self._settings.llm_creative_model,
                system_prompt="",
                input_payload={
                    "treatment_document": document.model_dump(mode="json"),
                    "response_locale": response_locale,
                },
                output_model=BrandTreatmentReviewOutputV1,
                trace_metadata={"workflow_id": workflow_id},
            )
        ).output
        validate_review_sources(document, output)
        review = BrandTreatmentReviewV1(
            **output.model_dump(),
            source_content_digest=document.content_digest,
        )
        with self._database.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            current = self._documents.read_in_transaction(connection, brand_id)
            if self._documents.frozen_in_transaction(connection, brand_id) is not None:
                raise stale_context()
            if (
                current.review is not None
                and current.review.source_content_digest == document.content_digest
            ):
                return current
            if current.content_digest != document.content_digest:
                raise stale_context()
            self._repository.append_decision_log_in_transaction(
                connection,
                BrandDecisionLogEntryV1(
                    log_id=f"blog_{uuid4().hex}",
                    stage="treatment",
                    action="recommend",
                    target_type="treatment_review",
                    target_id=document.content_digest,
                    detail={"review": review.model_dump(mode="json")},
                    created_at=datetime.now(timezone.utc),
                ),
                brand_id=brand_id,
            )
            return self._documents.read_in_transaction(connection, brand_id)


def validate_review_sources(
    document: BrandTreatmentDocumentV1, output: BrandTreatmentReviewOutputV1
) -> None:
    sections = {
        (step.step_key, section.key): section.text
        for step in document.treatment_steps
        if step.structured_detail is not None
        for section in step.structured_detail.sections
    }
    inventory = output.production_requirements
    references = (
        *inventory.character_sources,
        *inventory.prop_sources,
        *inventory.scene_sources,
        *(
            source
            for element in (*inventory.characters, *inventory.scenes)
            for source in element.sources
        ),
        *(source for finding in output.findings for source in finding.sources),
    )
    if any(
        not source.quote.strip()
        or source.quote not in sections.get((source.step_key, source.section_key), "")
        for source in references
    ):
        raise V2PersistenceError(
            "brand_review_invalid",
            "Treatment review references must quote confirmed sections exactly.",
        )
