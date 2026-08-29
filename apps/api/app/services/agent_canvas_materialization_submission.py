"""Freeze one Proposal choice and enqueue selected capability Materialization."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json

from pydantic import ValidationError

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_conversation import (
    ChatTurnAcceptedV2,
    CustomDirectionActionV2,
    DelegateChoiceActionV2,
    ReuseDirectionActionV2,
    SelectOptionActionV2,
)
from app.schemas.agent_canvas_creative_session import ProposedDraftReferenceV2
from app.schemas.agent_canvas_materialization import (
    CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS,
    CapabilityMaterializationEnvelopeV1,
    ParentDerivedMaterializationIntentV1,
    ParentNodeSnapshotV1,
    ProposalPublicationEnvelopeV1,
    ProposalReferencePlanV1,
    ProposalReferenceSnapshotV1,
    SelectedProposalCardV2,
    SelectedConceptOptionV1,
)
from app.services.agent_canvas_requirements import character_occurrences_for_authoring
from app.services.agent_canvas_storyboard_selection_identity import (
    StoryboardSelectionIdentityV1,
    StoryboardSelectionIdsV1,
    derive_storyboard_selection_ids,
)


class _ProposalSelectionSubmissionService:
    """Share selection validation for deterministic publication and Quick Media."""

    def __init__(
        self,
        conversations: AgentCanvasConversationRepository,
        materializations: AgentCanvasMaterializationRepository,
        *,
        reference_snapshot: Callable[[str, ProposedDraftReferenceV2], tuple[int | None, str | None]]
        | None = None,
    ) -> None:
        self._conversations = conversations
        self._materializations = materializations
        self._reference_snapshot = reference_snapshot

    def submit(
        self,
        proposal_id: str,
        action: (
            SelectOptionActionV2
            | CustomDirectionActionV2
            | DelegateChoiceActionV2
            | ReuseDirectionActionV2
        ),
        accepted: ChatTurnAcceptedV2,
    ) -> CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1:
        proposal = self._conversations.get_private_proposal(proposal_id)
        envelope = self._build_envelope(proposal, action, accepted)
        self._materializations.queue(envelope)
        return envelope

    def submit_action(
        self,
        workflow_id: str,
        proposal_id: str,
        action: (
            SelectOptionActionV2
            | CustomDirectionActionV2
            | DelegateChoiceActionV2
            | ReuseDirectionActionV2
        ),
        *,
        idempotency_key: str,
        guided_submission: dict[str, object] | None = None,
    ) -> ChatTurnAcceptedV2:
        proposal = self._conversations.get_private_proposal(proposal_id)
        if proposal.workflow_id != workflow_id:
            raise _error("proposal_not_found", "Concept proposal was not found.")
        source_turn = self._conversations.get_turn(proposal.turn_id)
        storyboard_identity: StoryboardSelectionIdentityV1 | None = None
        storyboard_ids: StoryboardSelectionIdsV1 | None = None
        if proposal.capability_id == "storyboard_design":
            storyboard_identity = self._storyboard_identity(proposal, action)
            storyboard_ids = derive_storyboard_selection_ids(storyboard_identity)
            turn_id = storyboard_ids.action_turn_id
            replayed = self._materializations.storyboard_identity_exists(
                storyboard_identity.digest
            ) or self._materializations.storyboard_alias_exists(
                idempotency_key,
                storyboard_identity.digest,
            )
        else:
            turn_id = (
                "turn_"
                + _digest(
                    f"materialization-action:{workflow_id}:{proposal_id}:{idempotency_key}"
                )[:32]
            )
            replayed = self._conversations.get_turn_by_idempotency_key(idempotency_key) is not None
        accepted = ChatTurnAcceptedV2(
            workflow_id=workflow_id,
            conversation_id=source_turn.conversation_id,
            message_id=None,
            turn_id=turn_id,
            events_cursor=0,
        )
        envelope = self._build_envelope(
            proposal,
            action,
            accepted,
            storyboard_identity=storyboard_identity,
            storyboard_ids=storyboard_ids,
        )
        action_request: dict[str, object] = {
            "proposal_id": proposal_id,
            "action": action.model_dump(mode="json", exclude_none=True),
        }
        if guided_submission is not None:
            action_request["guided_submission"] = guided_submission
        self._materializations.queue(
            envelope,
            action_request=action_request,
            idempotency_key=idempotency_key,
        )
        return accepted.model_copy(
            update={
                "events_cursor": self._materializations.events_cursor(workflow_id),
                "replayed": replayed,
            }
        )

    def _reference_plan(
        self,
        proposal,
        action,
        *,
        canonical_order: bool = False,
    ) -> ProposalReferencePlanV1:
        allowed = {
            (reference.source_kind, reference.source_id): reference
            for reference in proposal.proposed_references
        }
        supplied = (
            action.accepted_references
            if isinstance(action, SelectOptionActionV2)
            else proposal.proposed_references
        )
        accepted = []
        seen: set[tuple[str, str]] = set()
        for reference in supplied:
            identity = (reference.source_kind, reference.source_id)
            persisted = allowed.get(identity)
            if persisted is None:
                raise _error(
                    "proposal_reference_plan_invalid",
                    "Accepted reference was not included in the Proposal.",
                )
            if identity not in seen:
                accepted.append(persisted)
                seen.add(identity)
        if canonical_order:
            accepted = [
                reference
                for reference in proposal.proposed_references
                if (reference.source_kind, reference.source_id) in seen
            ]
        missing_required = [
            reference
            for identity, reference in allowed.items()
            if reference.required and identity not in seen
        ]
        if missing_required:
            raise _error(
                "guided_reference_required_missing",
                "Every required Proposal reference must be accepted.",
            )
        snapshots = []
        if self._reference_snapshot is not None:
            for reference in accepted:
                source_revision, asset_version_id = self._reference_snapshot(
                    proposal.workflow_id,
                    reference,
                )
                try:
                    snapshots.append(
                        ProposalReferenceSnapshotV1(
                            source_kind=reference.source_kind,
                            source_id=reference.source_id,
                            source_revision=source_revision,
                            asset_version_id=asset_version_id,
                        )
                    )
                except ValidationError as error:
                    raise _error(
                        "proposal_reference_plan_invalid",
                        "Accepted reference version identity could not be frozen.",
                    ) from error
        reference_payload = {
            "references": [reference.model_dump(mode="json") for reference in accepted],
            "source_snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots],
        }
        digest = _json_digest(reference_payload)
        return ProposalReferencePlanV1(
            plan_id="reference_plan_" + digest[:32],
            references=tuple(accepted),
            source_snapshots=tuple(snapshots),
            digest=digest,
        )

    def _storyboard_identity(self, proposal, action) -> StoryboardSelectionIdentityV1:
        """Resolve the immutable Storyboard selection tuple before allocating a Turn."""

        option, _selection_reason, reference_plan = self._selection_components(
            proposal,
            action,
            canonical_reference_order=True,
        )
        session = self._conversations.get_guidance_session(proposal.workflow_id)
        custom_text_digest = (
            _digest(action.custom_text) if isinstance(action, CustomDirectionActionV2) else None
        )
        selected_option_id = (
            None if isinstance(action, CustomDirectionActionV2) else option.option_id
        )
        return StoryboardSelectionIdentityV1(
            workflow_id=proposal.workflow_id,
            proposal_id=proposal.proposal_id,
            proposal_revision=proposal.proposal_revision,
            action=action.action,
            selection_actor=("agent" if action.action == "delegate_choice" else "user"),
            selected_option_id=selected_option_id,
            custom_text_digest=custom_text_digest,
            reference_plan_digest=reference_plan.digest,
            expected_session_revision=action.expected_session_revision,
            stage_revision=session.journey.stage_revision,
            target_node_id=proposal.target_node_id,
            target_node_revision=proposal.target_node_revision,
        )

    def _selection_components(
        self,
        proposal,
        action,
        *,
        canonical_reference_order: bool = False,
    ) -> tuple[SelectedConceptOptionV1 | SelectedProposalCardV2, str | None, ProposalReferencePlanV1]:
        descriptor = next(
            (
                candidate
                for candidate in proposal.actions
                if candidate.action_id == action.action_id and candidate.action == action.action
            ),
            None,
        )
        if descriptor is None:
            raise _error("proposal_action_stale", "Proposal action is no longer available.")
        option_id = getattr(action, "option_id", None)
        selection_reason = None
        if isinstance(action, CustomDirectionActionV2):
            option_id = "custom_" + _digest(action.custom_text)[:32]
            option = SelectedProposalCardV2(
                option_id=option_id,
                title="Custom direction",
                public_summary=action.custom_text,
                custom_text=action.custom_text,
            )
            selection_reason = "The user supplied this direction directly."
        elif option_id is None:
            option_id = proposal.options[0].option_id
            selection_reason = "The first current option best matches the approved direction."
            option_model = (
                SelectedConceptOptionV1
                if proposal.proposal_card_schema_version < 2
                else SelectedProposalCardV2
            )
            option = option_model.model_validate(proposal.options[0].model_dump(mode="json"))
        else:
            proposal_option = next(
                (candidate for candidate in proposal.options if candidate.option_id == option_id),
                None,
            )
            if proposal_option is None:
                raise _error("proposal_option_not_found", "Concept option was not found.")
            option_model = (
                SelectedConceptOptionV1
                if proposal.proposal_card_schema_version < 2
                else SelectedProposalCardV2
            )
            option = option_model.model_validate(proposal_option.model_dump(mode="json"))
        reference_plan = self._reference_plan(
            proposal,
            action,
            canonical_order=canonical_reference_order,
        )
        return option, selection_reason, reference_plan

    def _build_envelope(
        self,
        proposal,
        action: (
            SelectOptionActionV2
            | CustomDirectionActionV2
            | DelegateChoiceActionV2
            | ReuseDirectionActionV2
        ),
        accepted: ChatTurnAcceptedV2,
        *,
        storyboard_identity: StoryboardSelectionIdentityV1 | None = None,
        storyboard_ids: StoryboardSelectionIdsV1 | None = None,
    ) -> CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1:
        self._validate_capability(proposal)
        canonical_storyboard = (
            proposal.capability_id == "storyboard_design"
            and storyboard_identity is not None
            and storyboard_ids is not None
        )
        if proposal.materialization is not None and not canonical_storyboard:
            if proposal.materialization.turn_id == accepted.turn_id:
                return self._load_envelope(proposal.materialization.materialization_id)
            if proposal.materialization.status in {"queued", "working"}:
                raise _error(
                    "proposal_materialization_conflict",
                    "Another Materialization attempt is active for this Proposal.",
                )
        option, selection_reason, reference_plan = self._selection_components(
            proposal,
            action,
            canonical_reference_order=canonical_storyboard,
        )
        if canonical_storyboard:
            assert storyboard_identity is not None
            assert storyboard_ids is not None
            if proposal.materialization is not None:
                if proposal.materialization.materialization_id == storyboard_ids.materialization_id:
                    return self._load_envelope(proposal.materialization.materialization_id)
                if proposal.materialization.status in {"queued", "working"}:
                    raise _error(
                        "proposal_materialization_conflict",
                        "Another Materialization attempt is active for this Proposal.",
                    )
                if proposal.materialization.status == "failed":
                    if not proposal.materialization.retryable:
                        raise _error(
                            "guidance_action_lineage_invalid",
                            "Storyboard Proposal has a non-retryable historical Materialization.",
                        )
                    existing = self._load_envelope(proposal.materialization.materialization_id)
                    existing_identity = getattr(existing, "agent_request_identity", None)
                    if existing_identity is None:
                        existing_identity = getattr(existing, "idempotency_identity", "")
                    if existing_identity == storyboard_ids.request_identity:
                        return existing
                    # A new identity is valid only for the explicit historical
                    # reuse action after the Proposal authority marked the old
                    # branch superseded.  Ordinary retries must stay on the
                    # failed canonical branch and never fork it.
                    if not (
                        action.action == "reuse_direction"
                        and proposal.availability == "superseded"
                    ):
                        raise _error(
                            "guidance_action_lineage_invalid",
                            "Storyboard Proposal retry does not match its canonical identity.",
                        )
            attempt_no = 1
            materialization_id = storyboard_ids.materialization_id
        else:
            attempt_no = (
                proposal.materialization.attempt_no + 1 if proposal.materialization is not None else 1
            )
            materialization_id = (
                "materialization_"
                + _digest(f"{proposal.proposal_id}:{accepted.turn_id}:{attempt_no}")[:32]
            )
        result_contract = CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS[
            proposal.capability_id
        ].__name__
        session = self._conversations.get_guidance_session(proposal.workflow_id)
        stage_revision = session.journey.stage_revision
        if canonical_storyboard:
            assert storyboard_identity is not None
            assert storyboard_ids is not None
            expected_option_id = (
                None if isinstance(action, CustomDirectionActionV2) else option.option_id
            )
            expected_custom_digest = (
                _digest(action.custom_text)
                if isinstance(action, CustomDirectionActionV2)
                else None
            )
            if (
                accepted.turn_id != storyboard_ids.action_turn_id
                or storyboard_ids.identity_digest != storyboard_identity.digest
                or storyboard_identity.workflow_id != proposal.workflow_id
                or storyboard_identity.proposal_id != proposal.proposal_id
                or storyboard_identity.proposal_revision != proposal.proposal_revision
                or storyboard_identity.action != action.action
                or storyboard_identity.selected_option_id != expected_option_id
                or storyboard_identity.custom_text_digest != expected_custom_digest
                or storyboard_identity.reference_plan_digest != reference_plan.digest
                or storyboard_identity.expected_session_revision
                != action.expected_session_revision
                or storyboard_identity.stage_revision != stage_revision
                or storyboard_identity.target_node_id != proposal.target_node_id
                or storyboard_identity.target_node_revision != proposal.target_node_revision
            ):
                raise _error(
                    "materialization_payload_conflict",
                    "Storyboard selection authority changed before Materialization.",
                )
        operation_kind = (
            "parent"
            if proposal.capability_id in {"product_design", "character_design"}
            else "standalone"
        )
        occurrence_id = None
        character_phase = None
        requirement_revision_id = None
        requirement_revision_no = None
        journey_action_id = accepted.turn_id
        if proposal.capability_id == "character_design":
            current_action = session.journey.active_action
            if (
                session.journey.stage != "character"
                or current_action is None
                or current_action.occurrence_id is None
                or session.journey.active_occurrence_id != current_action.occurrence_id
            ):
                raise _error(
                    "character_occurrence_invalid",
                    "Character materialization does not match the current occurrence.",
                )
            if current_action.character_phase != "main":
                raise _error(
                    "character_authoring_phase_invalid",
                    "Character Proposal selection requires the current Main phase.",
                )
            requirement = AgentCanvasRequirementRepository(
                self._conversations.database
            ).get_current(proposal.workflow_id)
            occurrence = next(
                (
                    item
                    for item in character_occurrences_for_authoring(requirement)
                    if item.occurrence_id == current_action.occurrence_id
                    and item.presence == "include"
                ),
                None,
            )
            if occurrence is None:
                raise _error(
                    "character_occurrence_invalid",
                    "Character materialization does not match the current Ledger occurrence.",
                )
            occurrence_id = occurrence.occurrence_id
            character_phase = current_action.character_phase
            requirement_revision_id = requirement.revision_id
            requirement_revision_no = requirement.revision_no
            journey_action_id = current_action.action_id
        if proposal.capability_id == "character_design":
            materialization_id = (
                "materialization_"
                + _digest(
                    ":".join(
                        (
                            proposal.workflow_id,
                            requirement_revision_id or "",
                            occurrence_id or "",
                            character_phase or "",
                            journey_action_id,
                            accepted.turn_id,
                            proposal.target_node_id or "",
                            str(proposal.target_node_revision or ""),
                            str(attempt_no),
                        )
                    )
                )[:32]
            )
        derivative_intent = (
            _parent_derivative_intent(
                workflow_id=proposal.workflow_id,
                materialization_id=materialization_id,
                stage_revision=stage_revision,
                capability_id=proposal.capability_id,
                occurrence_id=occurrence_id,
            )
            if operation_kind == "parent"
            else None
        )
        context_payload = {
            "workflow_id": proposal.workflow_id,
            "proposal_id": proposal.proposal_id,
            "proposal_revision": proposal.proposal_revision,
            "option": option.model_dump(mode="json"),
            "reference_plan_digest": reference_plan.digest,
            "capability_id": proposal.capability_id,
        }
        if canonical_storyboard:
            context_payload["storyboard_selection_identity_digest"] = storyboard_identity.digest
        if proposal.capability_id == "character_design":
            context_payload.update(
                {
                    "occurrence_id": occurrence_id,
                    "character_phase": character_phase,
                    "requirement_revision_id": requirement_revision_id,
                    "requirement_revision_no": requirement_revision_no,
                    "journey_action_id": journey_action_id,
                    "target_node_id": proposal.target_node_id,
                    "target_node_revision": proposal.target_node_revision,
                }
            )
        context_digest = _json_digest(context_payload)
        request_identity = (
            storyboard_ids.request_identity
            if canonical_storyboard and storyboard_ids is not None
            else f"capability-materialization:{materialization_id}:attempt:{attempt_no}"
        )
        envelope_id = (
            storyboard_ids.envelope_id
            if canonical_storyboard and storyboard_ids is not None
            else "envelope_" + _digest(materialization_id)[:32]
        )
        return self._create_envelope(
            payload={
                "envelope_id": envelope_id,
                "materialization_id": materialization_id,
                "proposal_id": proposal.proposal_id,
                "proposal_revision": proposal.proposal_revision,
                "workflow_id": proposal.workflow_id,
                "conversation_id": accepted.conversation_id,
                "action_turn_id": accepted.turn_id,
                "action": action.action,
                "selection_actor": ("agent" if action.action == "delegate_choice" else "user"),
                "selection_reason": selection_reason,
                "capability_id": proposal.capability_id,
                "occurrence_id": occurrence_id,
                "character_phase": character_phase,
                "requirement_revision_id": requirement_revision_id,
                "requirement_revision_no": requirement_revision_no,
                "selected_option": option,
                "reference_plan": reference_plan,
                "expected_session_revision": action.expected_session_revision,
                "stage_revision": stage_revision,
                "operation_kind": operation_kind,
                "derivative_intent": derivative_intent,
                "target_node_id": proposal.target_node_id,
                "target_node_revision": proposal.target_node_revision,
                "context_snapshot_id": "snapshot_" + context_digest[:32],
                "context_snapshot_digest": context_digest,
                "style_skill_run_id": proposal.video_skill_run_id,
                "attempt_no": attempt_no,
                "created_at": datetime.now(timezone.utc),
            },
            result_contract_name=result_contract,
            request_identity=request_identity,
        )

    def _validate_capability(self, proposal) -> None:
        del proposal

    def _create_envelope(
        self,
        *,
        payload: dict[str, object],
        result_contract_name: str,
        request_identity: str,
    ) -> CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1:
        return CapabilityMaterializationEnvelopeV1.model_validate(
            {
                **payload,
                "result_contract_name": result_contract_name,
                "agent_request_identity": request_identity,
            }
        )

    def _load_envelope(
        self, materialization_id: str
    ) -> CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1:
        envelope_id = "envelope_" + _digest(materialization_id)[:32]
        return self._materializations.get_envelope(envelope_id)


class QuickMediaMaterializationSubmissionService(_ProposalSelectionSubmissionService):
    """Queue the sole remaining model-assisted Proposal materialization path."""

    def _validate_capability(self, proposal) -> None:
        if proposal.capability_id != "quick_media":
            raise _error(
                "quick_media_materialization_invalid",
                "Only Quick Media uses model-assisted Proposal materialization.",
            )


class ProposalPublicationSubmissionService(_ProposalSelectionSubmissionService):
    """Queue deterministic Proposal publication while preserving the public lifecycle."""

    def _validate_capability(self, proposal) -> None:
        if proposal.capability_id == "quick_media":
            raise _error(
                "proposal_publication_invalid",
                "Quick Media does not use deterministic Proposal publication.",
            )

    def _create_envelope(
        self,
        *,
        payload: dict[str, object],
        result_contract_name: str,
        request_identity: str,
    ) -> ProposalPublicationEnvelopeV1:
        del result_contract_name
        return ProposalPublicationEnvelopeV1.model_validate(
            {**payload, "idempotency_identity": request_identity}
        )

    def _load_envelope(self, materialization_id: str) -> ProposalPublicationEnvelopeV1:
        envelope_id = "envelope_" + _digest(materialization_id)[:32]
        envelope = self._materializations.get_envelope(envelope_id)
        if not isinstance(envelope, ProposalPublicationEnvelopeV1):
            raise _error(
                "proposal_publication_invalid",
                "Persisted operation is not a Proposal publication.",
            )
        return envelope


def _json_digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _parent_derivative_intent(
    *,
    workflow_id: str,
    materialization_id: str,
    stage_revision: int,
    capability_id: str,
    occurrence_id: str | None = None,
) -> ParentDerivedMaterializationIntentV1:
    is_character = capability_id == "character_design"
    node_id = "node_" + _digest(f"{materialization_id}:main")[:32]
    derivative_role = "character_turnaround" if is_character else "product_multiview"
    semantic_role = "character_main" if is_character else "product_main"
    prompt_operation_id = "prompt_" + _digest(f"{materialization_id}:{node_id}")[:32]
    return ParentDerivedMaterializationIntentV1(
        intent_id="derivative_" + _digest(f"{materialization_id}:{derivative_role}")[:32],
        workflow_id=workflow_id,
        stage_revision=stage_revision,
        occurrence_id=(
            occurrence_id if is_character and occurrence_id is not None else "product-1"
        ),
        parent=ParentNodeSnapshotV1(
            node_id=node_id,
            node_revision=1,
            semantic_role=semantic_role,
            occurrence_id=occurrence_id if is_character else None,
            prompt_preparation_operation_id=prompt_operation_id,
        ),
        derivative_role=derivative_role,
        payload_digest=_digest(
            f"{workflow_id}:{node_id}:1:{prompt_operation_id}:{derivative_role}"
        ),
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="materialization_submission")
