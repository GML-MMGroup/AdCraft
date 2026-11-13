"""Author, durably publish and hand off the explicitly delegated complete screenplay."""

from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING

from app.persistence.agent_canvas_conversation_repository import AgentCanvasConversationRepository
from app.persistence.event_repository import EventRepository
from app.schemas.brand_professional_mode import BrandDecisionLogEntryV1, BrandTreatmentDocumentV1
from app.schemas.brand_screenplay import BrandScreenplayV1, BrandScreenplayGenerationV1
from app.services.brand_decision_document import BrandDecisionDocumentService
from app.services.brand_question_context import BrandQuestionContextService
from app.services.brand_question_state import BrandQuestionState
from app.services.brand_script_route import BrandScriptRouteService
from app.services.brand_skill_stack import BrandSkillStackService
from app.services.brand_treatment_confirmation import BrandTreatmentConfirmationService
from app.services.v2_structured_generation_runtime import StructuredGenerationSpec

if TYPE_CHECKING:
    from app.services.brand_capability_invocation import BrandCapabilityInvocationService


class BrandFullScriptService:
    def __init__(self, service: "BrandCapabilityInvocationService") -> None:
        self.service = service
        self.database = service._database
        self.repository = service._repository
        self.documents = BrandDecisionDocumentService(self.database)

    def complete(self, brand_id: str) -> bool:
        with self.database.engine.connect() as connection:
            journey = self.repository.get_journey_in_transaction(connection, brand_id)
            if (
                journey is None
                or journey.stage != "treatment"
                or not BrandScriptRouteService.full_script_selected(connection, brand_id)
            ):
                return False
            document = self.documents.read_in_transaction(connection, brand_id)
        if document.full_script is None:
            self._generate(brand_id, journey.stage_revision, document)
            document = self.documents.read(brand_id)
        # Choosing direct production is the user's advance authorization. The
        # immutable screenplay is reused after a handoff failure, never regenerated.
        BrandTreatmentConfirmationService(self.database).confirm(brand_id, document.content_digest)
        return True

    def _generate(self, brand_id: str, revision: int, document: BrandTreatmentDocumentV1) -> None:
        snapshot = BrandQuestionContextService(self.database).read(brand_id)
        spec = StructuredGenerationSpec(
            stage_name="brand_full_script",
            operation="brand_full_script",
            contract_name="BrandScreenplayV1",
            output_model=BrandScreenplayGenerationV1,
            model_id=self.service._settings.llm_creative_model,
            system_prompt="Author the complete delegated Brand screenplay using the current operation Skill.",
            input_payload={
                "product_context": snapshot.payload,
                "brand_decisions": document.model_dump(mode="json"),
                **BrandSkillStackService(self.database).treatment_context(brand_id, "story"),
                "response_locale": self.service._workflow_response_locale(brand_id),
            },
            trace_metadata={"workflow_id": snapshot.workflow_id},
        )
        result, stream = self.service._run_with_presentation(
            spec,
            brand_id=brand_id,
            stage="treatment",
            stage_revision=revision,
            substep_or_slot="full-script",
        )
        script = BrandScreenplayV1.model_validate(result.output.model_dump())
        digest = sha256(script.model_dump_json().encode()).hexdigest()
        with self.database.engine.begin() as connection:
            state = BrandQuestionState(self.database)
            state.claim(connection, brand_id, revision)
            state.require_snapshot(connection, brand_id, snapshot)
            self.repository.append_decision_log_in_transaction(
                connection,
                BrandDecisionLogEntryV1(
                    log_id=f"blog_script_{brand_id}_{digest}",
                    stage="treatment",
                    action="recommend",
                    target_type="brand_screenplay",
                    target_id=digest,
                    detail={"script": script.model_dump(mode="json")},
                    created_at=datetime.now(timezone.utc),
                ),
                brand_id=brand_id,
            )
            if snapshot.workflow_id:
                AgentCanvasConversationRepository(
                    self.database, EventRepository(self.database)
                ).publish_brand_screenplay_in_transaction(
                    connection,
                    workflow_id=snapshot.workflow_id,
                    content=script.render(),
                    digest=digest,
                )
        self.service._finish_presentation(stream, authoritative_id=digest, content=script.render())
