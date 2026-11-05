"""Durable admission and fenced completion of a selected Treatment summary."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, update

from app.persistence.models import BrandDecisionLogRow, BrandFormGenerationLeaseRow
from app.persistence.errors import V2PersistenceError
from app.schemas.brand_professional_mode import BrandOptionCardV1, TreatmentStepResultV1
from app.schemas.brand_treatment_generation import treatment_output_model
from app.services.brand_guided_interaction_bridge import BrandGuidedInteractionBridge
from app.services.brand_journey_state import advance_treatment_substep
from app.services.brand_question_state import BrandQuestionState, stale_context
from app.services.brand_skill_stack import BrandSkillStackService
from app.services.v2_structured_generation_runtime import StructuredGenerationSpec

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from app.services.brand_capability_invocation import BrandCapabilityInvocationService


class BrandTreatmentExpansionService:
    def __init__(self, service: BrandCapabilityInvocationService) -> None:
        self.service = service
        self.database = service._database
        self.repository = service._repository

    def _intent(
        self,
        connection: Connection,
        brand_id: str,
        *,
        card_id: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any] | None:
        query = select(BrandDecisionLogRow.detail_json).where(
            BrandDecisionLogRow.brand_id == brand_id,
            BrandDecisionLogRow.target_type == "treatment_expansion",
            BrandDecisionLogRow.action == "select",
        )
        if card_id is not None:
            query = query.where(
                func.json_extract(BrandDecisionLogRow.detail_json, "$.card_id") == card_id
            )
        if revision is not None:
            query = query.where(
                func.json_extract(BrandDecisionLogRow.detail_json, "$.stage_revision") == revision
            )
        raw = connection.execute(
            query.order_by(
                BrandDecisionLogRow.created_at.desc(), BrandDecisionLogRow.log_id.desc()
            ).limit(1)
        ).scalar_one_or_none()
        return json.loads(raw) if raw else None

    def reserve(self, brand_id: str, card_id: str, option_id: str) -> bool:
        """Commit selection without external work; historical detailed cards bypass expansion."""
        state = BrandQuestionState(self.database)
        observed = self.repository.get_journey(brand_id)
        if observed is None:
            raise stale_context()
        # Build bounded creative context outside the writer transaction. Publication checks
        # its source revision and context again under the writer fence.
        snapshot = state.context.read(brand_id)
        context = BrandSkillStackService(self.database).treatment_context(
            brand_id, observed.treatment_substep
        )
        with self.database.engine.begin() as connection:
            state.claim(connection, brand_id, observed.stage_revision)
            intent = self._intent(connection, brand_id, card_id=card_id)
            if intent is not None:
                if intent["selected"]["option_id"] != option_id:
                    raise stale_context()
                return True
            card = self.repository.get_open_card_in_transaction(connection, brand_id)
            if card is None or card.card_id != card_id or card.stage != "treatment":
                raise stale_context()
            if not state.card_is_current(connection, brand_id, card):
                raise stale_context()
            selected = next((item for item in card.options if item.option_id == option_id), None)
            if selected is None:
                raise V2PersistenceError(
                    "brand_option_card_invalid", "Selected option is not on the current card."
                )
            if selected.authoring_mode != "summary" or selected.detail is not None:
                return False
            state.require_snapshot(connection, brand_id, snapshot)
            journey = observed.model_copy(
                update={"stage_revision": observed.stage_revision + 1, "stage_status": "working"}
            )
            self.repository.resolve_card_in_transaction(connection, brand_id, card_id)
            self.repository.save_journey_in_transaction(connection, brand_id, journey)
            frozen = state.context.read_in_transaction(connection, brand_id)
            self.service._append_log(
                connection,
                brand_id=brand_id,
                stage="treatment",
                action="select",
                target_type="treatment_expansion",
                target_id=card.target_slot_id,
                detail={
                    "card_id": card.card_id,
                    "option_id": selected.option_id,
                    "card": card.model_dump(mode="json"),
                    "selected": selected.model_dump(mode="json"),
                    "stage_revision": journey.stage_revision,
                    "context_digest": frozen.digest,
                    "input_payload": {
                        "product_context": frozen.payload,
                        **context,
                        "substep": card.target_slot_id,
                        "authoring_mode": "detail",
                        "response_locale": self.service._workflow_response_locale(brand_id),
                        "selected_summary": selected.model_dump(mode="json"),
                    },
                },
                now=datetime.now(timezone.utc),
            )
            return True

    def complete(self, brand_id: str) -> bool:
        """Resume the current selected summary; commit details and advancement together."""
        journey = self.repository.get_journey(brand_id)
        if journey is None or journey.stage != "treatment" or journey.stage_status != "working":
            return False
        with self.database.engine.connect() as connection:
            intent = self._intent(connection, brand_id, revision=journey.stage_revision)
        if intent is None:
            return False
        state = BrandQuestionState(self.database)
        snapshot = state.context.read(brand_id)
        if snapshot.digest != intent["context_digest"]:
            raise stale_context()
        workflow_id = self.repository.workflow_id_for_brand(brand_id)
        bridge = BrandGuidedInteractionBridge(self.database)
        # The operation has a hard deadline of 480s. This non-renewing lease exceeds
        # that bound including persistence; completion also checks token AND expiry.
        claim = bridge.claim_card_generation(
            workflow_id or brand_id,
            "treatment",
            journey.stage_revision,
            generation_scope="selected-detail",
            lease_seconds=600,
        )
        if claim.role == "wait":
            completed = bridge.wait_for_card_generation(claim, timeout_seconds=600)
            if completed is not None:
                return True
            raise V2PersistenceError(
                "brand_treatment_expansion_retry_required",
                "Selected Treatment details could not finish. Retry to keep the selected summary.",
            )
        if claim.role == "ready":
            return True
        if claim.role != "owner":
            raise V2PersistenceError(
                "brand_form_generation_in_progress",
                "Selected Treatment details are being prepared.",
            )
        stream = None
        try:
            step_key = intent["input_payload"]["substep"]
            spec = StructuredGenerationSpec(
                stage_name="brand_treatment_step",
                contract_name="CreativeTreatmentDetailOutputV1",
                model_id=self.service._settings.llm_creative_model,
                system_prompt="Expand only selected_summary into the current step's complete sections. Preserve its decisions, all confirmed facts and previous steps. Do not offer alternatives or ask for confirmation.",
                input_payload=intent["input_payload"],
                output_model=treatment_output_model(step_key, option_count=1),
                trace_metadata={"workflow_id": workflow_id},
            )
            result, stream = self.service._run_with_presentation(
                spec,
                brand_id=brand_id,
                stage="treatment",
                stage_revision=journey.stage_revision,
                substep_or_slot=f"{step_key}-detail",
            )
            # Apply the narrowed validator even with injected/fake runtimes.
            output = spec.output_model.model_validate(result.output.model_dump(mode="json"))
            detail = output.step.options[0].detail
            selected = intent["selected"]
            with self.database.engine.begin() as connection:
                state.claim(connection, brand_id, journey.stage_revision)
                state.require_snapshot(connection, brand_id, snapshot)
                fenced = connection.execute(
                    update(BrandFormGenerationLeaseRow)
                    .where(
                        BrandFormGenerationLeaseRow.generation_key == claim.generation_key,
                        BrandFormGenerationLeaseRow.lease_token == claim.lease_token,
                        BrandFormGenerationLeaseRow.status == "generating",
                        BrandFormGenerationLeaseRow.lease_until > int(time.time()),
                    )
                    .values(
                        status="published",
                        form_json=BrandOptionCardV1.model_validate(
                            intent["card"]
                        ).model_dump_json(),
                        lease_until=0,
                    )
                )
                if fenced.rowcount != 1:
                    raise stale_context()
                now = datetime.now(timezone.utc)
                self.repository.save_treatment_step_in_transaction(
                    connection,
                    brand_id,
                    TreatmentStepResultV1(
                        step_key=step_key,
                        selected_label=selected["label"],
                        detail=detail.render(),
                        confirmed_at=now,
                    ),
                )
                self.service._append_log(
                    connection,
                    brand_id=brand_id,
                    stage="treatment",
                    action="select",
                    target_type="treatment_step",
                    target_id=step_key,
                    detail={
                        "card_id": intent["card"]["card_id"],
                        "option_id": selected["option_id"],
                        "selected_summary": selected["why"],
                        "content_version": 2,
                        "structured_detail": detail.model_dump(mode="json"),
                    },
                    now=now,
                )
                self.repository.save_journey_in_transaction(
                    connection, brand_id, advance_treatment_substep(journey)
                )
            self.service._finish_presentation(
                stream,
                authoritative_id=f"treatment-detail:{brand_id}:{journey.stage_revision}",
                content=detail.render(),
            )
            return True
        except Exception:
            bridge.release_card_generation(claim)
            if stream is not None:
                self.service._presentation_publisher.fail(
                    stream, "brand_treatment_expansion_failed"
                )
            raise
