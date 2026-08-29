"""Atomic persistence for selected capability Materialization attempts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
import hashlib
from typing import cast
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.persistence.agent_canvas_auto_run_repository import (
    AgentCanvasAutomaticRunRepository,
    is_automatic_run_eligible_node_type,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
    normalize_queued_node,
)
from app.persistence.agent_canvas_continuation_repository import (
    AgentCanvasContinuationOutboxRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
    _append_timeline_entry,
    _creative_memory,
    _creative_memory_values,
    _dump,
    _ensure_conversation,
    _next_chat_sequence,
    _now,
    _require_guidance_revision,
    _require_guidance_session_row,
    _require_turn,
)
from app.persistence.agent_canvas_operation_envelope_repository import (
    AgentCanvasOperationEnvelopeRepository,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasActionReceiptRow,
    AgentCanvasBindingRow,
    AgentCanvasChatEntryRow,
    AgentCanvasChatTurnRow,
    AgentCanvasContinuationOutboxRow,
    AgentCanvasConceptOptionRow,
    AgentCanvasConceptProposalRow,
    AgentCanvasCreativeDirectionSnapshotRow,
    AgentCanvasCreativeMemoryRow,
    AgentCanvasExecutionSettingsRow,
    AgentCanvasExpertActivityRow,
    AgentCanvasGuidanceSessionRow,
    AgentCanvasGuidanceTopicRow,
    AgentCanvasGuidanceAwaitingRow,
    AgentCanvasGuidedInteractionRow,
    AgentCanvasGuidedInteractionSubmissionRow,
    AgentCanvasMaterializationCommitRow,
    AgentCanvasNodeRow,
    AgentCanvasPromptContextSnapshotRow,
    AgentCanvasWorkflowRow,
    AgentWorkingDocumentRow,
    AssetVersionRow,
    WorkflowEventRow,
)
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas import (
    CanvasBindingV2,
    CanvasNodeV2,
    ResolvedTextInputSnapshotV2,
)
from app.schemas.agent_canvas_conversation import ProposalMaterializationProjectionV2
from app.services.agent_canvas_production_journey import parse_production_journey
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationEnvelopeV1,
    ProposalPublicationEnvelopeV1,
    SelectedConceptOptionV1,
)
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationAuthoritySnapshotV1,
    MaterializationDocumentWriteV1,
    MaterializationDocumentResultV1,
    MaterializationOutcomeV1,
    MaterializationPlanV1,
    StageMaterializedJourneyEventV1,
)
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation_dispatch import detached_context_payload
from app.schemas.agent_working_documents import (
    AgentAnchorImageAssetVersionSourceV3,
    AgentAnchorNodeSourceV3,
    AgentWorkingDocumentV2,
    AnchorRegistryContentV3,
    StoryboardProductionPlanContentV3,
)
from app.schemas.agent_canvas_guided_interactions import (
    GuidedConceptSubmitV2,
    GuidedInteractionAcceptedV1,
    GuidedInteractionSubmitRequestV1,
)
from app.schemas.agent_canvas_requirements import (
    CharacterOccurrenceV1,
    RequirementDirectiveV1,
    RequirementLedgerV1,
    RequirementLedgerRevisionV1,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_requirement_directives import (
    canonicalize_requirement_directives,
)
from app.services.agent_canvas_user_presentation import build_presentation_metadata
from app.services.agent_canvas_requirements import (
    reconcile_character_occurrence_authority_in_transaction,
    update_requirement_compatibility_projection_in_transaction,
)
from app.services.agent_canvas_character_occurrence_authority import (
    CharacterOccurrenceAuthoritySource,
)
from app.services.response_locale_resolver import ResponseLocaleResolverV1
from app.services.agent_canvas_production_journey_reducer import (
    GuidedProductionJourneyReducer,
)
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


MaterializationEnvelopeV1 = CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1


class AgentCanvasMaterializationRepository:
    """Queue and project one immutable selected-option Materialization attempt."""

    def __init__(
        self,
        database: V2Database,
        events: EventRepository,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if events.database is not database:
            raise ValueError("Materialization and event repositories must share one database.")
        self._database = database
        self._events = events
        self._envelopes = AgentCanvasOperationEnvelopeRepository(database)
        self._outbox = AgentCanvasContinuationOutboxRepository(database, events)
        self._conversations = AgentCanvasConversationRepository(database, events)
        self._automatic_runs = AgentCanvasAutomaticRunRepository(database, events)
        self._requirements = AgentCanvasRequirementRepository(database)
        self._working_documents = AgentWorkingDocumentRepository(database, events)
        self._prompt_dispatch = AgentCanvasPromptPreparationDispatchRepository(database, events)
        self._fault_injector = fault_injector

    def get_completed_outcome(
        self,
        materialization_id: str,
        action_turn_id: str,
    ) -> MaterializationOutcomeV1 | None:
        """Return the immutable completed outcome used for publication replay."""

        with self._database.engine.connect() as connection:
            row = (
                connection.execute(
                    select(AgentCanvasMaterializationCommitRow).where(
                        AgentCanvasMaterializationCommitRow.materialization_id
                        == materialization_id,
                        AgentCanvasMaterializationCommitRow.action_turn_id == action_turn_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return MaterializationOutcomeV1.model_validate_json(str(row["outcome_json"]))

    def commit(
        self,
        plan: MaterializationPlanV1,
        *,
        reducer: GuidedProductionJourneyReducer,
    ) -> MaterializationOutcomeV1:
        """Commit or strictly replay one immutable materialization plan."""

        return self._commit_plan_transaction(plan, reducer)

    def _commit_plan_transaction(
        self,
        materialization_plan: MaterializationPlanV1,
        journey_reducer: GuidedProductionJourneyReducer,
    ) -> MaterializationOutcomeV1:
        """Persist one complete plan under a single immediate transaction."""

        proposal_id = materialization_plan.proposal_id
        option_id = materialization_plan.option_id
        nodes = materialization_plan.nodes
        bindings = materialization_plan.bindings
        expected_workflow_revision = materialization_plan.expected_workflow_revision
        selection_actor = materialization_plan.selection_actor
        source_turn_id = materialization_plan.action_turn_id
        expected_session_revision = materialization_plan.expected_session_revision
        proposal_action = materialization_plan.proposal_action
        receipt = materialization_plan.receipt
        continuation = materialization_plan.continuation
        materialization_id = materialization_plan.materialization_id
        workflow_id = materialization_plan.workflow_id
        fault_injector = self._fault_injector
        proposal = self._conversations.get_private_proposal(proposal_id)
        skill_run_id = proposal.video_skill_run_id
        topic_id = proposal.topic_id

        primary_node = nodes[0] if nodes else None
        preparation_contexts = {
            item.node_id: item.context for item in materialization_plan.prompt_preparations
        }
        node_ids = tuple(item.node_id for item in nodes)
        if len(set(node_ids)) != len(node_ids) or any(
            item.workflow_id != workflow_id for item in nodes
        ):
            raise _error(
                "draft_bundle_invalid",
                "Draft bundle Nodes require unique IDs in one Workflow.",
            )
        if any(
            binding.workflow_id != workflow_id or binding.target_node_id not in set(node_ids)
            for binding in bindings
        ):
            raise _error(
                "draft_binding_invalid",
                "Draft bundle Bindings must target a published bundle Node.",
            )

        if materialization_plan.proposal_action == "custom_direction":
            if materialization_plan.custom_text is None:
                raise _error(
                    "guided_interaction_option_invalid",
                    "Custom Materialization requires the original custom direction.",
                )
            selected_option = SelectedConceptOptionV1(
                option_id=option_id,
                title="Custom direction",
                public_summary=materialization_plan.custom_text,
                key_decisions=(materialization_plan.custom_text,),
                custom_text=materialization_plan.custom_text,
            )
        else:
            selected_option = next(
                (option for option in proposal.options if option.option_id == option_id),
                None,
            )
            if selected_option is None:
                raise _error("proposal_option_not_found", "Concept option was not found.")
        now = _now()
        materialization_outcome: MaterializationOutcomeV1 | None = None
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    existing_commit = (
                        connection.execute(
                            select(AgentCanvasMaterializationCommitRow).where(
                                (
                                    AgentCanvasMaterializationCommitRow.materialization_id
                                    == materialization_plan.materialization_id
                                )
                                | (
                                    AgentCanvasMaterializationCommitRow.action_turn_id
                                    == materialization_plan.action_turn_id
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing_commit is not None:
                        if (
                            str(existing_commit["materialization_id"])
                            != materialization_plan.materialization_id
                            or str(existing_commit["payload_digest"])
                            != materialization_plan.payload_digest
                        ):
                            raise _error(
                                "materialization_payload_conflict",
                                "Materialization identity was reused with a different payload.",
                            )
                        connection.rollback()
                        return MaterializationOutcomeV1.model_validate_json(
                            str(existing_commit["outcome_json"])
                        ).model_copy(update={"replayed": True})
                    _require_current_derivative_parent(
                        connection,
                        materialization_plan,
                    )
                    current = connection.execute(
                        select(AgentCanvasWorkflowRow.revision).where(
                            AgentCanvasWorkflowRow.workflow_id == proposal.workflow_id
                        )
                    ).scalar_one_or_none()
                    if current != expected_workflow_revision:
                        raise _error(
                            "proposal_revision_conflict",
                            "Workflow changed before proposal materialization.",
                        )
                    proposal_state = (
                        connection.execute(
                            select(
                                AgentCanvasConceptProposalRow.availability,
                                AgentCanvasConceptProposalRow.video_skill_run_id,
                                AgentCanvasConceptProposalRow.topic_id,
                                AgentCanvasConceptProposalRow.capability_id,
                                AgentCanvasConceptProposalRow.creative_direction_snapshot_id,
                                AgentCanvasConceptProposalRow.requirement_revision_id,
                                AgentCanvasConceptProposalRow.requirement_revision_no,
                                AgentCanvasConceptProposalRow.requirement_digest,
                                AgentCanvasConceptProposalRow.proposal_revision,
                                AgentCanvasConceptProposalRow.target_node_id,
                            ).where(
                                AgentCanvasConceptProposalRow.proposal_id == proposal_id,
                                AgentCanvasConceptProposalRow.workflow_id == proposal.workflow_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    persisted_availability = (
                        str(proposal_state["availability"]) if proposal_state is not None else None
                    )
                    availability_valid = (
                        persisted_availability == "open"
                        or (
                            proposal_action == "reuse_direction"
                            and persisted_availability == "superseded"
                        )
                        or (
                            materialization_plan.operation_kind == "derivative"
                            and persisted_availability == "applied"
                        )
                    )
                    if not availability_valid:
                        raise _error(
                            "proposal_not_available",
                            "Proposal is not available for application.",
                        )
                    if (
                        int(proposal_state["proposal_revision"])
                        != materialization_plan.expected_proposal_revision
                    ):
                        raise _error(
                            "proposal_revision_conflict",
                            "Proposal changed before materialization.",
                        )
                    if materialization_plan.expected_target_node_revision is not None:
                        target_node_id = proposal_state["target_node_id"]
                        target_revision = (
                            connection.execute(
                                select(AgentCanvasNodeRow.revision).where(
                                    AgentCanvasNodeRow.node_id == target_node_id,
                                    AgentCanvasNodeRow.workflow_id == proposal.workflow_id,
                                )
                            ).scalar_one_or_none()
                            if target_node_id is not None
                            else None
                        )
                        if target_revision != materialization_plan.expected_target_node_revision:
                            raise _error(
                                "proposal_target_revision_stale",
                                "The targeted Node changed before materialization.",
                            )
                    requirement_head = self._requirements.get_current_in_transaction(
                        connection,
                        proposal.workflow_id,
                    )
                    if materialization_plan.operation_kind != "derivative" and (
                        proposal_state["requirement_revision_id"] != requirement_head.revision_id
                        or proposal_state["requirement_revision_no"] != requirement_head.revision_no
                        or proposal_state["requirement_digest"] != requirement_head.digest
                    ):
                        raise _error(
                            "requirement_revision_superseded",
                            "Requirements changed before Proposal selection.",
                        )
                    persisted_skill_run_id = (
                        str(proposal_state["video_skill_run_id"])
                        if proposal_state["video_skill_run_id"]
                        else None
                    )
                    if skill_run_id != persisted_skill_run_id:
                        raise _error(
                            "style_skill_snapshot_invalid",
                            "Proposal Style Skill provenance is inconsistent.",
                        )
                    creative_direction_snapshot_id = (
                        str(proposal_state["creative_direction_snapshot_id"])
                        if proposal_state["creative_direction_snapshot_id"]
                        else None
                    )
                    skill_refs: tuple[dict[str, str], ...] = ()
                    if persisted_skill_run_id is not None:
                        snapshot_row = (
                            connection.execute(
                                select(AgentCanvasCreativeDirectionSnapshotRow).where(
                                    AgentCanvasCreativeDirectionSnapshotRow.snapshot_id
                                    == creative_direction_snapshot_id
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if snapshot_row is None:
                            raise _error(
                                "style_skill_snapshot_invalid",
                                "Proposal Creative Direction snapshot is unavailable.",
                            )
                        capability_id = str(proposal_state["capability_id"])
                        role = (
                            VideoAgentOperationRegistry()
                            .for_capability(cast(CapabilityIdV1, capability_id))
                            .style_projection_role
                        )
                        if role is None:
                            raise _error(
                                "style_skill_snapshot_invalid",
                                "Proposal capability does not define a Style projection role.",
                            )
                        projection = json.loads(str(snapshot_row["role_projections_json"])).get(
                            role
                        )
                        skill_ref = {
                            "skill_run_id": persisted_skill_run_id,
                            "skill_id": str(snapshot_row["source_skill_id"]),
                            "skill_version": str(snapshot_row["source_skill_version"]),
                            "package_digest": str(snapshot_row["source_skill_digest"]),
                            "role": role,
                        }
                        if isinstance(projection, dict):
                            role_digest = str(projection.get("digest") or "")
                            if role_digest:
                                skill_ref["role_guidance_digest"] = role_digest
                        skill_refs = (skill_ref,)
                    session = _require_guidance_session_row(
                        connection,
                        proposal.guidance_session_id,
                    )
                    _require_guidance_revision(session, expected_session_revision)
                    guided_submission = _guided_submission_context(
                        connection,
                        source_turn_id=source_turn_id,
                        workflow_id=proposal.workflow_id,
                        proposal_id=proposal_id,
                        option_id=option_id,
                        expected_session_revision=expected_session_revision,
                    )
                    current_journey = parse_production_journey(str(session["journey_state_json"]))
                    next_journey = journey_reducer.reduce(
                        current_journey,
                        materialization_plan.journey_event,
                    )
                    next_awaiting = None
                    if (
                        materialization_plan.operation_kind != "derivative"
                        and proposal_action != "reuse_direction"
                        and str(session["active_proposal_id"]) != proposal_id
                    ):
                        raise _error(
                            "proposal_action_stale",
                            "Proposal is not the current Guidance checkpoint.",
                        )
                    snapshot_ids: dict[str, str] = {}
                    for bundle_node in nodes:
                        node_bindings = tuple(
                            binding
                            for binding in bindings
                            if binding.target_node_id == bundle_node.node_id
                        )
                        snapshot_ids[bundle_node.node_id] = _insert_materialized_node(
                            connection,
                            node=bundle_node,
                            bindings=node_bindings,
                            creative_direction_snapshot_id=creative_direction_snapshot_id,
                            skill_refs=skill_refs,
                            now=now,
                            prompt_dispatch=self._prompt_dispatch,
                            prompt_context=preparation_contexts.get(bundle_node.node_id),
                        )
                    if fault_injector is not None:
                        fault_injector("node")
                        fault_injector("binding")
                    document_results: list[MaterializationDocumentResultV1] = []
                    document_kinds: dict[str, str] = {}
                    for document_write in materialization_plan.document_writes:
                        mutation = document_write.mutation_plan
                        if mutation is None:
                            document = self._working_documents.validate_document_payload(
                                document_write.payload
                            )
                            document_kinds[document.document_id] = document.kind
                            _validate_authority_document_sources(
                                connection,
                                plan=materialization_plan,
                                document=document,
                            )
                            _insert_materialization_document(
                                connection,
                                plan=materialization_plan,
                                guidance_session_id=proposal.guidance_session_id,
                                document_write=document_write,
                            )
                            document_results.append(
                                MaterializationDocumentResultV1(
                                    document_id=document.document_id,
                                    operation="create_document",
                                    after_revision=document.revision,
                                    after_digest=document.content_digest,
                                )
                            )
                            continue
                        current = (
                            connection.execute(
                                select(AgentWorkingDocumentRow).where(
                                    AgentWorkingDocumentRow.document_id == mutation.document_id
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if current is None:
                            raise _error(
                                "agent_document_not_found",
                                "Agent working document was not found.",
                            )
                        current_document = self._working_documents.validate_document_row(current)
                        document_kinds[current_document.document_id] = current_document.kind
                        next_document = current_document.model_copy(
                            update={
                                "revision": mutation.next_revision,
                                "content": mutation.next_content,
                                "content_schema_version": 3,
                                "content_digest": self._working_documents.digest_content(
                                    mutation.next_content
                                ),
                            }
                        )
                        _validate_authority_document_sources(
                            connection,
                            plan=materialization_plan,
                            document=next_document,
                        )
                        updated_document = self._working_documents.apply_content_in_transaction(
                            connection,
                            document_id=mutation.document_id,
                            expected_revision=mutation.expected_revision,
                            operation=mutation.operation,
                            content=mutation.next_content,
                            agent_run_id=materialization_plan.materialization_id,
                            idempotency_key=mutation.idempotency_key,
                            now=datetime.fromisoformat(now),
                            request_digest=mutation.request_digest,
                        )
                        document_results.append(
                            MaterializationDocumentResultV1(
                                document_id=mutation.document_id,
                                operation=mutation.operation,
                                before_revision=int(current["revision"]),
                                after_revision=updated_document.revision,
                                before_digest=str(current["content_digest"]),
                                after_digest=updated_document.content_digest,
                            )
                        )
                        _append_authority_document_events(
                            connection,
                            events=self._events,
                            before=current_document,
                            after=updated_document,
                            operation=mutation.operation,
                            receipt_id=(
                                receipt.receipt_id if receipt is not None else materialization_id
                            ),
                        )
                    for document_write, document_result in zip(
                        materialization_plan.document_writes,
                        document_results,
                        strict=True,
                    ):
                        if document_result.before_revision is not None:
                            continue
                        document = self._working_documents.validate_document_payload(
                            document_write.payload
                        )
                        _append_authority_document_events(
                            connection,
                            events=self._events,
                            before=None,
                            after=document,
                            operation=document_result.operation,
                            receipt_id=(
                                receipt.receipt_id if receipt is not None else materialization_id
                            ),
                        )
                    if fault_injector is not None:
                        fault_injector("document")
                    requirement_revision = requirement_head
                    if (
                        proposal.capability_id != "quick_media"
                        and materialization_plan.operation_kind != "derivative"
                    ):
                        commitment_values = tuple(
                            (
                                item.source_fragment,
                                item.normalized_meaning,
                                item.strength,
                            )
                            for item in materialization_plan.requirement_commitments
                        )
                        commitments = tuple(
                            RequirementDirectiveV1(
                                directive_id=(
                                    "reqdir_"
                                    + hashlib.sha256(
                                        (
                                            f"{materialization_plan.materialization_id}:"
                                            f"requirement:{index}"
                                        ).encode()
                                    ).hexdigest()[:32]
                                ),
                                source_kind="accepted_proposal",
                                source_turn_id=source_turn_id,
                                source_proposal_id=proposal_id,
                                source_node_id=(primary_node.node_id if primary_node else None),
                                source_text=source_text,
                                normalized_meaning=normalized_meaning,
                                scope_kind=("node" if node_ids else "global"),
                                target_node_ids=node_ids,
                                strength=strength,
                                created_revision_no=requirement_head.revision_no + 1,
                            )
                            for index, (
                                source_text,
                                normalized_meaning,
                                strength,
                            ) in enumerate(commitment_values)
                        )
                        canonical = canonicalize_requirement_directives(
                            requirement_head.ledger.active_directives,
                            commitments,
                        )
                        reconciliation = reconcile_character_occurrence_authority_in_transaction(
                            connection,
                            workflow_id=proposal.workflow_id,
                            current=requirement_head.ledger,
                            candidate=requirement_head.ledger.model_copy(
                                update={"active_directives": canonical.active_directives}
                            ),
                            occurrence_patches=_accepted_character_occurrence_patch(
                                requirement_head.ledger,
                                capability_id=proposal.capability_id,
                                occurrence_id=(
                                    materialization_plan.journey_event.occurrence_id
                                    if materialization_plan.journey_event is not None
                                    else None
                                ),
                                character_phase=(
                                    materialization_plan.journey_event.character_phase
                                    if materialization_plan.journey_event is not None
                                    else None
                                ),
                                title=selected_option.title,
                                public_summary=selected_option.public_summary,
                                revision_no=requirement_head.revision_no + 1,
                            ),
                            revision_no=requirement_head.revision_no + 1,
                            source=CharacterOccurrenceAuthoritySource(
                                source_kind="accepted_proposal",
                                source_text="Accepted Proposal requirement publication.",
                                source_turn_id=source_turn_id,
                                source_proposal_id=proposal_id,
                                source_node_id=(primary_node.node_id if primary_node else None),
                            ),
                            explicit_character_count=False,
                            explicit_character_presence=False,
                        )
                        requirement_revision = self._requirements.append_in_transaction(
                            connection,
                            workflow_id=proposal.workflow_id,
                            expected_revision_no=requirement_head.revision_no,
                            next_ledger=reconciliation.ledger,
                            source_kind="proposal_selection",
                            source_turn_id=source_turn_id,
                            source_proposal_id=proposal_id,
                            source_node_id=(primary_node.node_id if primary_node else None),
                            created_at=now,
                        )
                        if requirement_revision.revision_id != requirement_head.revision_id:
                            update_requirement_compatibility_projection_in_transaction(
                                connection,
                                proposal.workflow_id,
                                requirement_revision.ledger,
                                now,
                                advance_session_revision=False,
                            )
                            self._events.append_in_transaction(
                                connection,
                                V2EventInsert(
                                    workflow_id=proposal.workflow_id,
                                    turn_id=source_turn_id,
                                    node_id=(primary_node.node_id if primary_node else None),
                                    event_type="requirement_ledger_updated",
                                    created_at=now,
                                    payload={
                                        "revision_id": requirement_revision.revision_id,
                                        "revision_no": requirement_revision.revision_no,
                                        "digest": requirement_revision.digest,
                                        "source_kind": "proposal_selection",
                                        "source_proposal_id": proposal_id,
                                        "added_directive_ids": list(canonical.added_directive_ids),
                                        "superseded_directive_ids": list(
                                            canonical.superseded_directive_ids
                                        ),
                                        **reconciliation.delta.model_dump(mode="json"),
                                        "refresh": ["requirements"],
                                    },
                                ),
                            )
                    if fault_injector is not None:
                        fault_injector("requirements")
                    snapshot_id = (
                        snapshot_ids[primary_node.node_id] if primary_node is not None else None
                    )
                    if topic_id is None:
                        raise _error(
                            "guidance_topic_not_found",
                            "Proposal has no Guidance topic.",
                        )
                    topic = (
                        connection.execute(
                            select(AgentCanvasGuidanceTopicRow).where(
                                AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                                AgentCanvasGuidanceTopicRow.topic_id == topic_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if topic is None:
                        raise _error(
                            "guidance_topic_not_found",
                            "Guidance topic was not found.",
                        )
                    related_node_ids = tuple(
                        dict.fromkeys(
                            (
                                *json.loads(str(topic["related_node_ids_json"])),
                                *(item.node_id for item in nodes),
                            )
                        )
                    )
                    connection.execute(
                        update(AgentCanvasGuidanceTopicRow)
                        .where(
                            AgentCanvasGuidanceTopicRow.session_id == session["session_id"],
                            AgentCanvasGuidanceTopicRow.topic_id == topic_id,
                        )
                        .values(
                            status="selected",
                            source_proposal_id=proposal_id,
                            related_node_ids_json=_dump(list(related_node_ids)),
                            revision=int(topic["revision"]) + 1,
                            updated_at=now,
                        )
                    )
                    memory_row = (
                        connection.execute(
                            select(AgentCanvasCreativeMemoryRow).where(
                                AgentCanvasCreativeMemoryRow.workflow_id == workflow_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    memory = _creative_memory(memory_row, workflow_id)
                    approved_node_ids = dict(memory.approved_node_ids)
                    for bundle_node in nodes:
                        approved_node_ids[bundle_node.creative_role] = tuple(
                            dict.fromkeys(
                                (
                                    *approved_node_ids.get(bundle_node.creative_role, ()),
                                    bundle_node.node_id,
                                )
                            )
                        )
                    memory_revision = memory.memory_revision + 1
                    memory_values = _creative_memory_values(
                        memory.model_copy(update={"approved_node_ids": approved_node_ids}),
                        memory_revision,
                        created_at=(
                            str(memory_row["created_at"]) if memory_row is not None else now
                        ),
                        updated_at=now,
                    )
                    if memory_row is None:
                        connection.execute(
                            insert(AgentCanvasCreativeMemoryRow).values(**memory_values)
                        )
                    else:
                        connection.execute(
                            update(AgentCanvasCreativeMemoryRow)
                            .where(AgentCanvasCreativeMemoryRow.workflow_id == workflow_id)
                            .values(**memory_values)
                        )
                    proposal_values = {
                        "availability": "applied",
                        "updated_at": now,
                        "materialization_status": "completed",
                        "materialization_retryable": False,
                        "materialization_error_code": None,
                        "materialization_error_message": None,
                        "materialization_updated_at": now,
                    }
                    if materialization_plan.operation_kind == "derivative":
                        pass
                    else:
                        proposal_update_conditions = [
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id,
                            AgentCanvasConceptProposalRow.availability == persisted_availability,
                            AgentCanvasConceptProposalRow.materialization_id == materialization_id,
                        ]
                        proposal_update = connection.execute(
                            update(AgentCanvasConceptProposalRow)
                            .where(*proposal_update_conditions)
                            .values(**proposal_values)
                        )
                        if proposal_update.rowcount != 1:
                            raise _error(
                                "proposal_materialization_conflict",
                                "Materialization attempt is no longer current.",
                            )
                    if fault_injector is not None:
                        fault_injector("proposal")
                    next_session_revision = expected_session_revision + 1
                    session_values: dict[str, object] = {
                        "current_topic_id": None,
                        "active_proposal_id": None,
                        "revision": next_session_revision,
                        "updated_at": now,
                        "journey_state_json": next_journey.model_dump_json(),
                    }
                    session_update = connection.execute(
                        update(AgentCanvasGuidanceSessionRow)
                        .where(
                            AgentCanvasGuidanceSessionRow.session_id == session["session_id"],
                            AgentCanvasGuidanceSessionRow.revision == expected_session_revision,
                        )
                        .values(**session_values)
                    )
                    if session_update.rowcount != 1:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance state changed before Proposal materialization.",
                        )
                    if guided_submission is not None:
                        interaction_update = connection.execute(
                            update(AgentCanvasGuidedInteractionRow)
                            .where(
                                AgentCanvasGuidedInteractionRow.interaction_id
                                == guided_submission["interaction_id"],
                                AgentCanvasGuidedInteractionRow.status == "open",
                                AgentCanvasGuidedInteractionRow.revision
                                == guided_submission["interaction_revision"],
                            )
                            .values(
                                status="closed",
                                revision=guided_submission["interaction_revision"] + 1,
                                updated_at=now,
                            )
                        )
                        if interaction_update.rowcount != 1:
                            raise _error(
                                "guided_interaction_stale",
                                "Guided interaction changed before Materialization.",
                            )
                        connection.execute(
                            delete(AgentCanvasGuidanceAwaitingRow).where(
                                AgentCanvasGuidanceAwaitingRow.interaction_id
                                == guided_submission["interaction_id"]
                            )
                        )
                    if next_awaiting is not None:
                        connection.execute(
                            insert(AgentCanvasGuidanceAwaitingRow).values(
                                awaiting_id=next_awaiting.awaiting_id,
                                workflow_id=next_awaiting.workflow_id,
                                session_id=next_awaiting.session_id,
                                checkpoint_id=next_awaiting.checkpoint_id,
                                kind=next_awaiting.kind,
                                requires_user_action=next_awaiting.requires_user_action,
                                resume_policy=next_awaiting.resume_policy,
                                interaction_id=next_awaiting.interaction_id,
                                node_ids_json=_dump(list(next_awaiting.node_ids)),
                                stage=next_awaiting.stage,
                                stage_revision=next_awaiting.stage_revision,
                                created_at=next_awaiting.created_at.isoformat(),
                            )
                        )
                    if fault_injector is not None:
                        fault_injector("journey")
                    connection.execute(
                        update(AgentCanvasWorkflowRow)
                        .where(
                            AgentCanvasWorkflowRow.workflow_id == proposal.workflow_id,
                            AgentCanvasWorkflowRow.revision == expected_workflow_revision,
                        )
                        .values(
                            revision=expected_workflow_revision + 1,
                            updated_at=now,
                        )
                    )
                    if receipt is not None:
                        if (
                            receipt.workflow_id != workflow_id
                            or receipt.action_id != source_turn_id
                            or receipt.workflow_revision != expected_workflow_revision + 1
                        ):
                            raise _error(
                                "draft_publication_receipt_invalid",
                                "Draft publication receipt does not match the authoring transaction.",
                            )
                        connection.execute(
                            insert(AgentCanvasActionReceiptRow).values(
                                receipt_id=receipt.receipt_id,
                                workflow_id=receipt.workflow_id,
                                plan_id=None,
                                action_id=receipt.action_id,
                                proposal_id=receipt.proposal_id,
                                proposal_option_id=receipt.proposal_option_id,
                                proposal_action=receipt.proposal_action,
                                receipt_json=receipt.model_dump_json(),
                                created_at=now,
                            )
                        )
                        receipt_turn = _require_turn(
                            connection,
                            str(receipt.action_id),
                        )
                        response_locale = _guidance_response_locale(
                            connection,
                            receipt.workflow_id,
                        )
                        _append_timeline_entry(
                            connection,
                            conversation_id=str(receipt_turn["conversation_id"]),
                            workflow_id=receipt.workflow_id,
                            entry_type="action_receipt",
                            content=receipt.summary,
                            metadata=build_presentation_metadata(
                                message_key="draft.materialized",
                                message_args={
                                    "created_node_count": len(receipt.created_node_ids),
                                },
                                response_locale=response_locale,
                                presentation_key=f"receipt:{receipt.receipt_id}",
                                base={
                                    "action_receipt": receipt.model_dump(mode="json"),
                                },
                            ),
                            created_at=now,
                        )
                    if fault_injector is not None:
                        fault_injector("receipt")
                    if continuation is not None:
                        if source_turn_id != continuation.source_turn_id:
                            raise _error(
                                "continuation_context_invalid",
                                "Continuation source does not match the action transaction.",
                            )
                        event_turn = _require_turn(connection, continuation.source_turn_id)
                        self._conversations.insert_continuation_in_transaction(
                            connection,
                            workflow_id=workflow_id,
                            conversation_id=str(event_turn["conversation_id"]),
                            continuation=continuation,
                            now=now,
                        )
                    execution_mode = connection.execute(
                        select(AgentCanvasExecutionSettingsRow.media_execution_mode).where(
                            AgentCanvasExecutionSettingsRow.workflow_id == workflow_id
                        )
                    ).scalar_one_or_none()
                    automatic_run_command_ids: list[str] = []
                    storyboard_preparation_pending = (
                        materialization_plan.journey_event is not None
                        and materialization_plan.journey_event.event_type == "stage_materialized"
                        and materialization_plan.journey_event.storyboard_draft_preparation_queued
                    )
                    if execution_mode == "automatic" and not storyboard_preparation_pending:
                        for bundle_node in nodes:
                            if is_automatic_run_eligible_node_type(bundle_node.node_type):
                                command = self._automatic_runs.enqueue_in_transaction(
                                    connection,
                                    workflow_id=bundle_node.workflow_id,
                                    source_action_id=source_turn_id,
                                    node_id=bundle_node.node_id,
                                    now=datetime.fromisoformat(now),
                                )
                                automatic_run_command_ids.append(command.command_id)
                    event_turn = _require_turn(
                        connection,
                        source_turn_id,
                    )
                    stage_journey_event = (
                        materialization_plan.journey_event
                        if isinstance(
                            materialization_plan.journey_event,
                            StageMaterializedJourneyEventV1,
                        )
                        else None
                    )
                    action_owner = (
                        "targeted_authoring"
                        if current_journey.suspended_action is not None
                        else "quick_media"
                        if str(proposal_state["capability_id"]) == "quick_media"
                        else "guided_journey"
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=proposal.workflow_id,
                            node_id=(primary_node.node_id if primary_node else None),
                            conversation_id=str(event_turn["conversation_id"]),
                            turn_id=str(event_turn["turn_id"]),
                            action_id=source_turn_id,
                            event_type="proposal_action_applied",
                            created_at=now,
                            payload={
                                "proposal_id": proposal_id,
                                "option_id": option_id,
                                "selection_actor": selection_actor,
                                "proposal_action": proposal_action,
                                "session_revision": next_session_revision,
                                "node_id": (primary_node.node_id if primary_node else None),
                                "node_ids": list(node_ids),
                                "revision": expected_workflow_revision + 1,
                            },
                        ),
                    )
                    for bundle_node in nodes:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=bundle_node.workflow_id,
                                node_id=bundle_node.node_id,
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type="draft_node_created",
                                created_at=now,
                                payload={
                                    "node_type": bundle_node.node_type,
                                    "creative_role": bundle_node.creative_role,
                                    "occurrence_id": (
                                        stage_journey_event.occurrence_id
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "character_phase": (
                                        stage_journey_event.character_phase
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "action_owner": action_owner,
                                    "revision": expected_workflow_revision + 1,
                                    "refresh": ["workflow"],
                                },
                            ),
                        )
                    materialization_mode = (
                        primary_node.metadata.get("materialization_mode")
                        if primary_node is not None
                        else None
                    )
                    warning_code = (
                        primary_node.metadata.get("warning_code")
                        if primary_node is not None
                        else None
                    )
                    operation_policy_id = (
                        primary_node.metadata.get("operation_policy_id")
                        if primary_node is not None
                        else None
                    )
                    if primary_node is not None:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                node_id=primary_node.node_id,
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type="guided_draft_materialized",
                                created_at=now,
                                payload={
                                    "proposal_id": proposal_id,
                                    "option_id": option_id,
                                    "node_id": primary_node.node_id,
                                    "node_ids": list(node_ids),
                                    "creative_role": primary_node.creative_role,
                                    "occurrence_id": (
                                        stage_journey_event.occurrence_id
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "character_phase": (
                                        stage_journey_event.character_phase
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "action_owner": action_owner,
                                    "completion_mode": (
                                        materialization_mode
                                        if materialization_mode == "deterministic_fallback"
                                        else "agent"
                                    ),
                                    "warning_code": warning_code,
                                    "operation_policy_id": operation_policy_id,
                                    "refresh": ["workflow", "timeline"],
                                },
                            ),
                        )
                    normalization_mode = (
                        primary_node.metadata.get("normalization_mode")
                        if primary_node is not None
                        else None
                    )
                    if normalization_mode in {"repaired", "deterministic_fallback"}:
                        normalization_event = (
                            "materialization_prompt_repaired"
                            if normalization_mode == "repaired"
                            else "materialization_prompt_fallback_used"
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                node_id=(primary_node.node_id if primary_node else None),
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type=normalization_event,
                                created_at=now,
                                payload={
                                    "capability_id": str(proposal_state["capability_id"]),
                                    "node_id": (primary_node.node_id if primary_node else None),
                                    "violation_codes": (
                                        primary_node.metadata.get("normalization_warnings", [])
                                        if primary_node is not None
                                        else []
                                    ),
                                    "prompt_context_snapshot_id": snapshot_id,
                                    "result_digest": hashlib.sha256(
                                        (primary_node.generation_prompt or "").encode("utf-8")
                                        if primary_node is not None
                                        else b""
                                    ).hexdigest(),
                                },
                            ),
                        )
                    for binding in bindings:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                node_id=binding.target_node_id,
                                binding_id=binding.binding_id,
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type="binding_created",
                                created_at=now,
                                payload={
                                    "target_node_id": binding.target_node_id,
                                    "input_role": binding.input_role,
                                    "refresh": ["workflow"],
                                },
                            ),
                        )
                    if next_journey != current_journey:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                node_id=(primary_node.node_id if primary_node else None),
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type=(
                                    "journey_stage_changed"
                                    if next_journey.stage != current_journey.stage
                                    else "journey_stage_started"
                                ),
                                created_at=now,
                                payload={
                                    "previous_stage": current_journey.stage,
                                    "next_stage": next_journey.stage,
                                    "stage_revision": next_journey.stage_revision,
                                    "evidence_id": (
                                        materialization_plan.journey_event.evidence_id
                                        if materialization_plan.journey_event is not None
                                        else None
                                    ),
                                    "evidence_kind": (
                                        materialization_plan.journey_event.evidence_kind
                                        if materialization_plan.journey_event is not None
                                        and materialization_plan.journey_event.event_type
                                        == "stage_materialized"
                                        else "targeted_action_finished"
                                    ),
                                    "source_id": (
                                        materialization_plan.journey_event.source_id
                                        if materialization_plan.journey_event is not None
                                        else None
                                    ),
                                    "source_materialization_id": (
                                        materialization_plan.materialization_id
                                    ),
                                    "reason": None,
                                    "occurrence_id": (
                                        materialization_plan.journey_event.occurrence_id
                                        if materialization_plan.journey_event is not None
                                        and materialization_plan.journey_event.event_type
                                        == "stage_materialized"
                                        else None
                                    ),
                                    "character_phase": (
                                        stage_journey_event.character_phase
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "ledger_revision_id": (
                                        stage_journey_event.ledger_revision_id
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "receipt_id": (
                                        stage_journey_event.receipt_id
                                        if stage_journey_event is not None
                                        else None
                                    ),
                                    "action_owner": action_owner,
                                },
                            ),
                        )
                    if next_awaiting is not None:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=workflow_id,
                                node_id=(primary_node.node_id if primary_node else None),
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type="guidance_awaiting_entered",
                                transition_key=(
                                    f"guidance-awaiting:{next_awaiting.awaiting_id}:entered"
                                ),
                                created_at=now,
                                payload={
                                    "awaiting_id": next_awaiting.awaiting_id,
                                    "session_id": next_awaiting.session_id,
                                    "checkpoint_id": next_awaiting.checkpoint_id,
                                    "kind": next_awaiting.kind,
                                    "resume_policy": next_awaiting.resume_policy,
                                    "interaction_id": None,
                                    "node_ids": list(next_awaiting.node_ids),
                                },
                            ),
                        )
                    connection.execute(
                        update(AgentCanvasChatTurnRow)
                        .where(AgentCanvasChatTurnRow.turn_id == source_turn_id)
                        .values(
                            status="completed",
                            error_code=None,
                            error_message=None,
                            updated_at=now,
                        )
                    )
                    connection.execute(
                        update(AgentCanvasExpertActivityRow)
                        .where(AgentCanvasExpertActivityRow.turn_id == source_turn_id)
                        .values(status="completed", updated_at=now)
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            node_id=(primary_node.node_id if primary_node else None),
                            conversation_id=str(event_turn["conversation_id"]),
                            turn_id=source_turn_id,
                            action_id=source_turn_id,
                            event_type="proposal_materialization_completed",
                            transition_key=f"materialization:{materialization_id}:completed",
                            created_at=now,
                            payload={
                                "proposal_id": proposal_id,
                                "materialization_id": materialization_id,
                                "option_id": option_id,
                                "capability_id": str(proposal_state["capability_id"]),
                                "turn_id": source_turn_id,
                                "node_ids": list(node_ids),
                                "binding_ids": [binding.binding_id for binding in bindings],
                                **(
                                    {
                                        "occurrence_id": stage_journey_event.occurrence_id,
                                        "character_phase": stage_journey_event.character_phase,
                                        "ledger_revision_id": (
                                            stage_journey_event.ledger_revision_id
                                        ),
                                        "receipt_id": stage_journey_event.receipt_id,
                                        "action_owner": action_owner,
                                    }
                                    if stage_journey_event is not None
                                    and stage_journey_event.occurrence_id is not None
                                    else {}
                                ),
                            },
                        ),
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=workflow_id,
                            conversation_id=str(event_turn["conversation_id"]),
                            turn_id=str(event_turn["turn_id"]),
                            action_id=source_turn_id,
                            event_type="guidance_state_updated",
                            created_at=now,
                            payload={
                                "session_id": str(session["session_id"]),
                                "session_revision": next_session_revision,
                                "proposal_id": proposal_id,
                                "topic_id": topic_id,
                                "node_id": (primary_node.node_id if primary_node else None),
                                "node_ids": list(node_ids),
                            },
                        ),
                    )
                    if receipt is not None:
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=receipt.workflow_id,
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=str(event_turn["turn_id"]),
                                action_id=source_turn_id,
                                event_type="action_receipt_created",
                                created_at=now,
                                payload={
                                    "receipt_id": receipt.receipt_id,
                                    "revision": receipt.workflow_revision,
                                    "refresh": ["conversation", "workflow"],
                                },
                            ),
                        )
                    if primary_node is not None and primary_node.node_type == "script":
                        conversation_id = _ensure_conversation(
                            connection,
                            proposal.workflow_id,
                            now,
                        )
                        entry_id = f"artifact_{uuid4().hex}"
                        metadata = {
                            "script_node_id": primary_node.node_id,
                            "source_turn_id": source_turn_id,
                            "action_label": "View Script",
                        }
                        connection.execute(
                            insert(AgentCanvasChatEntryRow).values(
                                entry_id=entry_id,
                                conversation_id=conversation_id,
                                workflow_id=proposal.workflow_id,
                                sequence_no=_next_chat_sequence(
                                    connection,
                                    conversation_id,
                                ),
                                entry_type="script_artifact",
                                speaker=None,
                                content="Script ready",
                                metadata_json=_dump(metadata),
                                created_at=now,
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=proposal.workflow_id,
                                node_id=primary_node.node_id,
                                event_type="script_artifact_created",
                                created_at=now,
                                payload={"entry_id": entry_id, **metadata},
                            ),
                        )
                    if guided_submission is not None:
                        for event_type, payload in (
                            (
                                "guided_interaction_submitted",
                                {
                                    "interaction_id": guided_submission["interaction_id"],
                                    "submission_id": guided_submission["submission_id"],
                                    "proposal_id": proposal_id,
                                    "option_id": option_id,
                                },
                            ),
                            (
                                "guided_interaction_closed",
                                {
                                    "interaction_id": guided_submission["interaction_id"],
                                    "submission_id": guided_submission["submission_id"],
                                    "receipt_id": (
                                        receipt.receipt_id
                                        if receipt is not None
                                        else materialization_id
                                    ),
                                },
                            ),
                            (
                                "guidance_awaiting_resumed",
                                {
                                    "interaction_id": guided_submission["interaction_id"],
                                    "submission_id": guided_submission["submission_id"],
                                    "resume_evidence": "materialization_commit",
                                },
                            ),
                        ):
                            self._events.append_in_transaction(
                                connection,
                                V2EventInsert(
                                    workflow_id=workflow_id,
                                    node_id=(primary_node.node_id if primary_node else None),
                                    conversation_id=str(event_turn["conversation_id"]),
                                    turn_id=source_turn_id,
                                    action_id=guided_submission["interaction_id"],
                                    event_type=event_type,
                                    transition_key=(
                                        f"guided-submission:{guided_submission['submission_id']}:"
                                        f"{event_type}"
                                    ),
                                    created_at=now,
                                    payload=payload,
                                ),
                            )
                        events_cursor = int(
                            connection.execute(
                                select(func.coalesce(func.max(WorkflowEventRow.seq), 0)).where(
                                    WorkflowEventRow.workflow_id == workflow_id
                                )
                            ).scalar_one()
                        )
                        accepted_result = GuidedInteractionAcceptedV1(
                            workflow_id=workflow_id,
                            interaction_id=guided_submission["interaction_id"],
                            submission_id=guided_submission["submission_id"],
                            receipt_id=(
                                receipt.receipt_id if receipt is not None else materialization_id
                            ),
                            created_node_ids=tuple(item.node_id for item in nodes),
                            created_binding_ids=tuple(item.binding_id for item in bindings),
                            document_revisions={
                                item.document_id: item.after_revision for item in document_results
                            },
                            continuation_id=(
                                continuation.continuation_id if continuation is not None else None
                            ),
                            automatic_run_command_ids=tuple(automatic_run_command_ids),
                            resulting_session_revision=next_session_revision,
                            events_cursor=events_cursor,
                        )
                        connection.execute(
                            insert(AgentCanvasGuidedInteractionSubmissionRow).values(
                                submission_id=guided_submission["submission_id"],
                                workflow_id=workflow_id,
                                interaction_id=guided_submission["interaction_id"],
                                idempotency_key=guided_submission["idempotency_key"],
                                request_digest=guided_submission["request_digest"],
                                request_json=guided_submission["request_json"],
                                result_json=accepted_result.model_dump_json(),
                                created_at=now,
                            )
                        )
                    if fault_injector is not None:
                        fault_injector("event")
                    materialization_outcome = MaterializationOutcomeV1(
                        materialization_id=materialization_plan.materialization_id,
                        workflow_id=materialization_plan.workflow_id,
                        proposal_id=materialization_plan.proposal_id,
                        node_ids=tuple(item.node_id for item in nodes),
                        binding_ids=tuple(item.binding_id for item in bindings),
                        document_ids=tuple(
                            item.document_id for item in materialization_plan.document_writes
                        ),
                        document_results=tuple(document_results),
                        before_authority=_authority_snapshot(
                            workflow_revision=expected_workflow_revision,
                            guidance_revision=expected_session_revision,
                            requirement=requirement_head,
                            document_results=document_results,
                            document_kinds=document_kinds,
                            before=True,
                        ),
                        after_authority=_authority_snapshot(
                            workflow_revision=expected_workflow_revision + 1,
                            guidance_revision=next_session_revision,
                            requirement=requirement_revision,
                            document_results=document_results,
                            document_kinds=document_kinds,
                            before=False,
                        ),
                        prompt_preparation_ids=tuple(
                            item.operation_id for item in materialization_plan.prompt_preparations
                        ),
                        receipt_id=(receipt.receipt_id if receipt is not None else None),
                        workflow_revision=expected_workflow_revision + 1,
                        session_revision=next_session_revision,
                        journey_stage=next_journey.stage,
                        replayed=False,
                    )
                    connection.execute(
                        insert(AgentCanvasMaterializationCommitRow).values(
                            materialization_id=materialization_plan.materialization_id,
                            workflow_id=materialization_plan.workflow_id,
                            proposal_id=materialization_plan.proposal_id,
                            action_turn_id=materialization_plan.action_turn_id,
                            payload_digest=materialization_plan.payload_digest,
                            outcome_json=materialization_outcome.model_dump_json(),
                            created_at=now,
                        )
                    )
                    if fault_injector is not None:
                        fault_injector("commit_receipt")
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "agent_conversation_unavailable", "Conversation storage failed."
            ) from error
        if materialization_outcome is None:
            raise _error(
                "materialization_outcome_invalid",
                "Materialization transaction did not produce an outcome.",
            )
        return materialization_outcome

    def queue(
        self,
        envelope: MaterializationEnvelopeV1,
        *,
        max_attempts: int = 5,
        action_request: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> ProposalMaterializationProjectionV2:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        continuation_id = "continuation_" + _digest(envelope.materialization_id)[:32]
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    if action_request is not None:
                        if not idempotency_key:
                            raise _error(
                                "idempotency_key_required",
                                "Materialization action requires an idempotency key.",
                            )
                        request_json = json.dumps(
                            action_request,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        existing_turn = (
                            connection.execute(
                                select(AgentCanvasChatTurnRow).where(
                                    AgentCanvasChatTurnRow.idempotency_key == idempotency_key
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if existing_turn is None:
                            connection.execute(
                                insert(AgentCanvasChatTurnRow).values(
                                    turn_id=envelope.action_turn_id,
                                    conversation_id=envelope.conversation_id,
                                    workflow_id=envelope.workflow_id,
                                    turn_kind="proposal_action",
                                    status="queued",
                                    request_json=request_json,
                                    idempotency_key=idempotency_key,
                                    error_code=None,
                                    error_message=None,
                                    created_at=timestamp,
                                    updated_at=timestamp,
                                )
                            )
                            self._events.append_in_transaction(
                                connection,
                                V2EventInsert(
                                    workflow_id=envelope.workflow_id,
                                    conversation_id=envelope.conversation_id,
                                    turn_id=envelope.action_turn_id,
                                    event_type="agent_turn_queued",
                                    transition_key=(
                                        f"conversation:{envelope.action_turn_id}:queued"
                                    ),
                                    created_at=timestamp,
                                    payload={
                                        "turn_id": envelope.action_turn_id,
                                        "turn_kind": "proposal_action",
                                    },
                                ),
                            )
                        elif (
                            str(existing_turn["turn_id"]) != envelope.action_turn_id
                            or str(existing_turn["workflow_id"]) != envelope.workflow_id
                            or str(existing_turn["request_json"]) != request_json
                        ):
                            raise _error(
                                "idempotency_conflict",
                                "Idempotency key was reused.",
                            )
                    proposal = (
                        connection.execute(
                            select(AgentCanvasConceptProposalRow).where(
                                AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if proposal is None or str(proposal["workflow_id"]) != envelope.workflow_id:
                        raise _error("proposal_not_found", "Concept proposal was not found.")
                    existing_id = proposal["materialization_id"]
                    if existing_id is not None:
                        if str(existing_id) == envelope.materialization_id:
                            connection.commit()
                            return _projection(proposal)
                        if str(proposal["materialization_status"]) in {"queued", "working"}:
                            raise _error(
                                "proposal_materialization_conflict",
                                "Another Materialization attempt is active for this Proposal.",
                            )
                    allowed_availability = str(proposal["availability"]) == "open" or (
                        envelope.action == "reuse_direction"
                        and str(proposal["availability"]) == "superseded"
                    )
                    if not allowed_availability:
                        raise _error(
                            "proposal_action_stale",
                            "Concept proposal is not available for Materialization.",
                        )
                    if int(proposal["proposal_revision"]) != envelope.proposal_revision:
                        raise _error(
                            "proposal_action_stale",
                            "Concept proposal revision is stale.",
                        )
                    session_row = (
                        connection.execute(
                            select(AgentCanvasGuidanceSessionRow).where(
                                AgentCanvasGuidanceSessionRow.session_id
                                == proposal["guidance_session_id"]
                            )
                        )
                        .mappings()
                        .one()
                    )
                    if int(session_row["revision"]) != envelope.expected_session_revision:
                        raise _error(
                            "guidance_revision_conflict",
                            "Guidance session revision is stale.",
                        )
                    if envelope.capability_id == "character_design":
                        journey = parse_production_journey(str(session_row["journey_state_json"]))
                        active_action = journey.active_action
                        if (
                            journey.stage != "character"
                            or active_action is None
                            or journey.active_occurrence_id != envelope.occurrence_id
                            or active_action.occurrence_id != envelope.occurrence_id
                        ):
                            raise _error(
                                "character_occurrence_invalid",
                                "Character materialization does not own the current occurrence.",
                            )
                        if active_action.character_phase != envelope.character_phase:
                            raise _error(
                                "character_authoring_phase_invalid",
                                "Character materialization does not own the current phase.",
                            )
                        requirement = self._requirements.get_current_in_transaction(
                            connection,
                            envelope.workflow_id,
                        )
                        if (
                            requirement.revision_id != envelope.requirement_revision_id
                            or requirement.revision_no != envelope.requirement_revision_no
                        ):
                            raise _error(
                                "character_authoring_revision_stale",
                                "Character materialization uses an obsolete Requirement revision.",
                            )
                    if envelope.action != "custom_direction":
                        option_exists = connection.execute(
                            select(AgentCanvasConceptOptionRow.option_id).where(
                                AgentCanvasConceptOptionRow.proposal_id == envelope.proposal_id,
                                AgentCanvasConceptOptionRow.option_id
                                == envelope.selected_option.option_id,
                            )
                        ).scalar_one_or_none()
                        if option_exists is None:
                            raise _error(
                                "proposal_option_not_found",
                                "Concept option was not found.",
                            )
                    turn = (
                        connection.execute(
                            select(AgentCanvasChatTurnRow).where(
                                AgentCanvasChatTurnRow.turn_id == envelope.action_turn_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if turn is None or str(turn["workflow_id"]) != envelope.workflow_id:
                        raise _error(
                            "chat_turn_not_found",
                            "Materialization action turn was not found.",
                        )

                    self._envelopes.create_in_transaction(connection, envelope)
                    self._outbox.enqueue_in_transaction(
                        connection,
                        continuation_id=continuation_id,
                        workflow_id=envelope.workflow_id,
                        conversation_id=envelope.conversation_id,
                        source_turn_id=str(proposal["turn_id"]),
                        continuation_turn_id=envelope.action_turn_id,
                        operation="capability_materialization",
                        payload={
                            "schema_version": "1",
                            "envelope_id": envelope.envelope_id,
                            **(
                                {
                                    "occurrence_id": envelope.occurrence_id,
                                    "character_phase": envelope.character_phase,
                                    "action_owner": "guided_journey",
                                }
                                if envelope.capability_id == "character_design"
                                else {}
                            ),
                        },
                        max_attempts=max_attempts,
                        now=now,
                    )
                    connection.execute(
                        insert(AgentCanvasExpertActivityRow).values(
                            activity_id="activity_" + _digest(envelope.materialization_id)[:32],
                            turn_id=envelope.action_turn_id,
                            workflow_id=envelope.workflow_id,
                            capability_id=envelope.capability_id,
                            operation="capability_materialization",
                            status="working",
                            display_name="Capability Materialization",
                            error_code=None,
                            error_message=None,
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                    connection.execute(
                        update(AgentCanvasConceptProposalRow)
                        .where(AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id)
                        .values(
                            materialization_id=envelope.materialization_id,
                            materialization_option_id=envelope.selected_option.option_id,
                            materialization_turn_id=envelope.action_turn_id,
                            materialization_attempt_no=envelope.attempt_no,
                            materialization_status="queued",
                            materialization_retryable=True,
                            materialization_error_code=None,
                            materialization_error_message=None,
                            materialization_created_at=timestamp,
                            materialization_updated_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                    sequence_no = (
                        int(
                            connection.execute(
                                select(
                                    func.coalesce(func.max(AgentCanvasChatEntryRow.sequence_no), 0)
                                ).where(
                                    AgentCanvasChatEntryRow.conversation_id
                                    == envelope.conversation_id
                                )
                            ).scalar_one()
                        )
                        + 1
                    )
                    connection.execute(
                        insert(AgentCanvasChatEntryRow).values(
                            entry_id="entry_" + _digest(envelope.materialization_id)[:32],
                            conversation_id=envelope.conversation_id,
                            workflow_id=envelope.workflow_id,
                            sequence_no=sequence_no,
                            entry_type="planning_progress",
                            speaker="adcraft_video_agent",
                            content="The selected direction is being prepared as an editable Draft.",
                            metadata_json=json.dumps(
                                build_presentation_metadata(
                                    message_key="planning_progress.next_action",
                                    message_args={},
                                    response_locale=_guidance_response_locale(
                                        connection,
                                        envelope.workflow_id,
                                    ),
                                    presentation_key=(f"planning:{envelope.materialization_id}"),
                                    base={
                                        "proposal_id": envelope.proposal_id,
                                        "materialization_id": envelope.materialization_id,
                                        "option_id": envelope.selected_option.option_id,
                                        "capability_id": envelope.capability_id,
                                        "status": "queued",
                                    },
                                ),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            created_at=timestamp,
                        )
                    )
                    self._events.append_in_transaction(
                        connection,
                        V2EventInsert(
                            workflow_id=envelope.workflow_id,
                            conversation_id=envelope.conversation_id,
                            turn_id=envelope.action_turn_id,
                            action_id=envelope.action_turn_id,
                            event_type="proposal_materialization_queued",
                            created_at=timestamp,
                            payload={
                                "proposal_id": envelope.proposal_id,
                                "materialization_id": envelope.materialization_id,
                                "option_id": envelope.selected_option.option_id,
                                "capability_id": envelope.capability_id,
                                "turn_id": envelope.action_turn_id,
                                **(
                                    {
                                        "occurrence_id": envelope.occurrence_id,
                                        "character_phase": envelope.character_phase,
                                        "ledger_revision_id": envelope.requirement_revision_id,
                                        "action_owner": "guided_journey",
                                    }
                                    if envelope.capability_id == "character_design"
                                    else {}
                                ),
                            },
                        ),
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "capability_materialization_failed",
                "Materialization submission could not be persisted.",
            ) from error
        return self.get_projection(envelope.proposal_id)

    def queue_derivative(
        self,
        envelope: ProposalPublicationEnvelopeV1,
        *,
        source_turn_id: str,
        max_attempts: int = 5,
    ) -> ProposalPublicationEnvelopeV1:
        """Queue one parent-derived operation without republishing its Proposal."""

        if envelope.operation_kind != "derivative" or envelope.parent_snapshot is None:
            raise _error(
                "derivative_materialization_invalid",
                "Derivative queueing requires one parent snapshot.",
            )
        now = datetime.now(timezone.utc)
        continuation_id = "continuation_" + _digest(envelope.materialization_id)[:32]
        try:
            with self._database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    proposal = (
                        connection.execute(
                            select(AgentCanvasConceptProposalRow).where(
                                AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id,
                                AgentCanvasConceptProposalRow.workflow_id == envelope.workflow_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if proposal is None or str(proposal["availability"]) != "applied":
                        raise _error(
                            "parent_materialization_missing",
                            "The accepted parent materialization is not available.",
                        )
                    parent = (
                        connection.execute(
                            select(AgentCanvasNodeRow).where(
                                AgentCanvasNodeRow.node_id == envelope.parent_snapshot.node_id,
                                AgentCanvasNodeRow.workflow_id == envelope.workflow_id,
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    expected_role = (
                        "character"
                        if envelope.parent_snapshot.semantic_role == "character_main"
                        else "product"
                    )
                    prompt_preparation = (
                        json.loads(str(parent["prompt_preparation_json"]))
                        if parent is not None
                        else {}
                    )
                    expected_prompt_operation_id = (
                        envelope.parent_snapshot.prompt_preparation_operation_id
                    )
                    revision_matches = parent is not None and (
                        int(parent["revision"]) == envelope.parent_snapshot.node_revision
                        or (
                            expected_prompt_operation_id is not None
                            and int(parent["revision"]) > envelope.parent_snapshot.node_revision
                            and prompt_preparation.get("operation_id")
                            == expected_prompt_operation_id
                            and prompt_preparation.get("status") == "ready"
                        )
                    )
                    if (
                        parent is None
                        or not revision_matches
                        or str(parent["creative_role"]) != expected_role
                    ):
                        raise _error(
                            "parent_materialization_revision_stale",
                            "The parent Node no longer matches the derived operation.",
                        )
                    if envelope.capability_id == "character_design":
                        requirement = self._requirements.get_current_in_transaction(
                            connection,
                            envelope.workflow_id,
                        )
                        if (
                            requirement.revision_id != envelope.requirement_revision_id
                            or requirement.revision_no != envelope.requirement_revision_no
                        ):
                            raise _error(
                                "character_authoring_revision_stale",
                                "Character derivative uses an obsolete Requirement revision.",
                            )
                        parent_metadata = json.loads(str(parent["metadata_json"]))
                        if (
                            envelope.parent_snapshot.occurrence_id != envelope.occurrence_id
                            or parent_metadata.get("occurrence_id") != envelope.occurrence_id
                        ):
                            raise _error(
                                "character_parent_provenance_invalid",
                                "Character derivative parent occurrence does not match.",
                            )
                    persisted_envelope = self._envelopes.create_in_transaction(connection, envelope)
                    existing = (
                        connection.execute(
                            select(AgentCanvasContinuationOutboxRow).where(
                                AgentCanvasContinuationOutboxRow.continuation_id == continuation_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if existing is None:
                        event_turn = (
                            connection.execute(
                                select(AgentCanvasChatTurnRow).where(
                                    AgentCanvasChatTurnRow.turn_id == envelope.action_turn_id,
                                    AgentCanvasChatTurnRow.workflow_id == envelope.workflow_id,
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if event_turn is None:
                            raise _error(
                                "chat_turn_not_found",
                                "Derivative materialization Turn was not found.",
                            )
                        self._outbox.enqueue_in_transaction(
                            connection,
                            continuation_id=continuation_id,
                            workflow_id=envelope.workflow_id,
                            conversation_id=str(event_turn["conversation_id"]),
                            source_turn_id=source_turn_id,
                            continuation_turn_id=envelope.action_turn_id,
                            operation="capability_materialization",
                            payload={
                                "schema_version": "1",
                                "envelope_id": envelope.envelope_id,
                                **(
                                    {
                                        "occurrence_id": envelope.occurrence_id,
                                        "character_phase": envelope.character_phase,
                                        "action_owner": "guided_journey",
                                    }
                                    if envelope.capability_id == "character_design"
                                    else {}
                                ),
                            },
                            max_attempts=max_attempts,
                            now=now,
                        )
                        connection.execute(
                            insert(AgentCanvasExpertActivityRow).values(
                                activity_id="activity_" + _digest(envelope.materialization_id)[:32],
                                turn_id=envelope.action_turn_id,
                                workflow_id=envelope.workflow_id,
                                capability_id=envelope.capability_id,
                                operation="capability_materialization",
                                status="working",
                                display_name="Derived Capability Materialization",
                                error_code=None,
                                error_message=None,
                                created_at=now.isoformat(),
                                updated_at=now.isoformat(),
                            )
                        )
                        self._events.append_in_transaction(
                            connection,
                            V2EventInsert(
                                workflow_id=envelope.workflow_id,
                                conversation_id=str(event_turn["conversation_id"]),
                                turn_id=envelope.action_turn_id,
                                action_id=envelope.action_turn_id,
                                event_type="parent_derived_materialization_queued",
                                transition_key=f"materialization:{envelope.materialization_id}:queued",
                                created_at=now.isoformat(),
                                payload={
                                    "materialization_id": envelope.materialization_id,
                                    "parent_node_id": envelope.parent_snapshot.node_id,
                                    "parent_node_revision": envelope.parent_snapshot.node_revision,
                                    **(
                                        {
                                            "occurrence_id": envelope.occurrence_id,
                                            "character_phase": envelope.character_phase,
                                            "ledger_revision_id": (
                                                envelope.requirement_revision_id
                                            ),
                                            "action_owner": "guided_journey",
                                        }
                                        if envelope.capability_id == "character_design"
                                        else {}
                                    ),
                                    "derivative_role": envelope.derivative_intent.derivative_role
                                    if envelope.derivative_intent is not None
                                    else None,
                                },
                            ),
                        )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except V2PersistenceError:
            raise
        except (IntegrityError, SQLAlchemyError) as error:
            raise _error(
                "capability_materialization_failed",
                "Derived materialization submission could not be persisted.",
            ) from error
        if not isinstance(persisted_envelope, ProposalPublicationEnvelopeV1):
            raise _error(
                "capability_materialization_invalid",
                "Persisted derivative envelope has an invalid operation type.",
            )
        return persisted_envelope

    def mark_working(
        self,
        envelope: MaterializationEnvelopeV1,
    ) -> ProposalMaterializationProjectionV2:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._database.engine.begin() as connection:
                if envelope.operation_kind == "derivative":
                    proposal = (
                        connection.execute(
                            select(AgentCanvasConceptProposalRow).where(
                                AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id,
                                AgentCanvasConceptProposalRow.availability == "applied",
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if proposal is None:
                        raise _error(
                            "proposal_materialization_conflict",
                            "Parent materialization is not available for the derived operation.",
                        )
                else:
                    result = connection.execute(
                        update(AgentCanvasConceptProposalRow)
                        .where(
                            AgentCanvasConceptProposalRow.proposal_id == envelope.proposal_id,
                            AgentCanvasConceptProposalRow.materialization_id
                            == envelope.materialization_id,
                            AgentCanvasConceptProposalRow.materialization_status.in_(
                                ("queued", "working")
                            ),
                        )
                        .values(materialization_status="working", materialization_updated_at=now)
                    )
                    if result.rowcount != 1:
                        raise _error(
                            "proposal_materialization_conflict",
                            "Materialization attempt is no longer active.",
                        )
                connection.execute(
                    update(AgentCanvasChatTurnRow)
                    .where(AgentCanvasChatTurnRow.turn_id == envelope.action_turn_id)
                    .values(status="running", updated_at=now)
                )
                self._events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=envelope.workflow_id,
                        conversation_id=envelope.conversation_id,
                        turn_id=envelope.action_turn_id,
                        action_id=envelope.action_turn_id,
                        event_type="proposal_materialization_started",
                        transition_key=(f"materialization:{envelope.materialization_id}:started"),
                        created_at=now,
                        payload={
                            "proposal_id": envelope.proposal_id,
                            "materialization_id": envelope.materialization_id,
                            "option_id": envelope.selected_option.option_id,
                            "capability_id": envelope.capability_id,
                            "turn_id": envelope.action_turn_id,
                            **(
                                {
                                    "occurrence_id": envelope.occurrence_id,
                                    "character_phase": envelope.character_phase,
                                    "ledger_revision_id": envelope.requirement_revision_id,
                                    "action_owner": "guided_journey",
                                }
                                if envelope.capability_id == "character_design"
                                else {}
                            ),
                        },
                    ),
                )
        except V2PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise _error(
                "capability_materialization_failed",
                "Materialization state could not be updated.",
            ) from error
        return self.get_projection(envelope.proposal_id)

    def fail_for_turn(
        self,
        turn_id: str,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._database.engine.begin() as connection:
            proposal = (
                connection.execute(
                    select(AgentCanvasConceptProposalRow).where(
                        AgentCanvasConceptProposalRow.materialization_turn_id == turn_id,
                        AgentCanvasConceptProposalRow.materialization_status.in_(
                            ("queued", "working")
                        ),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if proposal is None:
                return False
            connection.execute(
                update(AgentCanvasConceptProposalRow)
                .where(AgentCanvasConceptProposalRow.proposal_id == proposal["proposal_id"])
                .values(
                    availability="open",
                    materialization_status="failed",
                    materialization_retryable=retryable,
                    materialization_error_code=error_code[:160],
                    materialization_error_message=error_message[:2_048],
                    materialization_updated_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(AgentCanvasChatTurnRow)
                .where(AgentCanvasChatTurnRow.turn_id == turn_id)
                .values(
                    status="failed",
                    error_code=error_code[:160],
                    error_message=error_message[:2_048],
                    updated_at=now,
                )
            )
            connection.execute(
                update(AgentCanvasExpertActivityRow)
                .where(AgentCanvasExpertActivityRow.turn_id == turn_id)
                .values(
                    status="failed",
                    error_code=error_code[:160],
                    error_message=error_message[:2_048],
                    updated_at=now,
                )
            )
            connection.execute(
                update(AgentCanvasContinuationOutboxRow)
                .where(
                    AgentCanvasContinuationOutboxRow.continuation_turn_id == turn_id,
                    AgentCanvasContinuationOutboxRow.operation == "capability_materialization",
                    AgentCanvasContinuationOutboxRow.status.in_(("queued", "retry_wait", "leased")),
                )
                .values(
                    status="failed",
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_code=error_code[:160],
                    last_error_message=error_message[:2_048],
                    updated_at=now,
                )
            )
            self._events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=str(proposal["workflow_id"]),
                    conversation_id=None,
                    turn_id=turn_id,
                    action_id=turn_id,
                    event_type="proposal_materialization_failed",
                    transition_key=(f"materialization:{proposal['materialization_id']}:failed"),
                    created_at=now,
                    payload={
                        "proposal_id": str(proposal["proposal_id"]),
                        "materialization_id": str(proposal["materialization_id"]),
                        "option_id": str(proposal["materialization_option_id"]),
                        "capability_id": str(proposal["capability_id"]),
                        "turn_id": turn_id,
                        "error_code": error_code[:160],
                        "retryable": retryable,
                    },
                ),
            )
        return True

    def get_projection(self, proposal_id: str) -> ProposalMaterializationProjectionV2:
        try:
            with self._database.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(AgentCanvasConceptProposalRow).where(
                            AgentCanvasConceptProposalRow.proposal_id == proposal_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except SQLAlchemyError as error:
            raise _error(
                "capability_materialization_failed",
                "Materialization state could not be loaded.",
            ) from error
        if row is None or row["materialization_id"] is None:
            raise _error("proposal_not_found", "Concept proposal was not found.")
        return _projection(row)

    def get_envelope(self, envelope_id: str) -> MaterializationEnvelopeV1:
        envelope = self._envelopes.get(envelope_id)
        if not isinstance(
            envelope,
            (CapabilityMaterializationEnvelopeV1, ProposalPublicationEnvelopeV1),
        ):
            raise _error(
                "capability_materialization_invalid",
                "Operation envelope is not a capability Materialization.",
            )
        return envelope

    def events_cursor(self, workflow_id: str) -> int:
        return self._events.max_seq(workflow_id)


def _materialization_document(row: Mapping[str, object]) -> AgentWorkingDocumentV2:
    return AgentWorkingDocumentRepository.validate_document_payload(
        {
            "document_id": row["document_id"],
            "workflow_id": row["workflow_id"],
            "guidance_session_id": row["guidance_session_id"],
            "kind": row["document_kind"],
            "title": row["title"],
            "revision": row["revision"],
            "content_schema_version": row["content_schema_version"],
            "content_digest": row["content_digest"],
            "content": json.loads(str(row["content_json"])),
            "created_by_agent_run_id": row["created_by_agent_run_id"],
            "updated_by_agent_run_id": row["updated_by_agent_run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _authority_snapshot(
    *,
    workflow_revision: int,
    guidance_revision: int,
    requirement: RequirementLedgerRevisionV1,
    document_results: list[MaterializationDocumentResultV1],
    document_kinds: dict[str, str],
    before: bool,
) -> MaterializationAuthoritySnapshotV1:
    revisions: dict[str, int | None] = {
        "anchor_registry": None,
        "storyboard_production_plan": None,
    }
    digests: dict[str, str | None] = {
        "anchor_registry": None,
        "storyboard_production_plan": None,
    }
    for result in document_results:
        kind = document_kinds[result.document_id]
        revisions[kind] = result.before_revision if before else result.after_revision
        digests[kind] = result.before_digest if before else result.after_digest
    return MaterializationAuthoritySnapshotV1(
        workflow_revision=workflow_revision,
        guidance_revision=guidance_revision,
        requirement_revision_id=requirement.revision_id,
        requirement_revision_no=requirement.revision_no,
        requirement_digest=requirement.digest,
        anchor_registry_revision=revisions["anchor_registry"],
        anchor_registry_digest=digests["anchor_registry"],
        storyboard_plan_revision=revisions["storyboard_production_plan"],
        storyboard_plan_digest=digests["storyboard_production_plan"],
    )


def _validate_authority_document_sources(
    connection: Connection,
    *,
    plan: MaterializationPlanV1,
    document: AgentWorkingDocumentV2,
) -> None:
    content = document.content
    if isinstance(content, AnchorRegistryContentV3):
        planned_node_ids = {node.node_id for node in plan.nodes}
        for anchor in content.anchors:
            source = anchor.source
            if isinstance(source, (AgentAnchorNodeSourceV3, AgentAnchorImageAssetVersionSourceV3)):
                _require_exact_materialization_node_source(
                    connection,
                    workflow_id=plan.workflow_id,
                    node_id=source.node_id,
                    node_revision=source.node_revision,
                    source_workflow_id=source.workflow_id,
                    allow_newer_revision=source.node_id not in planned_node_ids,
                )
                if not any(
                    evidence.node_revision == source.node_revision
                    for evidence in anchor.acceptance_evidence
                ):
                    raise _error(
                        "agent_anchor_acceptance_stale",
                        "Anchor acceptance does not match its source Node revision.",
                    )
            if isinstance(source, AgentAnchorImageAssetVersionSourceV3):
                asset_source = connection.execute(
                    select(
                        AssetVersionRow.asset_id,
                        AssetVersionRow.source_workflow_id,
                        AssetVersionRow.source_node_id,
                        AssetVersionRow.status,
                    ).where(AssetVersionRow.version_id == source.asset_version_id)
                ).one_or_none()
                if (
                    asset_source is None
                    or str(asset_source.asset_id) != source.asset_id
                    or str(asset_source.source_workflow_id) != plan.workflow_id
                    or str(asset_source.source_node_id) != source.node_id
                    or str(asset_source.status) != "ready"
                ):
                    raise _error(
                        "agent_anchor_source_invalid",
                        "Anchor Asset version is not an exact readable Workflow source.",
                    )
        return
    if isinstance(content, StoryboardProductionPlanContentV3):
        for planned_node in content.planned_nodes:
            _require_exact_materialization_node_source(
                connection,
                workflow_id=plan.workflow_id,
                node_id=planned_node.node_id,
                node_revision=planned_node.node_revision,
                source_workflow_id=plan.workflow_id,
                error_code="agent_storyboard_plan_invalid",
                allow_newer_revision=True,
            )
        if content.visual_anchor is not None:
            _require_exact_materialization_node_source(
                connection,
                workflow_id=plan.workflow_id,
                node_id=content.visual_anchor.node_id,
                node_revision=content.visual_anchor.node_revision,
                source_workflow_id=plan.workflow_id,
                error_code="agent_storyboard_plan_invalid",
            )


def _require_exact_materialization_node_source(
    connection: Connection,
    *,
    workflow_id: str,
    node_id: str,
    node_revision: int,
    source_workflow_id: str,
    error_code: str = "agent_anchor_source_invalid",
    allow_newer_revision: bool = False,
) -> None:
    persisted_revision = connection.execute(
        select(AgentCanvasNodeRow.revision).where(
            AgentCanvasNodeRow.workflow_id == workflow_id,
            AgentCanvasNodeRow.node_id == node_id,
        )
    ).scalar_one_or_none()
    revision_matches = persisted_revision == node_revision or (
        allow_newer_revision
        and persisted_revision is not None
        and persisted_revision > node_revision
    )
    if source_workflow_id != workflow_id or not revision_matches:
        raise _error(
            error_code,
            "Working document source does not match an exact Node revision in this Workflow.",
        )


def _append_authority_document_events(
    connection: Connection,
    *,
    events: EventRepository,
    before: AgentWorkingDocumentV2 | None,
    after: AgentWorkingDocumentV2,
    operation: str,
    receipt_id: str,
) -> None:
    affected_aliases = _affected_anchor_aliases(before, after)
    sequence_ids = _affected_sequence_ids(after)
    payload = {
        "session_id": after.guidance_session_id,
        "document_id": after.document_id,
        "previous_revision": before.revision if before is not None else None,
        "next_revision": after.revision,
        "content_digest": after.content_digest,
        "mutation_kind": operation,
        "receipt_id": receipt_id,
        "affected_aliases": list(affected_aliases),
        "sequence_ids": list(sequence_ids),
    }
    created_at = after.updated_at.isoformat()
    events.append_in_transaction(
        connection,
        V2EventInsert(
            workflow_id=after.workflow_id,
            event_type=(
                "agent_working_document_created"
                if before is None
                else "agent_working_document_updated"
            ),
            transition_key=f"authority-document:{after.document_id}:{after.revision}",
            created_at=created_at,
            payload=payload,
        ),
    )
    if isinstance(after.content, AnchorRegistryContentV3):
        before_by_alias = (
            {anchor.alias: anchor for anchor in before.content.anchors}
            if before is not None and isinstance(before.content, AnchorRegistryContentV3)
            else {}
        )
        for alias in affected_aliases:
            anchor = next(item for item in after.content.anchors if item.alias == alias)
            prior = before_by_alias.get(alias)
            event_type = None
            if anchor.lifecycle == "planned" and prior is None:
                event_type = "agent_anchor_planned"
            elif anchor.lifecycle == "active" and (prior is None or prior.lifecycle != "active"):
                event_type = "agent_anchor_activated"
            elif anchor.lifecycle == "retired" and (prior is None or prior.lifecycle != "retired"):
                event_type = "agent_anchor_retired"
            if event_type is not None:
                events.append_in_transaction(
                    connection,
                    V2EventInsert(
                        workflow_id=after.workflow_id,
                        event_type=event_type,
                        transition_key=(
                            f"authority-anchor:{after.document_id}:{after.revision}:{alias}"
                        ),
                        created_at=created_at,
                        payload=payload,
                    ),
                )
    elif isinstance(after.content, StoryboardProductionPlanContentV3):
        events.append_in_transaction(
            connection,
            V2EventInsert(
                workflow_id=after.workflow_id,
                event_type="storyboard_plan_revised",
                transition_key=f"storyboard-plan:{after.document_id}:{after.revision}",
                created_at=created_at,
                payload=payload,
            ),
        )
        before_anchor = (
            before.content.visual_anchor
            if before is not None and isinstance(before.content, StoryboardProductionPlanContentV3)
            else None
        )
        if after.content.visual_anchor is not None and after.content.visual_anchor != before_anchor:
            events.append_in_transaction(
                connection,
                V2EventInsert(
                    workflow_id=after.workflow_id,
                    event_type="storyboard_visual_anchor_frozen",
                    transition_key=(f"storyboard-anchor:{after.document_id}:{after.revision}"),
                    created_at=created_at,
                    payload=payload,
                ),
            )


def _affected_anchor_aliases(
    before: AgentWorkingDocumentV2 | None,
    after: AgentWorkingDocumentV2,
) -> tuple[str, ...]:
    if not isinstance(after.content, AnchorRegistryContentV3):
        return ()
    before_by_alias = (
        {anchor.alias: anchor for anchor in before.content.anchors}
        if before is not None and isinstance(before.content, AnchorRegistryContentV3)
        else {}
    )
    return tuple(
        anchor.alias
        for anchor in after.content.anchors
        if before_by_alias.get(anchor.alias) != anchor
    )


def _affected_sequence_ids(after: AgentWorkingDocumentV2) -> tuple[str, ...]:
    if not isinstance(after.content, StoryboardProductionPlanContentV3):
        return ()
    return tuple(segment.sequence_id for segment in after.content.segments)


def _insert_materialized_node(
    connection: Connection,
    *,
    node: CanvasNodeV2,
    bindings: tuple[CanvasBindingV2, ...],
    creative_direction_snapshot_id: str | None,
    skill_refs: tuple[dict[str, str], ...],
    now: str,
    prompt_dispatch: AgentCanvasPromptPreparationDispatchRepository | None = None,
    prompt_context: object | None = None,
) -> str:
    # Bind the Node operation identity to the exact immutable context that is
    # persisted in the dispatch envelope.  Without this digest, two
    # materializations with the same Node snapshot but different Stage
    # Authoring contexts reuse one operation identity while producing distinct
    # dispatch identities.
    context_payload: dict[str, object] | None = None
    context_digest: str | None = None
    if isinstance(prompt_context, (StageAuthoringContextV1, Mapping)):
        context_payload, context_digest = detached_context_payload(prompt_context)
    node = normalize_queued_node(
        node,
        bindings=bindings,
        context_digest=context_digest,
    )
    snapshot_id = node.prompt_context_snapshot_id or f"snapshot_{uuid4().hex}"
    connection.execute(
        insert(AgentCanvasNodeRow).values(
            node_id=node.node_id,
            workflow_id=node.workflow_id,
            node_type=node.node_type,
            creative_role=node.creative_role,
            role_contract_version=node.role_contract_version,
            title=node.title,
            status=node.status,
            execution_mode=node.execution_mode,
            summary_prompt=node.summary_prompt,
            generation_prompt=node.generation_prompt,
            structured_content_json=_dump(node.structured_content),
            model_selection_mode=node.model_selection_mode,
            model_ref=node.model_ref,
            parameters_json=_dump(node.parameters),
            metadata_json=_dump(node.metadata),
            parameter_provenance_json=_dump(
                {
                    field: provenance.model_dump(mode="json")
                    for field, provenance in node.parameter_provenance.items()
                }
            ),
            prompt_context_snapshot_id=snapshot_id,
            output_asset_id=node.output_asset_id,
            position_x=node.position.x,
            position_y=node.position.y,
            revision=node.revision,
            error_json=None,
            prompt_preparation_json=_dump(node.prompt_preparation.model_dump(mode="json")),
            created_at=node.created_at.isoformat(),
            updated_at=node.updated_at.isoformat(),
        )
    )
    for binding in bindings:
        connection.execute(
            insert(AgentCanvasBindingRow).values(
                binding_id=binding.binding_id,
                workflow_id=binding.workflow_id,
                source_kind=binding.source.kind,
                source_node_id=(
                    binding.source.source_node_id if binding.source.kind == "node_output" else None
                ),
                source_asset_id=(
                    binding.source.asset_id if binding.source.kind == "image_asset" else None
                ),
                source_asset_version_id=(
                    binding.source.source_asset_version_id
                    if binding.source.kind == "image_asset"
                    else None
                ),
                target_node_id=binding.target_node_id,
                input_role=binding.input_role,
                required=binding.required,
                enabled=binding.enabled,
                order_index=binding.order,
                label=binding.label,
                metadata_json=_dump(binding.metadata),
                created_at=binding.created_at.isoformat(),
                updated_at=binding.updated_at.isoformat(),
            )
        )
    connection.execute(
        insert(AgentCanvasPromptContextSnapshotRow).values(
            snapshot_id=snapshot_id,
            workflow_id=node.workflow_id,
            target_node_id=node.node_id,
            inputs_json=_dump(_materialization_text_snapshots(connection, bindings)),
            creative_direction_snapshot_id=creative_direction_snapshot_id,
            skill_refs_json=_dump(skill_refs),
            content_digest=hashlib.sha256(
                _dump(
                    {
                        "generation_prompt": node.generation_prompt,
                        "structured_content": node.structured_content,
                        "skill_refs": skill_refs,
                    }
                ).encode("utf-8")
            ).hexdigest(),
            created_at=now,
        )
    )
    if prompt_dispatch is not None:
        # The materialization plan carries an immutable context identity.  The
        # full StageAuthoringContext is supplied by the post-commit worker
        # loader; this durable envelope prevents an orphaned queued projection
        # while keeping the authoring transaction free of Agent calls.
        prompt_dispatch.ensure_for_node_in_transaction(
            connection,
            node,
            bindings=bindings,
            context=(
                context_payload
                if context_payload is not None
                else {
                    "workflow_id": node.workflow_id,
                    "node_id": node.node_id,
                    "context_snapshot_id": node.prompt_preparation.context_snapshot_id
                    or snapshot_id,
                    "materialization_snapshot_id": snapshot_id,
                }
            ),
            now=datetime.fromisoformat(now),
        )
    return snapshot_id


def _insert_materialization_document(
    connection: Connection,
    *,
    plan: MaterializationPlanV1,
    guidance_session_id: str,
    document_write: MaterializationDocumentWriteV1,
) -> None:
    if document_write.document_type != "agent_working_document":
        raise _error(
            "materialization_document_invalid",
            "Materialization document type is not supported.",
        )
    if document_write.payload is None:
        raise _error(
            "materialization_document_invalid",
            "Materialization document create payload is missing.",
        )
    document = AgentWorkingDocumentRepository.validate_document_payload(document_write.payload)
    if (
        document.document_id != document_write.document_id
        or document.workflow_id != plan.workflow_id
        or document.guidance_session_id != guidance_session_id
    ):
        raise _error(
            "materialization_document_invalid",
            "Materialization document scope is inconsistent.",
        )
    connection.execute(
        insert(AgentWorkingDocumentRow).values(
            document_id=document.document_id,
            workflow_id=document.workflow_id,
            guidance_session_id=document.guidance_session_id,
            document_kind=document.kind,
            title=document.title,
            revision=document.revision,
            content_schema_version=document.content_schema_version,
            content_digest=document.content_digest,
            content_json=_dump(document.content.model_dump(mode="json")),
            created_by_agent_run_id=document.created_by_agent_run_id,
            updated_by_agent_run_id=document.updated_by_agent_run_id,
            created_at=document.created_at.isoformat(),
            updated_at=document.updated_at.isoformat(),
        )
    )


def _materialization_text_snapshots(
    connection: Connection,
    bindings: tuple[CanvasBindingV2, ...],
) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    for binding in sorted(
        bindings,
        key=lambda item: (item.display_order, item.binding_id),
    ):
        if binding.input_role != "text_context" or binding.source.kind != "node_output":
            continue
        source = (
            connection.execute(
                select(AgentCanvasNodeRow).where(
                    AgentCanvasNodeRow.node_id == binding.source.node_id
                )
            )
            .mappings()
            .one()
        )
        structured_content = json.loads(str(source["structured_content_json"]))
        content = str(structured_content.get("content", ""))
        snapshot = ResolvedTextInputSnapshotV2(
            source_node_id=str(source["node_id"]),
            source_node_revision=int(source["revision"]),
            binding_kind="text_context",
            document_kind=("script" if str(source["node_type"]) == "script" else "text"),
            content=content[:16_000],
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_semantic_role=str(source["creative_role"]),
            binding_metadata=binding.metadata,
            source_structured_content=structured_content,
            binding_id=binding.binding_id,
            input_role="text_context",
            required=binding.required,
            display_order=binding.display_order,
        )
        snapshots.append(snapshot.model_dump(mode="json"))
    return snapshots


def _require_current_derivative_parent(
    connection: Connection,
    plan: MaterializationPlanV1,
) -> None:
    if plan.operation_kind != "derivative" or plan.parent_snapshot is None:
        return
    parent_snapshot = plan.parent_snapshot
    parent = (
        connection.execute(
            select(AgentCanvasNodeRow).where(
                AgentCanvasNodeRow.node_id == parent_snapshot.node_id,
                AgentCanvasNodeRow.workflow_id == plan.workflow_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if parent is None:
        raise _error(
            "parent_materialization_missing",
            "The derivative parent is not available in this Workflow.",
        )
    expected_role = "character" if parent_snapshot.semantic_role == "character_main" else "product"
    content = json.loads(str(parent["structured_content_json"]))
    expected_asset_kind = (
        content.get("character_asset_kind") == "identity_master"
        if expected_role == "character"
        else content.get("asset_kind") == "main"
    )
    if str(parent["creative_role"]) != expected_role or not expected_asset_kind:
        raise _error(
            "role_reference_mismatch",
            "The derivative parent does not match the authoritative role policy.",
        )
    prompt_preparation = json.loads(str(parent["prompt_preparation_json"]))
    prompt_operation_id = parent_snapshot.prompt_preparation_operation_id
    revision_matches = int(parent["revision"]) == parent_snapshot.node_revision or (
        prompt_operation_id is not None
        and int(parent["revision"]) > parent_snapshot.node_revision
        and prompt_preparation.get("operation_id") == prompt_operation_id
        and prompt_preparation.get("status") == "ready"
    )
    if not revision_matches:
        raise _error(
            "parent_materialization_revision_stale",
            "The derivative parent revision is stale.",
        )


def _guidance_response_locale(connection: Connection, workflow_id: str) -> str:
    value = connection.execute(
        select(AgentCanvasGuidanceSessionRow.response_locale).where(
            AgentCanvasGuidanceSessionRow.workflow_id == workflow_id
        )
    ).scalar_one_or_none()
    return ResponseLocaleResolverV1().resolve(str(value or "und"))


def _guided_submission_context(
    connection: Connection,
    *,
    source_turn_id: str,
    workflow_id: str,
    proposal_id: str,
    option_id: str,
    expected_session_revision: int,
) -> dict[str, object] | None:
    turn = _require_turn(connection, source_turn_id)
    turn_request = json.loads(str(turn["request_json"]))
    payload = turn_request.get("guided_submission")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise _error(
            "guided_interaction_incomplete",
            "Guided interaction submission snapshot is invalid.",
        )
    interaction_id = str(payload.get("interaction_id") or "")
    submission_id = str(payload.get("submission_id") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    if (
        not interaction_id
        or not submission_id
        or not idempotency_key
        or idempotency_key != str(turn["idempotency_key"])
    ):
        raise _error(
            "guided_interaction_incomplete",
            "Guided interaction submission identity is invalid.",
        )
    interaction = (
        connection.execute(
            select(AgentCanvasGuidedInteractionRow).where(
                AgentCanvasGuidedInteractionRow.interaction_id == interaction_id,
                AgentCanvasGuidedInteractionRow.workflow_id == workflow_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if interaction is None:
        raise _error(
            "guided_interaction_not_found",
            "Guided interaction was not found.",
        )
    request = TypeAdapter(GuidedInteractionSubmitRequestV1).validate_python(payload.get("request"))
    content = json.loads(str(interaction["content_json"]))
    if (
        str(interaction["status"]) != "open"
        or int(interaction["revision"]) != request.expected_interaction_revision
        or int(interaction["expected_session_revision"]) != request.expected_session_revision
        or request.expected_session_revision != expected_session_revision
    ):
        raise _error(
            "guided_interaction_stale",
            "Guided interaction changed before Materialization.",
        )
    if (
        not isinstance(request, GuidedConceptSubmitV2)
        or content.get("proposal_id") != proposal_id
        or (request.action == "select" and request.option_id != option_id)
    ):
        raise _error(
            "guided_interaction_option_invalid",
            "Guided interaction selection does not match Materialization.",
        )
    request_json = json.dumps(
        request.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "interaction_id": interaction_id,
        "interaction_revision": int(interaction["revision"]),
        "submission_id": submission_id,
        "idempotency_key": idempotency_key,
        "request_digest": hashlib.sha256(request_json.encode("utf-8")).hexdigest(),
        "request_json": request_json,
    }


def _projection(row) -> ProposalMaterializationProjectionV2:
    error = None
    if row["materialization_error_code"] is not None:
        error = {
            "code": str(row["materialization_error_code"]),
            "message": str(row["materialization_error_message"]),
        }
    return ProposalMaterializationProjectionV2(
        materialization_id=str(row["materialization_id"]),
        option_id=str(row["materialization_option_id"]),
        turn_id=str(row["materialization_turn_id"]),
        status=str(row["materialization_status"]),
        attempt_no=int(row["materialization_attempt_no"]),
        retryable=bool(row["materialization_retryable"]),
        error=error,
        created_at=str(row["materialization_created_at"]),
        updated_at=str(row["materialization_updated_at"]),
    )


def _accepted_character_occurrence_patch(
    ledger: RequirementLedgerV1,
    *,
    capability_id: str,
    occurrence_id: str | None,
    character_phase: str | None,
    title: str,
    public_summary: str,
    revision_no: int,
) -> tuple[CharacterOccurrenceV1, ...] | None:
    if capability_id != "character_design" or occurrence_id is None or character_phase != "main":
        return None
    target = next(
        (item for item in ledger.character_occurrences if item.occurrence_id == occurrence_id),
        None,
    )
    if target is None:
        raise _error(
            "character_occurrence_invalid",
            "Character Proposal occurrence authority was not found.",
        )
    return tuple(
        item
        if item.occurrence_id != occurrence_id
        else item.model_copy(
            update={
                "role": " ".join(title.split()),
                "identity_summary": " ".join(public_summary.split()),
                "source_revision_no": revision_no,
                "specification_state": "specified",
            }
        )
        for item in ledger.character_occurrences
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="capability_materialization_repository")
