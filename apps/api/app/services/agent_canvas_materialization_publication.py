"""Deterministic publication of one validated capability Materialization."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2, CanvasPositionV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_ad_media import StoryboardGridContentV2, StoryboardPanelV2
from app.schemas.agent_canvas_creative_session import (
    DraftReferenceIntentV2,
    SpecialistDraftV2,
)
from app.schemas.agent_canvas_production_journey import JourneyEvidenceV1
from app.schemas.agent_canvas_conversation import ContinuationCommitV2
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    MaterializationNormalizationV1,
    ProposalApplicationEnvelopeV1,
    QuickMediaMaterializationResultV1,
    StoryboardMaterializationResultV1,
    WorldSettingMaterializationResultV1,
)
from app.schemas.agent_canvas_world_setting import (
    WorldSettingAuthoringProvenanceV2,
    WorldSettingDocumentV2,
)
from app.services.agent_canvas_capability_policy import CapabilityPolicyService
from app.services.agent_canvas_production_journey_orchestration import (
    GuidedProductionJourneyService,
)
from app.services.agent_canvas_character_reference_pairs import CharacterReferencePairFactory
from app.services.agent_canvas_conversation import (
    GuidanceProposalActionService,
    VideoAgentGateway,
)
from app.services.agent_canvas_materialization_runtime import (
    materialization_context_from_state,
    validate_materialization_reference_snapshots,
)
from app.services.agent_canvas_materialization_normalizer import (
    CapabilityMaterializationNormalizer,
)
from app.services.agent_canvas_world_setting import WorldSettingPublicationCandidateV2
from app.services.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthoringService,
)
from app.services.agent_canvas_prompt_preparation import NodePromptPreparationService
from app.services.agent_canvas_stage_authoring import (
    FoundationDraftPublicationService,
    PersistedStageDraft,
    StageDraftPublicationService,
)
from app.services.agent_canvas_stage_authoring_context import (
    stage_authoring_context_from_materialization,
)


class CapabilityMaterializationPublicationService:
    """Compile platform-owned fields and publish one Materialization exactly once."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: AgentCanvasConversationRepository,
        materializer: GuidanceProposalActionService,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        clock: Callable[[], datetime] | None = None,
        storyboard_authoring: StoryboardSequenceAuthoringService | None = None,
        storyboard_gateway: VideoAgentGateway | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._materializer = materializer
        self._asset_resolver = asset_resolver
        self._policy = CapabilityPolicyService()
        self._journey = GuidedProductionJourneyService(conversations)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._storyboard_authoring = storyboard_authoring
        self._storyboard_gateway = storyboard_gateway

    def publish(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        result: BaseModel,
        lease_guard: Callable[[], None],
    ) -> str:
        if isinstance(result, CapabilityMaterializationContextV1):
            return self._publish_progressive_stage(envelope, result, lease_guard)
        existing = self._conversations.get_publication_receipt_for_action(envelope.action_turn_id)
        if existing is not None and existing.created_node_ids:
            self._record_journey_evidence(envelope)
            return existing.created_node_ids[0]
        lease_guard()
        if envelope.target_node_id is not None:
            try:
                target = self._workflows.get_node(
                    envelope.workflow_id,
                    envelope.target_node_id,
                )
            except V2PersistenceError as error:
                raise V2PersistenceError(
                    "proposal_target_revision_stale",
                    "The targeted Node is no longer available.",
                    stage="capability_materialization_publication",
                ) from error
            if target.revision != envelope.target_node_revision:
                raise V2PersistenceError(
                    "proposal_target_revision_stale",
                    "The targeted Node changed before Materialization publication.",
                    stage="capability_materialization_publication",
                )
        validate_materialization_reference_snapshots(
            envelope,
            workflows=self._workflows,
            asset_resolver=self._asset_resolver,
        )
        materialization_context = materialization_context_from_state(
            envelope,
            conversations=self._conversations,
            workflows=self._workflows,
            asset_resolver=self._asset_resolver,
        )
        normalization = (
            result
            if isinstance(result, MaterializationNormalizationV1)
            else CapabilityMaterializationNormalizer().normalize(
                capability_id=envelope.capability_id,
                result=result,
                context=materialization_context,
            )
        )
        normalized_result = normalization.result
        storyboard_plan_id: str | None = None
        storyboard_sequence_id: str | None = None
        if (
            envelope.capability_id == "storyboard_design"
            and self._storyboard_authoring is not None
            and self._storyboard_gateway is not None
        ):
            materialization_context = materialization_context.model_copy(
                update={
                    "capability_facts": {
                        **materialization_context.capability_facts,
                        "storyboard_segment_duration_seconds": 5,
                    }
                }
            )
            outline = self._storyboard_gateway.plan_storyboard_sequence_outline(
                materialization_context,
                request_identity=f"{envelope.materialization_id}:outline",
            )
            plan = self._storyboard_authoring.persist_outline(
                workflow_id=envelope.workflow_id,
                guidance_session_id=(
                    self._conversations.get_guidance_session(envelope.workflow_id).session_id
                ),
                agent_run_id=envelope.materialization_id,
                idempotency_key=f"{envelope.materialization_id}:outline",
                draft=outline,
            )
            storyboard_plan_id = plan.document_id
            storyboard_sequence_id = "sequence-1"
            segment_context = self._storyboard_authoring.build_segment_context(
                envelope.workflow_id,
                plan.document_id,
                storyboard_sequence_id,
                style_excerpt=str(materialization_context.style_projection)[:8_192],
            )
            segment = self._storyboard_gateway.materialize_storyboard_segment(
                segment_context,
                request_identity=f"{envelope.materialization_id}:{storyboard_sequence_id}",
            )
            plan = self._storyboard_authoring.persist_segment(
                workflow_id=envelope.workflow_id,
                plan_document_id=plan.document_id,
                sequence_id=storyboard_sequence_id,
                agent_run_id=envelope.materialization_id,
                idempotency_key=f"{envelope.materialization_id}:{storyboard_sequence_id}",
                draft=segment,
            )
            original = StoryboardMaterializationResultV1.model_validate(normalized_result)
            sequence = plan.content.segments[0]
            normalized_result = original.model_copy(
                update={
                    "title": f"{original.title} 1",
                    "summary_prompt": sequence.narrative_goal,
                    "generation_prompt": segment.generation_prompt,
                    "structured_content": StoryboardGridContentV2(
                        sequence_summary=sequence.narrative_goal,
                        narrative_goal=sequence.narrative_goal,
                        style=original.structured_content.style,
                        panels=tuple(
                            StoryboardPanelV2(
                                panel_index=row.panel_index,
                                beat=row.content_beat,
                                composition=row.camera_description,
                                camera=row.camera_description,
                                subject_action=row.content_beat,
                                continuity_from_previous=(
                                    sequence.start_state
                                    if row.panel_index == 1
                                    else "Continue the prior panel action."
                                ),
                            )
                            for row in segment.rows
                        ),
                    ),
                }
            )
        definition = self._policy.definition(envelope.capability_id)
        node_id = "node_" + _digest(envelope.materialization_id)[:32]
        current_session = self._conversations.get_guidance_session(envelope.workflow_id)
        continuation = (
            _next_action_continuation(envelope)
            if (
                envelope.target_node_id is not None
                or envelope.capability_id == "quick_media"
                or current_session.journey.suspended_action is not None
            )
            else None
        )
        if envelope.capability_id == "world_setting":
            typed = WorldSettingMaterializationResultV1.model_validate(normalized_result)
            now = self._clock()
            document = WorldSettingDocumentV2(
                content=typed.structured_content.content,
                core=typed.structured_content.core,
                authoring_provenance=WorldSettingAuthoringProvenanceV2(
                    source_proposal_id=envelope.proposal_id,
                    source_option_id=envelope.selected_option.option_id,
                    materialization_run_id=envelope.materialization_id,
                    style_skill_run_id=envelope.style_skill_run_id,
                    creative_direction_snapshot_id=(
                        self._conversations.get_proposal(
                            envelope.proposal_id
                        ).creative_direction_snapshot_id
                    ),
                ),
            )
            node = CanvasNodeV2(
                node_id=node_id,
                workflow_id=envelope.workflow_id,
                node_type="text",
                creative_role="world_setting",
                title=typed.title,
                status="ready",
                summary_prompt=typed.summary_prompt,
                structured_content=document.model_dump(mode="json"),
                position=CanvasPositionV2(x=0, y=0),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            published = self._materializer.publish_world_setting(
                envelope.proposal_id,
                option_id=envelope.selected_option.option_id,
                candidate=WorldSettingPublicationCandidateV2(
                    node=node,
                    materialization_run_id=envelope.materialization_id,
                ),
                expected_session_revision=envelope.expected_session_revision,
                proposal_action=envelope.action,
                selection_actor=envelope.selection_actor,
                source_turn_id=envelope.action_turn_id,
                continuation=continuation,
                materialization_id=envelope.materialization_id,
            )
            self._record_journey_evidence(envelope)
            return published.node_id
        if envelope.capability_id == "character_design":
            pair = CharacterReferencePairFactory().build(
                envelope=envelope,
                normalization=normalization,
            )
            lease_guard()
            try:
                nodes = self._materializer.materialize_bundle(
                    envelope.proposal_id,
                    option_id=envelope.selected_option.option_id,
                    drafts=(pair.main_draft, pair.turnaround_draft),
                    internal_bindings=(pair.internal_binding,),
                    expected_session_revision=envelope.expected_session_revision,
                    proposal_action=envelope.action,
                    selection_actor=envelope.selection_actor,
                    source_turn_id=envelope.action_turn_id,
                    continuation=continuation,
                    deterministic_node_ids=(pair.main_node_id, pair.turnaround_node_id),
                    deterministic_binding_id=lambda index: (
                        "binding_"
                        + _digest(f"{envelope.materialization_id}:reference:{index}")[:32]
                    ),
                    materialization_id=envelope.materialization_id,
                )
            except V2PersistenceError as error:
                raise V2PersistenceError(
                    "character_pair_publication_failed",
                    "Character reference pair publication failed atomically.",
                    stage="capability_materialization_publication",
                ) from error
            except Exception as error:
                raise V2PersistenceError(
                    "character_pair_publication_failed",
                    "Character reference pair publication failed atomically.",
                    stage="capability_materialization_publication",
                ) from error
            self._record_journey_evidence(envelope)
            return nodes[0].node_id
        if envelope.capability_id == "quick_media":
            quick_media = QuickMediaMaterializationResultV1.model_validate(normalized_result)
            node_type = quick_media.structured_content.media_type
            creative_role = {
                "image": "general_image",
                "video": "general_video",
                "audio": "general_audio",
            }[node_type]
        else:
            if definition.node_type is None or definition.creative_role is None:
                raise V2PersistenceError(
                    "capability_policy_invalid",
                    "Capability does not define a publishable Node role.",
                    stage="capability_materialization_publication",
                )
            node_type = definition.node_type
            creative_role = definition.creative_role
        structured = getattr(normalized_result, "structured_content")
        references = tuple(
            DraftReferenceIntentV2.model_validate(
                reference.model_dump(
                    include={
                        "source_kind",
                        "source_id",
                        "binding_kind",
                        "input_role",
                        "required",
                        "display_order",
                        "semantic_reference_role",
                    }
                )
            )
            for reference in envelope.reference_plan.references
        )
        draft = SpecialistDraftV2(
            title=str(getattr(normalized_result, "title")),
            node_type=node_type,
            creative_role=creative_role,
            summary_prompt=str(getattr(normalized_result, "summary_prompt")),
            generation_prompt=getattr(normalized_result, "generation_prompt", None),
            structured_content=structured.model_dump(mode="json"),
            parameters={
                **normalization.parameters,
                "normalization_mode": normalization.mode,
                "normalization_warnings": list(normalization.warnings),
            },
            parameter_provenance=normalization.parameter_provenance,
            prompt_context_snapshot_id=envelope.context_snapshot_id,
            reference_intents=references,
        )
        lease_guard()
        node = self._materializer.materialize(
            envelope.proposal_id,
            option_id=envelope.selected_option.option_id,
            draft=draft,
            expected_session_revision=envelope.expected_session_revision,
            proposal_action=envelope.action,
            selection_actor=envelope.selection_actor,
            source_turn_id=envelope.action_turn_id,
            continuation=continuation,
            deterministic_node_id=node_id,
            deterministic_binding_id=lambda index: (
                "binding_" + _digest(f"{envelope.materialization_id}:{index}")[:32]
            ),
            materialization_id=envelope.materialization_id,
        )
        if storyboard_plan_id is not None and storyboard_sequence_id is not None:
            self._storyboard_authoring.attach_grid_node(
                workflow_id=envelope.workflow_id,
                plan_document_id=storyboard_plan_id,
                sequence_id=storyboard_sequence_id,
                node_id=node.node_id,
                agent_run_id=envelope.materialization_id,
                idempotency_key=f"{envelope.materialization_id}:attach:{storyboard_sequence_id}",
            )
        self._record_journey_evidence(envelope)
        return node.node_id

    def _publish_progressive_stage(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
        lease_guard: Callable[[], None],
    ) -> str:
        if not hasattr(envelope, "idempotency_identity"):
            raise V2PersistenceError(
                "stage_content_mismatch",
                "Progressive stage publication requires a concise Proposal envelope.",
                stage="capability_materialization_publication",
            )
        plan = FoundationDraftPublicationService().build(
            envelope,
            context,
            now=self._clock(),
        )
        prompt_service = NodePromptPreparationService(self._workflows)
        session = self._conversations.get_guidance_session(envelope.workflow_id)
        stage_context = stage_authoring_context_from_materialization(
            context,
            session_id=session.session_id,
            session_revision=session.revision,
            stage=session.journey.stage,
            foundation_item_id=(
                session.journey.active_action.foundation_item_id
                if session.journey.active_action is not None
                else None
            ),
            references=envelope.reference_plan.references,
        )

        def publish_bundle(_selection) -> tuple[PersistedStageDraft, ...]:
            existing = self._conversations.get_publication_receipt_for_action(
                envelope.action_turn_id
            )
            if existing is None:
                lease_guard()
                nodes = self._materializer.materialize_bundle(
                    envelope.proposal_id,
                    option_id=envelope.selected_option.option_id,
                    drafts=plan.drafts,
                    internal_bindings=plan.internal_bindings,
                    expected_session_revision=envelope.expected_session_revision,
                    proposal_action=envelope.action,
                    selection_actor=envelope.selection_actor,
                    source_turn_id=envelope.action_turn_id,
                    deterministic_node_ids=plan.node_ids,
                    deterministic_binding_id=lambda index: (
                        "binding_"
                        + _digest(f"{envelope.materialization_id}:reference:{index}")[:32]
                    ),
                    materialization_id=envelope.materialization_id,
                    queued_prompt_preparation=True,
                )
                node_ids = tuple(node.node_id for node in nodes)
                binding_ids = tuple(binding.binding_id for binding in plan.internal_bindings)
            else:
                node_ids = existing.created_node_ids
                binding_ids = existing.created_binding_ids
            published: list[PersistedStageDraft] = []
            for node_id in node_ids:
                node = self._workflows.get_node(envelope.workflow_id, node_id)
                published.append(
                    PersistedStageDraft(
                        node_id=node_id,
                        binding_ids=binding_ids,
                        prompt_preparation_id=(
                            node.prompt_preparation.operation_id
                            or "prompt_" + _digest(f"{envelope.materialization_id}:{node_id}")[:32]
                        ),
                        enqueue_required=node.prompt_preparation.status != "ready",
                    )
                )
            self._record_journey_evidence(envelope)
            return tuple(published)

        preparation_errors: list[Exception] = []

        def prepare(item: PersistedStageDraft) -> None:
            lease_guard()
            try:
                prompt_service.prepare(
                    envelope.workflow_id,
                    item.node_id,
                    operation_id=item.prompt_preparation_id,
                    context=stage_context,
                )
            except Exception as error:  # noqa: BLE001 - preserve sibling preparation.
                preparation_errors.append(error)

        result = StageDraftPublicationService(
            publish_bundle=publish_bundle,
            enqueue_prompt_preparation=prepare,
        ).publish_selection(plan.selection)
        if preparation_errors:
            raise V2PersistenceError(
                "prompt_preparation_failed",
                "One or more Draft prompts could not be prepared.",
                stage="capability_materialization_publication",
                details={"retryable": True},
            ) from preparation_errors[0]
        return result.created_node_ids[0]

    def _record_journey_evidence(self, envelope: ProposalApplicationEnvelopeV1) -> None:
        session = self._conversations.get_guidance_session(envelope.workflow_id)
        if session.journey.suspended_action is not None:
            suspended = session.journey.suspended_action
            self._journey.apply_evidence(
                envelope.workflow_id,
                evidence=JourneyEvidenceV1(
                    evidence_id=f"targeted-finish:{envelope.materialization_id}",
                    evidence_kind="targeted_action_finished",
                    source_id=envelope.materialization_id,
                    action_id=suspended.action_id,
                ),
                expected_session_revision=session.revision,
                idempotency_key=f"targeted-finish:{envelope.materialization_id}",
            )
            return
        if envelope.capability_id == "quick_media":
            return
        action = session.journey.active_action
        if action is None:
            return
        evidence_kind_by_stage = {
            "world_setting": "world_setting_selected",
            "narrative_direction": "narrative_direction_selected",
            "storyboard_plan": "storyboard_plan_accepted",
            "storyboard_grids": "storyboard_grids_prepared",
            "video_segments": "video_segments_prepared",
            "bgm": "bgm_prepared",
        }
        foundation_item_id = None
        if session.journey.stage == "foundation_design":
            evidence_kind = "foundation_item_selected"
            foundation_item_id = action.foundation_item_id
        else:
            evidence_kind = evidence_kind_by_stage.get(session.journey.stage)
        if evidence_kind is None:
            return
        self._journey.apply_evidence(
            envelope.workflow_id,
            evidence=JourneyEvidenceV1(
                evidence_id=f"materialization:{envelope.materialization_id}",
                evidence_kind=evidence_kind,
                source_id=envelope.materialization_id,
                foundation_item_id=foundation_item_id,
            ),
            expected_session_revision=session.revision,
            idempotency_key=f"materialization:{envelope.materialization_id}",
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _next_action_continuation(
    envelope: ProposalApplicationEnvelopeV1,
) -> ContinuationCommitV2:
    digest = _digest(f"materialization-next-action:{envelope.materialization_id}")
    return ContinuationCommitV2(
        continuation_id=f"continuation_{digest[:24]}",
        continuation_turn_id=f"turn_{digest[24:56]}",
        source_turn_id=envelope.action_turn_id,
        source_action_id=envelope.action_turn_id,
        idempotency_key=f"materialization-next-action:{envelope.materialization_id}",
        video_skill_run_id=envelope.style_skill_run_id,
    )
