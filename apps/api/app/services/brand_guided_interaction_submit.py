"""Submit brand guided interactions through the standard interaction endpoint."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_guided_interactions import (
    GuidedConceptSubmitV2,
    GuidedInteractionAcceptedV1,
    GuidedInteractionV1,
)
from app.services.brand_guided_interaction_bridge import (
    BrandGuidedInteractionBridge,
)
from app.services.brand_capability_invocation import (
    BrandCapabilityInvocationService,
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
        request: GuidedConceptSubmitV2,
        *,
        submission_id: str,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        """Apply the brand selection, close the card, and publish the next one."""

        content = interaction.content
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
            self._brand_service.apply_hypothesis_selection(brand_id, option_id)
        elif "adspec" in content.capability_id:
            self._brand_service.apply_adspec_selection(
                brand_id,
                card_id=action_id,
                option_id=option_id or "recommended",
            )
        elif "treatment" in content.capability_id:
            if request.action != "select" or custom_text:
                raise V2PersistenceError(
                    "guided_interaction_action_not_allowed",
                    "Select a Treatment candidate first. Use the Treatment step editor to submit complete revised details before final confirmation.",
                )
            selected_label = custom_text or self._option_label(content, option_id)
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
