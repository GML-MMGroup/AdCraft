"""Submit brand guided interactions through the standard interaction endpoint."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_interactions import (
    GuidedInteractionAcceptedV1,
    GuidedInteractionSubmitRequestV1,
    GuidedInteractionV1,
)
from app.schemas.brand_professional_mode import BrandFormSubmitV1, BrandFormV1
from app.services.brand_guided_interaction_bridge import (
    BrandGuidedInteractionBridge,
)
from app.services.brand_capability_invocation import (
    BrandCapabilityInvocationService,
    BrandFormSubmissionResult,
)

if TYPE_CHECKING:
    from app.persistence.database import V2Database


class BrandGuidedInteractionSubmitter:
    """Route concept-choice submissions to the brand capability service."""

    def __init__(
        self,
        database: "V2Database",
        brand_service: BrandCapabilityInvocationService,
        bridge: BrandGuidedInteractionBridge,
    ) -> None:
        self._database = database
        self._brand_service = brand_service
        self._bridge = bridge

    def submit_interaction(
        self,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        request: GuidedInteractionSubmitRequestV1,
        *,
        submission_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        """Apply the brand selection, close the card, and publish the next one."""

        content = interaction.content
        if isinstance(request, BrandFormSubmitV1) and isinstance(content, BrandFormV1):
            brand_id = self._resolve_brand_id(workflow_id)
            if request.form_id != content.form_id:
                raise V2PersistenceError(
                    "brand_form_invalid",
                    "The submitted Brand form is not current.",
                )
            result = self._brand_service.apply_form_submission(
                brand_id,
                form=content,
                answers=request.answers,
            )
            if result.requested_slot_ids:
                self._publish_more_options_form(
                    workflow_id,
                    brand_id,
                    content,
                    result,
                )
            else:
                self._bridge.close_current_interaction(workflow_id)
            revision = self._session_revision(workflow_id) or 1
            return GuidedInteractionAcceptedV1(
                workflow_id=workflow_id,
                interaction_id=interaction.interaction_id,
                submission_id=submission_id,
                receipt_id=f"receipt_{submission_id}",
                resulting_session_revision=revision,
                events_cursor=0,
            )
        if content.content_kind != "concept_choice":
            raise V2PersistenceError(
                "guided_interaction_action_not_allowed",
                "Brand interaction content is not a concept choice.",
            )
        brand_id = self._resolve_brand_id(workflow_id)
        option_id = request.option_id or ""
        custom_text = request.custom_text or ""
        action_id = content.action_id

        if "skill-stack" in content.capability_id:
            if custom_text or request.action not in {"select", "delegate"}:
                raise V2PersistenceError(
                    "brand_skill_selection_required",
                    "Use the Skill selector to submit explicit catalog ids and versions.",
                )
            self._brand_service.apply_skill_stack_selection(
                brand_id,
                card_id=action_id,
                option_id=option_id or "delegate",
            )
        elif "hypothesis" in content.capability_id:
            if request.action == "custom" and custom_text:
                replayed, keep_open = self._submit_card_custom_text(
                    workflow_id,
                    brand_id,
                    content.action_id,
                    "hypothesis",
                    custom_text,
                    submission_id,
                    content.stage_revision,
                )
                if replayed:
                    return self._accepted(workflow_id, interaction, submission_id)
                if keep_open:
                    revision = self._session_revision(workflow_id) or 1
                    return GuidedInteractionAcceptedV1(
                        workflow_id=workflow_id,
                        interaction_id=interaction.interaction_id,
                        submission_id=submission_id,
                        receipt_id=f"receipt_{submission_id}",
                        resulting_session_revision=revision,
                        events_cursor=0,
                    )
            elif request.action != "select" or custom_text:
                raise V2PersistenceError(
                    "guided_interaction_action_not_allowed",
                    "Choose a hypothesis option or provide a custom idea.",
                )
            else:
                self._brand_service.apply_hypothesis_selection(brand_id, option_id)
        elif "adspec" in content.capability_id:
            self._brand_service.apply_adspec_selection(
                brand_id,
                card_id=action_id,
                option_id=option_id or "recommended",
            )
        elif "treatment" in content.capability_id:
            if request.action == "custom" and custom_text:
                replayed, keep_open = self._submit_card_custom_text(
                    workflow_id,
                    brand_id,
                    content.action_id,
                    "treatment",
                    custom_text,
                    submission_id,
                    content.stage_revision,
                )
                if replayed:
                    return self._accepted(workflow_id, interaction, submission_id)
                if keep_open:
                    revision = self._session_revision(workflow_id) or 1
                    return GuidedInteractionAcceptedV1(
                        workflow_id=workflow_id,
                        interaction_id=interaction.interaction_id,
                        submission_id=submission_id,
                        receipt_id=f"receipt_{submission_id}",
                        resulting_session_revision=revision,
                        events_cursor=0,
                    )
            elif request.action != "select" or custom_text:
                raise V2PersistenceError(
                    "guided_interaction_action_not_allowed",
                    "Choose a Treatment option or provide a custom idea.",
                )
            else:
                selected_label = self._option_label(content, option_id)
                self._brand_service.apply_treatment_selection(
                    brand_id,
                    card_id=action_id,
                    option_id=option_id,
                    selected_label=selected_label,
                    detail="",
                )
        else:
            if request.action not in {"select", "custom", "delegate"}:
                raise V2PersistenceError(
                    "guided_interaction_action_not_allowed",
                    "Choose an option, provide a custom answer, or delegate this question.",
                )
            value_text = custom_text or self._option_label(content, option_id)
            self._brand_service.apply_slot_selection(
                brand_id,
                card_id=action_id,
                option_id=option_id if request.action == "select" else request.action,
                value_text=value_text,
                provenance="user_confirmed",
            )
        self._bridge.close_current_interaction(workflow_id)
        submission_identity = f"submission_{sha256(submission_id.encode()).hexdigest()[:32]}"
        revision = self._session_revision(workflow_id) or 1
        accepted = GuidedInteractionAcceptedV1(
            workflow_id=workflow_id,
            interaction_id=interaction.interaction_id,
            submission_id=submission_identity,
            receipt_id=f"receipt_{submission_identity}",
            resulting_session_revision=revision,
            events_cursor=0,
        )
        return accepted

    def _accepted(
        self,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        submission_id: str,
    ) -> GuidedInteractionAcceptedV1:
        revision = self._session_revision(workflow_id) or 1
        return GuidedInteractionAcceptedV1(
            workflow_id=workflow_id,
            interaction_id=interaction.interaction_id,
            submission_id=submission_id,
            receipt_id=f"receipt_{submission_id}",
            resulting_session_revision=revision,
            events_cursor=0,
        )

    def _submit_card_custom_text(
        self,
        workflow_id: str,
        brand_id: str,
        card_id: str,
        stage: str,
        custom_text: str,
        submission_id: str,
        stage_revision: int,
    ) -> tuple[bool, bool]:
        """Claim, generate, persist, and publish one card custom operation."""

        digest = sha256(custom_text.encode("utf-8")).hexdigest()
        claim = self._bridge.claim_card_generation(
            workflow_id,
            stage,  # type: ignore[arg-type]
            stage_revision,
            generation_scope=f"custom:{card_id}:{digest}:{submission_id}",
        )
        if claim.role == "ready":
            return True, False
        if claim.role == "wait":
            waited = self._bridge.wait_for_card_generation(claim)
            if waited is not None:
                return True, False
            claim = self._bridge.claim_card_generation(
                workflow_id,
                stage,  # type: ignore[arg-type]
                stage_revision,
                generation_scope=f"custom:{card_id}:{digest}:{submission_id}",
            )
            if claim.role == "ready":
                return True, False
            if claim.role != "owner":
                raise V2PersistenceError(
                    "brand_form_generation_in_progress",
                    "Brand card generation is still in progress.",
                )
        card = self._brand_service._repository.get_open_card(brand_id)
        if card is None or card.card_id != card_id or card.stage != stage:
            self._bridge.release_card_generation(claim)
            raise V2PersistenceError(
                "brand_stage_action_mismatch",
                "The submitted Brand card is not current.",
            )
        if card.stage_revision != stage_revision:
            self._bridge.release_card_generation(claim)
            raise V2PersistenceError(
                "brand_context_stale",
                "The Brand brief has changed. Refresh the current question.",
            )
        if len(card.options) >= 12:
            self._bridge.release_card_generation(claim)
            raise V2PersistenceError(
                "brand_option_card_invalid",
                "This Brand card already contains the maximum of twelve options.",
            )
        try:
            intent, direction = self._brand_service._card_custom_text_intent(
                brand_id, card, custom_text
            )
            if intent == "request_more_options":
                if len(card.options) + 3 > 12:
                    raise V2PersistenceError(
                        "brand_option_card_invalid",
                        "Adding three options would exceed the twelve-option card limit.",
                    )
                if stage == "hypothesis":
                    candidates = self._brand_service.generate_hypothesis_custom_candidates(
                        brand_id,
                        card,
                        custom_text=custom_text,
                        direction=direction,
                        count=3,
                    )
                    updated = self._brand_service.append_hypothesis_options(
                        brand_id, card_id=card_id, candidates=candidates
                    )
                else:
                    candidates = self._brand_service.generate_treatment_custom_candidates(
                        brand_id,
                        card,
                        custom_text=custom_text,
                        direction=direction,
                        count=3,
                    )
                    updated = self._brand_service.append_treatment_options(
                        brand_id, card_id=card_id, candidates=candidates
                    )
                self._bridge.publish_card_interaction(
                    workflow_id,
                    updated,
                    self._brand_service._workflow_response_locale(brand_id),
                )
                self._bridge.publish_card_generation(claim, updated)
                return False, True
            if stage == "hypothesis":
                candidate = self._brand_service.generate_hypothesis_custom_candidates(
                    brand_id,
                    card,
                    custom_text=custom_text,
                    direction=direction,
                    count=1,
                )[0]
                updated = self._brand_service.apply_hypothesis_custom_candidate(
                    brand_id, card_id=card_id, candidate=candidate
                )
            else:
                candidate = self._brand_service.generate_treatment_custom_candidates(
                    brand_id,
                    card,
                    custom_text=custom_text,
                    direction=direction,
                    count=1,
                )[0]
                updated = self._brand_service.apply_treatment_custom_candidate(
                    brand_id, card_id=card_id, candidate=candidate
                )
            self._bridge.publish_card_generation(claim, updated)
            self._bridge.close_current_interaction(workflow_id)
            return False, False
        except Exception:
            self._bridge.release_card_generation(claim)
            raise

    def _publish_more_options_form(
        self,
        workflow_id: str,
        brand_id: str,
        submitted_form: BrandFormV1,
        result: BrandFormSubmissionResult,
    ) -> BrandFormV1:
        """Generate and publish the comparison form for requested slots."""

        scope = (
            "more_"
            + sha256(
                f"{submitted_form.form_id}:{','.join(result.requested_slot_ids)}".encode()
            ).hexdigest()[:24]
        )
        claim = self._bridge.claim_form_generation(
            workflow_id,
            submitted_form.stage,
            submitted_form.revision,
            generation_scope=scope,
        )
        if claim.role == "ready":
            try:
                return BrandFormV1.model_validate_json(claim.form_json or "")
            except ValueError as error:
                raise V2PersistenceError(
                    "brand_form_generation_invalid",
                    "Published supplemental Brand form could not be read.",
                ) from error
        if claim.role == "wait":
            waited = self._bridge.wait_for_form_generation(
                workflow_id,
                submitted_form.stage,
                submitted_form.revision,
                generation_scope=scope,
            )
            if waited is not None:
                return waited
            claim = self._bridge.claim_form_generation(
                workflow_id,
                submitted_form.stage,
                submitted_form.revision,
                generation_scope=scope,
            )
            if claim.role == "ready":
                try:
                    return BrandFormV1.model_validate_json(claim.form_json or "")
                except ValueError as error:
                    raise V2PersistenceError(
                        "brand_form_generation_invalid",
                        "Published supplemental Brand form could not be read.",
                    ) from error
            if claim.role != "owner":
                raise V2PersistenceError(
                    "brand_form_generation_in_progress",
                    "Supplemental Brand form generation is still in progress.",
                )
        try:
            next_form = self._brand_service.run_slot_form(
                brand_id,
                submitted_form.stage,
                requested_slot_ids=result.requested_slot_ids,
                previous_options_by_slot=result.previous_options_by_slot,
                round_id=submitted_form.form_id,
            )
            self._bridge.publish_form_interaction(workflow_id, next_form)
            authoritative = (
                self._bridge.get_open_form(workflow_id, submitted_form.stage) or next_form
            )
            self._bridge.publish_form_generation(claim, authoritative)
            return authoritative
        except Exception:
            self._bridge.release_form_generation(claim)
            raise

    def _resolve_brand_id(self, workflow_id: str) -> str:
        from app.persistence.brand_decision_repository import BrandDecisionRepository

        repository = BrandDecisionRepository(self._database)
        project_id = repository.project_id_for_workflow(workflow_id)
        if project_id is None:
            raise V2PersistenceError(
                "brand_decisions_not_found",
                "Brand decisions not found for this workflow.",
            )
        brand_id = repository.get_brand_id_by_project(project_id)
        if brand_id is None:
            raise V2PersistenceError(
                "brand_decisions_not_found",
                "Brand identity not found for this workflow.",
            )
        return brand_id

    def _option_label(
        self,
        content,  # noqa: ANN001
        option_id: str,
    ) -> str:
        for option in content.options:
            if option.option_id == option_id:
                return option.title
        return ""

    def _session_revision(self, workflow_id: str) -> int | None:
        from sqlalchemy import select
        from app.persistence.models import AgentCanvasGuidanceSessionRow

        with self._database.engine.connect() as connection:
            row = connection.execute(
                select(AgentCanvasGuidanceSessionRow.revision).where(
                    AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
                )
            ).scalar_one_or_none()
            return int(row) if row is not None else None
