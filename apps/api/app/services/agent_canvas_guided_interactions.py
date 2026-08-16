"""Canonical service boundary for durable guided-interaction actions."""

from __future__ import annotations

from hashlib import sha256

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_guided_interaction_repository import (
    AgentCanvasGuidedInteractionRepository,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import (
    DelegateChoiceActionV2,
    SelectOptionActionV2,
)
from app.schemas.agent_canvas_creative_session import ProposedDraftReferenceV2
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingV1,
    GuidedConceptChoiceV1,
    GuidedConceptSubmitV1,
    GuidedInteractionAcceptedV1,
    GuidedInteractionSubmitRequestV1,
    GuidedInteractionV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
)
from app.services.agent_canvas_materialization_submission import (
    ProposalPublicationSubmissionService,
)


class GuidedInteractionService:
    """Read and submit one frozen guided interaction without duplicate writers."""

    def __init__(
        self,
        interactions: AgentCanvasGuidedInteractionRepository,
        conversations: AgentCanvasConversationRepository,
        materializations: AgentCanvasMaterializationRepository,
    ) -> None:
        self._interactions = interactions
        self._conversations = conversations
        self._materializations = materializations
        self._proposal_submissions = ProposalPublicationSubmissionService(
            conversations,
            materializations,
        )

    def open_interaction(
        self,
        interaction: GuidedInteractionV1,
        awaiting: GuidanceAwaitingV1,
    ) -> GuidedInteractionV1:
        return self._interactions.open_with_awaiting(interaction, awaiting)

    def get_interaction(self, workflow_id: str, interaction_id: str) -> GuidedInteractionV1:
        interaction = self._interactions.get(interaction_id)
        if interaction.workflow_id != workflow_id:
            raise _error(
                "guided_interaction_not_found",
                "Guided interaction was not found.",
            )
        return interaction

    def get_current(self, workflow_id: str) -> GuidedInteractionV1 | None:
        return self._interactions.get_current(workflow_id)

    def submit_interaction(
        self,
        workflow_id: str,
        interaction_id: str,
        request: GuidedInteractionSubmitRequestV1,
        *,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1:
        submission_id = "submission_" + _digest(f"{interaction_id}:{idempotency_key}")[:32]
        replay = self._interactions.get_submission_or_none(submission_id)
        if replay is not None:
            if (
                replay.workflow_id != workflow_id
                or replay.interaction_id != interaction_id
                or replay.idempotency_key != idempotency_key
                or replay.request != request
                or replay.result is None
            ):
                raise _error(
                    "guided_interaction_submission_conflict",
                    "Submission identity was reused with different content.",
                )
            return replay.result.model_copy(update={"replayed": True})
        interaction = self.get_interaction(workflow_id, interaction_id)
        self._validate_current(interaction, request)
        if isinstance(request, GuidedQuestionnaireSubmitV1) and isinstance(
            interaction.content, GuidedQuestionnaireV1
        ):
            return self._interactions.submit_questionnaire(
                interaction,
                request,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
            )
        if not isinstance(request, GuidedConceptSubmitV1) or not isinstance(
            interaction.content, GuidedConceptChoiceV1
        ):
            raise _error(
                "guided_interaction_action_not_allowed",
                "This guided interaction action is not available.",
            )
        proposal_id = interaction.content.proposal_id
        if proposal_id is None:
            raise _error(
                "guided_interaction_incomplete",
                "Concept interaction does not identify its Proposal.",
            )
        proposal = self._conversations.get_proposal(proposal_id)
        if request.action in {"defer", "exclude"}:
            proposal_action = "defer_topic" if request.action == "defer" else "exclude_element"
            descriptor = next(
                (item for item in proposal.actions if item.action == proposal_action),
                None,
            )
            if descriptor is None or request.action not in interaction.allowed_actions:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "This action is not available for the current guided interaction.",
                )
            return self._interactions.submit_concept_state_action(
                interaction,
                request,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
                action_id=descriptor.action_id,
                proposal_action=proposal_action,
            )
        action = self._proposal_action(interaction, request, proposal)
        accepted = self._proposal_submissions.submit_action(
            workflow_id,
            proposal_id,
            action,
            idempotency_key=idempotency_key,
            guided_submission={
                "submission_id": submission_id,
                "interaction_id": interaction_id,
                "idempotency_key": idempotency_key,
                "request": request.model_dump(mode="json", exclude_none=True),
            },
        )
        refreshed = self._conversations.get_proposal(proposal_id)
        materialization = refreshed.materialization
        if materialization is None:
            raise _error(
                "guided_interaction_incomplete",
                "Guided interaction did not queue Materialization.",
            )
        return GuidedInteractionAcceptedV1(
            workflow_id=workflow_id,
            interaction_id=interaction_id,
            submission_id=submission_id,
            receipt_id=f"receipt_{accepted.turn_id}",
            continuation_id=("continuation_" + _digest(materialization.materialization_id)[:32]),
            resulting_session_revision=request.expected_session_revision + 1,
            events_cursor=accepted.events_cursor,
            replayed=accepted.replayed,
        )

    def _validate_current(
        self,
        interaction: GuidedInteractionV1,
        request: GuidedInteractionSubmitRequestV1,
    ) -> None:
        session = self._conversations.get_guidance_session(interaction.workflow_id)
        if (
            interaction.status != "open"
            or request.expected_interaction_revision != interaction.revision
            or request.expected_session_revision != interaction.expected_session_revision
            or session.revision != interaction.expected_session_revision
        ):
            raise _error(
                "guided_interaction_stale",
                "Guided interaction or Guidance session revision is stale.",
            )

    @staticmethod
    def _proposal_action(interaction, request, proposal):
        action_name = request.action
        if action_name not in interaction.allowed_actions:
            raise _error(
                "guided_interaction_action_not_allowed",
                "This action is not allowed for the current guided interaction.",
            )
        if action_name == "select":
            if request.option_id is None or not any(
                option.option_id == request.option_id for option in interaction.content.options
            ):
                raise _error(
                    "guided_interaction_option_invalid",
                    "Selected guided option is not current.",
                )
            descriptor = next(
                (
                    candidate
                    for candidate in proposal.actions
                    if candidate.action == "select_option"
                ),
                None,
            )
            if descriptor is None:
                raise _error(
                    "guided_interaction_option_invalid",
                    "Selected guided option is not available.",
                )
            return SelectOptionActionV2(
                action_id=descriptor.action_id,
                action="select_option",
                option_id=request.option_id,
                expected_session_revision=request.expected_session_revision,
                accepted_references=tuple(
                    ProposedDraftReferenceV2.model_validate(reference.model_dump())
                    for reference in request.accepted_references
                ),
            )
        if action_name == "delegate":
            descriptor = next(
                (
                    candidate
                    for candidate in proposal.actions
                    if candidate.action == "delegate_choice"
                ),
                None,
            )
            if descriptor is not None:
                return DelegateChoiceActionV2(
                    action_id=descriptor.action_id,
                    action="delegate_choice",
                    expected_session_revision=request.expected_session_revision,
                )
        raise _error(
            "guided_interaction_action_not_allowed",
            "This action is not available for the current guided interaction.",
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_interaction_service")
