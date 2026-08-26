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
        replayed = self._conversations.get_turn_by_idempotency_key(idempotency_key) is not None
        turn_id = (
            "turn_"
            + _digest(f"materialization-action:{workflow_id}:{proposal_id}:{idempotency_key}")[:32]
        )
        accepted = ChatTurnAcceptedV2(
            workflow_id=workflow_id,
            conversation_id=source_turn.conversation_id,
            message_id=None,
            turn_id=turn_id,
            events_cursor=0,
        )
        envelope = self._build_envelope(proposal, action, accepted)
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

    def _reference_plan(self, proposal, action) -> ProposalReferencePlanV1:
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
    ) -> CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1:
        self._validate_capability(proposal)
        if proposal.materialization is not None:
            if proposal.materialization.turn_id == accepted.turn_id:
                return self._load_envelope(proposal.materialization.materialization_id)
            if proposal.materialization.status in {"queued", "working"}:
                raise _error(
                    "proposal_materialization_conflict",
                    "Another Materialization attempt is active for this Proposal.",
                )
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
        reference_plan = self._reference_plan(proposal, action)
        attempt_no = (
            proposal.materialization.attempt_no + 1 if proposal.materialization is not None else 1
        )
        materialization_id = (
            "materialization_"
            + _digest(f"{proposal.proposal_id}:{accepted.turn_id}:{attempt_no}")[:32]
        )
        context_payload = {
            "workflow_id": proposal.workflow_id,
            "proposal_id": proposal.proposal_id,
            "proposal_revision": proposal.proposal_revision,
            "option": option.model_dump(mode="json"),
            "reference_plan_digest": reference_plan.digest,
            "capability_id": proposal.capability_id,
        }
        context_digest = _json_digest(context_payload)
        result_contract = CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS[
            proposal.capability_id
        ].__name__
        stage_revision = self._conversations.get_guidance_session(
            proposal.workflow_id
        ).journey.stage_revision
        operation_kind = (
            "parent"
            if proposal.capability_id in {"product_design", "character_design"}
            else "standalone"
        )
        derivative_intent = (
            _parent_derivative_intent(
                workflow_id=proposal.workflow_id,
                materialization_id=materialization_id,
                stage_revision=stage_revision,
                capability_id=proposal.capability_id,
            )
            if operation_kind == "parent"
            else None
        )
        request_identity = f"capability-materialization:{materialization_id}:attempt:{attempt_no}"
        return self._create_envelope(
            payload={
                "envelope_id": "envelope_" + _digest(materialization_id)[:32],
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
        occurrence_id="character-1" if is_character else "product-1",
        parent=ParentNodeSnapshotV1(
            node_id=node_id,
            node_revision=1,
            semantic_role=semantic_role,
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
