"""Persist content-bound, advisory Treatment assessments without editing choices."""

from datetime import datetime, timezone
import unicodedata
from uuid import uuid4

from app.core.config import Settings
from app.persistence.brand_decision_repository import BrandDecisionRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import (
    BrandDecisionLogEntryV1,
    BrandTreatmentDocumentV1,
    BrandTreatmentReviewOutputV1,
    BrandTreatmentSourceV1,
    BrandTreatmentReviewV1,
)
from app.services.brand_decision_document import BrandDecisionDocumentService
from app.services.brand_question_state import stale_context
from app.services.v2_structured_generation_runtime import (
    StructuredGenerationRuntime,
    StructuredGenerationSpec,
)
from app.services.v2_agent_structured_validation import normalize_confirmed_quote


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
                validation_profile="brand_treatment_review_sources_v1",
                validation_context={
                    "confirmed_sections": [
                        {
                            "step_key": step.step_key,
                            "section_key": section.key,
                            "text": section.text,
                        }
                        for step in document.treatment_steps
                        if step.structured_detail is not None
                        for section in step.structured_detail.sections
                    ]
                },
            )
        ).output
        validate_review_sources(document, output)
        output = canonicalize_review_sources(document, output)
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
    sections = _confirmed_sections(document)
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
        or normalize_confirmed_quote(source.quote)
        not in normalize_confirmed_quote(sections.get((source.step_key, source.section_key), ""))
        for source in references
    ):
        raise V2PersistenceError(
            "brand_review_invalid",
            "Treatment review references must quote confirmed sections exactly.",
        )


def canonical_confirmed_quote(section_text: str, quote: str) -> str | None:
    normalized_section, source_indexes = _normalize_with_indexes(section_text)
    normalized_quote = normalize_confirmed_quote(quote)
    if not normalized_quote:
        return None
    start = normalized_section.find(normalized_quote)
    if start < 0:
        return None
    end = start + len(normalized_quote)
    raw_start = source_indexes[start]
    raw_end = source_indexes[end - 1] + 1
    candidate = _trim_quote_edges(section_text[raw_start:raw_end])
    if normalize_confirmed_quote(candidate) != normalized_quote:
        return None
    return candidate or None


def canonicalize_review_sources(
    document: BrandTreatmentDocumentV1, output: BrandTreatmentReviewOutputV1
) -> BrandTreatmentReviewOutputV1:
    sections = _confirmed_sections(document)

    def canonical_source(source: BrandTreatmentSourceV1) -> BrandTreatmentSourceV1:
        canonical = canonical_confirmed_quote(
            sections.get((source.step_key, source.section_key), ""), source.quote
        )
        if canonical is None:
            raise V2PersistenceError(
                "brand_review_invalid",
                "Treatment review references must quote confirmed sections exactly.",
            )
        return source.model_copy(update={"quote": canonical})

    def canonical_sources(
        sources: tuple[BrandTreatmentSourceV1, ...],
    ) -> tuple[BrandTreatmentSourceV1, ...]:
        return tuple(canonical_source(source) for source in sources)

    inventory = output.production_requirements
    canonical_inventory = inventory.model_copy(
        update={
            "character_sources": canonical_sources(inventory.character_sources),
            "prop_sources": canonical_sources(inventory.prop_sources),
            "scene_sources": canonical_sources(inventory.scene_sources),
            "characters": tuple(
                element.model_copy(update={"sources": canonical_sources(element.sources)})
                for element in inventory.characters
            ),
            "scenes": tuple(
                element.model_copy(update={"sources": canonical_sources(element.sources)})
                for element in inventory.scenes
            ),
        }
    )
    return output.model_copy(
        update={
            "production_requirements": canonical_inventory,
            "findings": tuple(
                finding.model_copy(update={"sources": canonical_sources(finding.sources)})
                for finding in output.findings
            ),
        }
    )


def _confirmed_sections(document: BrandTreatmentDocumentV1) -> dict[tuple[str, str], str]:
    return {
        (step.step_key, section.key): section.text
        for step in document.treatment_steps
        if step.structured_detail is not None
        for section in step.structured_detail.sections
    }


def _normalize_with_indexes(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    source_indexes: list[int] = []
    whitespace_pending = False
    whitespace_index = 0
    for source_index, character in enumerate(value):
        for normalized_character in unicodedata.normalize("NFKC", character):
            if normalized_character.isspace():
                if not whitespace_pending:
                    whitespace_pending = True
                    whitespace_index = source_index
                continue
            if whitespace_pending:
                normalized.append(" ")
                source_indexes.append(whitespace_index)
                whitespace_pending = False
            normalized.append(normalized_character)
            source_indexes.append(source_index)
    return "".join(normalized), source_indexes


def _trim_quote_edges(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and (
        value[start].isspace() or unicodedata.category(value[start]).startswith("P")
    ):
        start += 1
    while end > start and (
        value[end - 1].isspace() or unicodedata.category(value[end - 1]).startswith("P")
    ):
        end -= 1
    return value[start:end]
