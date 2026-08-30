"""Canonical service boundary for durable guided-interaction actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256

from pydantic import TypeAdapter, ValidationError

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
    ChatTurnAcceptedV2,
    CustomDirectionActionV2,
    DeferTopicActionV2,
    DelegateChoiceActionV2,
    ExcludeElementActionV2,
    ProposalActionRequestV2,
    ReuseDirectionActionV2,
    SelectOptionActionV2,
)
from app.schemas.agent_canvas_creative_session import ProposedDraftReferenceV2
from app.schemas.agent_canvas_guided_interactions import (
    GuidanceAwaitingV2,
    GuidedConceptChoiceV2,
    GuidedConceptSubmitV2,
    GuidedInteractionAcceptedV1,
    GuidedInteractionSubmitRequestV1,
    GuidedInteractionV1,
    GuidedProductSourceQuestionV1,
    GuidedProductSourceSubmitV1,
    GuidedMediaReviewSubmitV1,
    GuidedMediaReviewV1,
    GuidedQuestionnaireSubmitV1,
    GuidedQuestionnaireV1,
)
from app.schemas.agent_canvas_materialization import ProposalPublicationEnvelopeV1
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
        *,
        media_submit: Callable[..., GuidedInteractionAcceptedV1] | None = None,
        product_submit: Callable[..., GuidedInteractionAcceptedV1] | None = None,
        reference_snapshot: Callable[[str, ProposedDraftReferenceV2], tuple[int | None, str | None]]
        | None = None,
    ) -> None:
        self._interactions = interactions
        self._conversations = conversations
        self._materializations = materializations
        self._media_submit = media_submit
        self._product_submit = product_submit
        self._proposal_submissions = ProposalPublicationSubmissionService(
            conversations,
            materializations,
            reference_snapshot=reference_snapshot,
        )

    def open_interaction(
        self,
        interaction: GuidedInteractionV1,
        awaiting: GuidanceAwaitingV2,
    ) -> GuidedInteractionV1:
        return self._interactions.open_with_awaiting(interaction, awaiting)

    def set_product_submitter(
        self,
        submitter: Callable[..., GuidedInteractionAcceptedV1],
    ) -> None:
        """Attach the existing Product source authority after runtime wiring."""

        self._product_submit = submitter

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

    def replay_proposal_action(
        self,
        workflow_id: str,
        proposal_id: str,
        action: ProposalActionRequestV2,
        *,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1 | None:
        submission = self._interactions.get_submission_by_idempotency_key(
            workflow_id,
            idempotency_key,
        )
        if submission is None:
            return None
        interaction = self.get_interaction(workflow_id, submission.interaction_id)
        if (
            not isinstance(interaction.content, GuidedConceptChoiceV2)
            or interaction.content.proposal_id != proposal_id
            or not isinstance(submission.request, GuidedConceptSubmitV2)
            or submission.result is None
        ):
            raise _error(
                "idempotency_conflict",
                "Idempotency key was reused with different content.",
            )
        proposal = self._conversations.get_private_proposal(proposal_id)
        if (
            proposal.workflow_id != workflow_id
            or proposal.guidance_session_revision != submission.request.expected_session_revision
            or not self._proposal_action_matches_submission(
                proposal_id,
                action,
                submission.request,
            )
        ):
            raise _error(
                "idempotency_conflict",
                "Idempotency key was reused with different content.",
            )
        return submission.result.model_copy(update={"replayed": True})

    def replay_closed_storyboard_action(
        self,
        workflow_id: str,
        proposal_id: str,
        action: ProposalActionRequestV2,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2 | None:
        """Replay a terminal Storyboard selection from immutable lineage facts.

        Proposal action descriptors and Journey revisions are mutable
        projections.  Once the canonical materialization closes, the persisted
        operation Turn and publication envelope are the only authority for a
        changed-key replay.
        """

        loaded = self._load_persisted_storyboard_action(workflow_id, proposal_id)
        if loaded is None:
            return None
        envelope, canonical_action = loaded
        if not _storyboard_actions_equivalent(action, canonical_action, envelope):
            # Let the normal Proposal authority handle an intentional
            # supersession (for example, a historical reuse action).  A
            # malformed persisted lineage still raises from the loader.
            return None
        return self._queue_persisted_storyboard_action(
            envelope,
            canonical_action,
            idempotency_key=idempotency_key,
        )

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
            if isinstance(request, GuidedMediaReviewSubmitV1) and request.action == "accept":
                self._interactions.ensure_media_resume_delivery(replay.submission_id)
            return replay.result.model_copy(update={"replayed": True})
        interaction = self.get_interaction(workflow_id, interaction_id)
        try:
            self._validate_current(interaction, request)
        except V2PersistenceError as error:
            if error.code != "guided_interaction_stale":
                raise
            replay = self._replay_closed_storyboard_selection(
                workflow_id,
                interaction,
                request,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return replay
            raise
        if isinstance(request, GuidedMediaReviewSubmitV1) and isinstance(
            interaction.content,
            GuidedMediaReviewV1,
        ):
            if self._media_submit is None:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "Media review actions are unavailable.",
                )
            return self._media_submit(
                interaction,
                request,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
            )
        if isinstance(request, GuidedQuestionnaireSubmitV1) and isinstance(
            interaction.content, GuidedQuestionnaireV1
        ):
            return self._interactions.submit_questionnaire(
                interaction,
                request,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
                continuation_writer=self._conversations.insert_continuation_in_transaction,
            )
        if isinstance(request, GuidedProductSourceSubmitV1) and isinstance(
            interaction.content,
            GuidedProductSourceQuestionV1,
        ):
            if self._product_submit is None:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "Product source actions are unavailable.",
                )
            return self._product_submit(
                workflow_id,
                interaction,
                request,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
            )
        if not isinstance(request, GuidedConceptSubmitV2) or not isinstance(
            interaction.content, GuidedConceptChoiceV2
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
        proposal = self._conversations.get_private_proposal(proposal_id)
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
        refreshed = self._conversations.get_private_proposal(proposal_id)
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

    def _replay_closed_storyboard_selection(
        self,
        workflow_id: str,
        interaction: GuidedInteractionV1,
        request: GuidedInteractionSubmitRequestV1,
        *,
        idempotency_key: str,
    ) -> GuidedInteractionAcceptedV1 | None:
        """Replay an already claimed Storyboard selection after its wait closes.

        A changed client key is an alias of the server-owned selection identity,
        not a new guided action.  Only an existing canonical Storyboard claim is
        eligible for this stale-interaction bypass; a new or different option
        still receives the normal stale interaction error.
        """

        if not isinstance(request, GuidedConceptSubmitV2) or not isinstance(
            interaction.content, GuidedConceptChoiceV2
        ):
            return None
        proposal_id = interaction.content.proposal_id
        if proposal_id is None:
            return None
        try:
            loaded = self._load_persisted_storyboard_action(workflow_id, proposal_id)
            if loaded is None:
                return None
            envelope, canonical_action = loaded
            action = self._guided_replay_action(request, canonical_action)
            if action is None or not _storyboard_actions_equivalent(
                action,
                canonical_action,
                envelope,
            ):
                return None
            accepted = self._queue_persisted_storyboard_action(
                envelope,
                canonical_action,
                idempotency_key=idempotency_key,
            )
            canonical_result = self._load_persisted_guided_result(
                envelope.action_turn_id,
                interaction.interaction_id,
            )
            if canonical_result is not None:
                return canonical_result.model_copy(
                    update={
                        "continuation_id": canonical_result.continuation_id
                        or "continuation_" + _digest(envelope.materialization_id)[:32],
                        "replayed": True,
                    }
                )
            materialization = self._conversations.get_private_proposal(proposal_id).materialization
            if materialization is None:
                return None
            session = self._conversations.get_guidance_session(workflow_id)
            return GuidedInteractionAcceptedV1(
                workflow_id=workflow_id,
                interaction_id=interaction.interaction_id,
                submission_id="submission_"
                + _digest(f"{interaction.interaction_id}:{idempotency_key}")[:32],
                receipt_id=f"receipt_{accepted.turn_id}",
                continuation_id="continuation_" + _digest(materialization.materialization_id)[:32],
                resulting_session_revision=max(
                    request.expected_session_revision + 1,
                    session.revision,
                ),
                events_cursor=accepted.events_cursor,
                replayed=True,
            )
        except V2PersistenceError as error:
            if error.code in {
                "proposal_action_stale",
                "guided_interaction_action_not_allowed",
                "guided_interaction_option_invalid",
                "proposal_option_not_found",
            }:
                return None
            raise

    def _load_persisted_guided_result(
        self,
        action_turn_id: str,
        interaction_id: str,
    ) -> GuidedInteractionAcceptedV1 | None:
        """Return the immutable guided result stored with the canonical Turn."""

        turn = self._conversations.get_turn(action_turn_id)
        request = turn.request
        if not isinstance(request, Mapping):
            raise _error(
                "guidance_action_lineage_invalid",
                "Persisted Storyboard action Turn request is malformed.",
            )
        guided_submission = request.get("guided_submission")
        if not isinstance(guided_submission, Mapping):
            return None
        if guided_submission.get("interaction_id") != interaction_id:
            raise _error(
                "guidance_action_lineage_invalid",
                "Persisted Storyboard action belongs to another interaction.",
            )
        submission_id = guided_submission.get("submission_id")
        if not isinstance(submission_id, str) or not submission_id:
            raise _error(
                "guidance_action_lineage_invalid",
                "Persisted Storyboard action has no guided submission identity.",
            )
        submission = self._interactions.get_submission_or_none(submission_id)
        if submission is None or submission.result is None:
            return None
        try:
            return GuidedInteractionAcceptedV1.model_validate(submission.result)
        except (TypeError, ValueError, ValidationError) as error:
            raise _error(
                "guidance_action_lineage_invalid",
                "Persisted Storyboard guided result is malformed.",
            ) from error

    def _load_persisted_storyboard_action(
        self,
        workflow_id: str,
        proposal_id: str,
    ) -> tuple[ProposalPublicationEnvelopeV1, ProposalActionRequestV2] | None:
        """Load immutable Storyboard action facts from the canonical Turn."""

        proposal = self._conversations.get_private_proposal(proposal_id)
        if (
            proposal.workflow_id != workflow_id
            or proposal.capability_id != "storyboard_design"
            or proposal.materialization is None
            or proposal.materialization.status not in {"completed", "failed"}
        ):
            return None
        try:
            envelope = self._materializations.get_envelope(
                "envelope_" + _digest(proposal.materialization.materialization_id)[:32]
            )
            if not isinstance(envelope, ProposalPublicationEnvelopeV1):
                raise ValueError("Storyboard operation is not a publication envelope.")
            canonical_turn = self._conversations.get_turn(envelope.action_turn_id)
            if (
                canonical_turn.workflow_id != workflow_id
                or canonical_turn.conversation_id != envelope.conversation_id
                or canonical_turn.turn_kind != "proposal_action"
            ):
                raise ValueError("Storyboard action Turn ownership is malformed.")
            request_payload = canonical_turn.request
            if not isinstance(request_payload, Mapping):
                raise ValueError("Storyboard action Turn request is malformed.")
            if request_payload.get("proposal_id") != proposal_id:
                raise ValueError("Storyboard action Turn points to another Proposal.")
            action_payload = request_payload.get("action")
            if not isinstance(action_payload, Mapping):
                raise ValueError("Storyboard action Turn has no typed action.")
            canonical_action = TypeAdapter(ProposalActionRequestV2).validate_python(action_payload)
            if (
                envelope.capability_id != "storyboard_design"
                or envelope.action != canonical_action.action
                or not _action_matches_envelope(canonical_action, envelope)
            ):
                raise ValueError("Storyboard action does not match its envelope.")
        except (V2PersistenceError, ValidationError, TypeError, ValueError) as error:
            raise _error(
                "guidance_action_lineage_invalid",
                "Persisted Storyboard selection lineage is invalid.",
            ) from error
        if (
            envelope.workflow_id != workflow_id
            or envelope.proposal_id != proposal_id
            or envelope.action_turn_id != canonical_turn.turn_id
        ):
            raise _error(
                "guidance_action_lineage_invalid",
                "Persisted Storyboard selection ownership is inconsistent.",
            )
        return envelope, canonical_action

    def _queue_persisted_storyboard_action(
        self,
        envelope: ProposalPublicationEnvelopeV1,
        canonical_action: ProposalActionRequestV2,
        *,
        idempotency_key: str,
    ) -> ChatTurnAcceptedV2:
        proposal = self._conversations.get_private_proposal(envelope.proposal_id)
        previous_status = (
            proposal.materialization.status if proposal.materialization is not None else None
        )
        self._materializations.queue(
            envelope,
            action_request={
                "proposal_id": envelope.proposal_id,
                "action": canonical_action.model_dump(mode="json", exclude_none=True),
            },
            idempotency_key=idempotency_key,
        )
        return ChatTurnAcceptedV2(
            workflow_id=envelope.workflow_id,
            conversation_id=envelope.conversation_id,
            message_id=None,
            turn_id=envelope.action_turn_id,
            events_cursor=self._materializations.events_cursor(envelope.workflow_id),
            replayed=previous_status != "failed",
        )

    @staticmethod
    def _guided_replay_action(
        request: GuidedConceptSubmitV2,
        canonical_action: ProposalActionRequestV2,
    ) -> ProposalActionRequestV2 | None:
        if request.action == "select" and isinstance(canonical_action, SelectOptionActionV2):
            return SelectOptionActionV2(
                action_id=canonical_action.action_id,
                action="select_option",
                option_id=request.option_id,
                expected_session_revision=canonical_action.expected_session_revision,
                accepted_references=tuple(
                    ProposedDraftReferenceV2.model_validate(reference.model_dump())
                    for reference in request.accepted_references
                ),
            )
        if request.action == "custom" and isinstance(canonical_action, CustomDirectionActionV2):
            return CustomDirectionActionV2(
                action_id=canonical_action.action_id,
                action="custom_direction",
                custom_text=request.custom_text,
                expected_session_revision=canonical_action.expected_session_revision,
            )
        if request.action == "delegate" and isinstance(canonical_action, DelegateChoiceActionV2):
            return canonical_action
        return None

    @staticmethod
    def _proposal_action_for_replay(interaction, request, proposal):
        """Build a typed action without trusting a closed interaction's status."""

        if request.action == "select":
            if request.option_id is None or not any(
                option.option_id == request.option_id for option in proposal.options
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
                    "guided_interaction_action_not_allowed",
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
        if request.action == "custom" and request.custom_text is not None:
            descriptor = next(
                (
                    candidate
                    for candidate in proposal.actions
                    if candidate.action == "custom_direction"
                ),
                None,
            )
            if descriptor is None:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "Custom direction is not available for the current Proposal.",
                )
            return CustomDirectionActionV2(
                action_id=descriptor.action_id,
                action="custom_direction",
                custom_text=request.custom_text,
                expected_session_revision=request.expected_session_revision,
            )
        if request.action == "delegate":
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
        return None

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
        if action_name == "custom":
            if request.custom_text is None:
                raise _error(
                    "journey_custom_input_invalid",
                    "A custom guided direction is required.",
                )
            descriptor = next(
                (
                    candidate
                    for candidate in proposal.actions
                    if candidate.action == "custom_direction"
                ),
                None,
            )
            if descriptor is None:
                raise _error(
                    "guided_interaction_action_not_allowed",
                    "Custom direction is not available for the current Proposal.",
                )
            return CustomDirectionActionV2(
                action_id=descriptor.action_id,
                action="custom_direction",
                custom_text=request.custom_text,
                expected_session_revision=request.expected_session_revision,
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

    @staticmethod
    def _proposal_action_matches_submission(
        proposal_id: str,
        action: ProposalActionRequestV2,
        submission: GuidedConceptSubmitV2,
    ) -> bool:
        expected_action = {
            "select": "select_option",
            "custom": "custom_direction",
            "delegate": "delegate_choice",
            "defer": "defer_topic",
            "exclude": "exclude_element",
        }[submission.action]
        if (
            action.action != expected_action
            or action.action_id
            != f"{expected_action}:{proposal_id}:{submission.expected_session_revision}"
            or action.expected_session_revision != submission.expected_session_revision
        ):
            return False
        if isinstance(action, SelectOptionActionV2):
            return (
                submission.option_id == action.option_id
                and tuple(
                    ProposedDraftReferenceV2.model_validate(reference.model_dump())
                    for reference in submission.accepted_references
                )
                == action.accepted_references
            )
        if isinstance(action, CustomDirectionActionV2):
            return submission.custom_text == action.custom_text
        return (
            isinstance(action, DelegateChoiceActionV2)
            if submission.action == "delegate"
            else isinstance(action, (DeferTopicActionV2, ExcludeElementActionV2))
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _storyboard_actions_equivalent(
    requested: ProposalActionRequestV2,
    canonical: ProposalActionRequestV2,
    envelope: ProposalPublicationEnvelopeV1,
) -> bool:
    """Compare replay payload semantics while ignoring route-local action IDs."""

    if (
        requested.action != canonical.action
        or requested.expected_session_revision != canonical.expected_session_revision
    ):
        return False
    if isinstance(canonical, SelectOptionActionV2):
        if not isinstance(requested, SelectOptionActionV2):
            return False
        if requested.option_id != canonical.option_id:
            return False
        expected = tuple(
            reference.model_dump(mode="json", exclude_none=True)
            for reference in envelope.reference_plan.references
        )
        return _normalize_reference_payloads(
            requested.accepted_references, expected
        ) == expected and (
            _normalize_reference_payloads(canonical.accepted_references, expected) == expected
        )
    if isinstance(canonical, CustomDirectionActionV2):
        return isinstance(requested, CustomDirectionActionV2) and (
            requested.custom_text == canonical.custom_text
        )
    if isinstance(canonical, ReuseDirectionActionV2):
        return isinstance(requested, ReuseDirectionActionV2) and (
            requested.option_id == canonical.option_id
        )
    return type(requested) is type(canonical)


def _normalize_reference_payloads(references, expected: tuple[dict[str, object], ...]):
    """Normalize route-local reference ordering without collapsing duplicates."""

    expected_by_identity = {
        (str(reference["source_kind"]), str(reference["source_id"])): index
        for index, reference in enumerate(expected)
    }
    if len(expected_by_identity) != len(expected):
        return None
    normalized = []
    seen: set[tuple[str, str]] = set()
    for reference in references:
        payload = reference.model_dump(mode="json", exclude_none=True)
        identity = (str(payload.get("source_kind")), str(payload.get("source_id")))
        if identity not in expected_by_identity or identity in seen:
            return None
        seen.add(identity)
        normalized.append(payload)
    if len(normalized) != len(expected):
        return None
    normalized.sort(
        key=lambda payload: expected_by_identity[
            (str(payload["source_kind"]), str(payload["source_id"]))
        ]
    )
    return tuple(normalized)


def _action_matches_envelope(
    action: ProposalActionRequestV2,
    envelope: ProposalPublicationEnvelopeV1,
) -> bool:
    """Check immutable action fields before allowing a closed replay."""

    # Compatibility action IDs are Proposal descriptors, while the envelope
    # stores the deterministic Turn ID.  The descriptor is immutable in the
    # canonical action Turn; only its presence is required here because the
    # domain selection identity intentionally excludes this route-local marker.
    if not action.action_id:
        return False
    if action.expected_session_revision != envelope.expected_session_revision:
        return False
    if isinstance(action, SelectOptionActionV2):
        if (
            envelope.action != "select_option"
            or action.option_id != envelope.selected_option.option_id
        ):
            return False
        expected = tuple(
            reference.model_dump(mode="json", exclude_none=True)
            for reference in envelope.reference_plan.references
        )
        return _normalize_reference_payloads(action.accepted_references, expected) == expected
    if isinstance(action, CustomDirectionActionV2):
        return (
            envelope.action == "custom_direction"
            and action.custom_text == envelope.selected_option.custom_text
        )
    if isinstance(action, ReuseDirectionActionV2):
        return (
            envelope.action == "reuse_direction"
            and action.option_id == envelope.selected_option.option_id
        )
    if isinstance(action, DelegateChoiceActionV2):
        return envelope.action == "delegate_choice"
    return False


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="guided_interaction_service")
