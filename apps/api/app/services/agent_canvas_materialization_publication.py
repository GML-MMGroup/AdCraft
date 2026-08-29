"""Deterministic publication of one validated capability Materialization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel, ValidationError

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
)
from app.persistence.agent_canvas_execution_settings_repository import (
    AgentCanvasExecutionSettingsRepository,
)
from app.persistence.agent_canvas_storyboard_prompt_ready_promotion_repository import (
    StoryboardPromptReadyPromotionRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_ad_media import (
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VisualStyleContractV2,
)
from app.schemas.agent_canvas_production_journey import JourneyStageV2
from app.schemas.agent_canvas_storyboard_sequences import (
    StoryboardSegmentMaterializationDraftV2,
)
from app.schemas.agent_canvas_materialization import (
    CapabilityMaterializationContextV1,
    MaterializationNormalizationV1,
    ProposalApplicationEnvelopeV1,
    StoryboardMaterializationResultV1,
)
from app.schemas.agent_canvas_materialization_commit import (
    MaterializationAuthoringSnapshotV1,
    MaterializationDocumentWriteV1,
)
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.v2_persistence import V2EventInsert
from app.schemas.agent_working_documents import (
    AgentAnchorRoleSourceV3,
    AgentAnchorNodeSourceV3,
    AgentAnchorSkillSnapshotSourceV3,
    AgentAnchorV3,
    AgentDocumentMutationPlanV3,
    AgentWorkingDocumentV2,
    AnchorAcceptanceEvidenceV1,
    AnchorRegistryContentV3,
    StoryboardPlannedNodeV3,
    StoryboardNarrativeSegmentV2,
    StoryboardPlanGlobalParametersV2,
    StoryboardProductionPlanContentV3,
    StoryboardSegmentMaterializationV3,
)
from app.services.agent_canvas_conversation import (
    VideoAgentGateway,
)
from app.services.agent_canvas_guided_duration import GuidedDurationAuthorityPolicy
from app.services.agent_canvas_materialization_runtime import (
    materialization_context_from_state,
    validate_materialization_reference_snapshots,
)
from app.services.agent_canvas_materialization_normalizer import (
    CapabilityMaterializationNormalizer,
)
from app.services.agent_canvas_parent_derived_materialization import (
    ParentDerivedMaterializationCoordinator,
)
from app.services.agent_canvas_materialization_commit import (
    AgentCanvasMaterializationCommitService,
)
from app.services.agent_canvas_materialization_plan import (
    CapabilityMaterializationPlanCompiler,
)
from app.services.agent_canvas_production_journey_reducer import (
    GuidedProductionJourneyReducer,
)
from app.services.agent_canvas_storyboard_sequences import (
    StoryboardSequenceAuthoringService,
)
from app.services.agent_canvas_capability_draft_bundle import (
    stage_definitions,
    stage_draft_parameters,
    stage_draft_title,
)
from app.services.agent_canvas_prompt_preparation import (
    NodePromptPreparationService,
    context_digest,
)
from app.services.agent_canvas_prompt_assertion_policy import (
    current_source_snapshots_for_evidence,
)
from app.services.agent_canvas_storyboard_prompt_ready_promotion import (
    StoryboardPromptReadyPromotionService,
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
        commit_service: AgentCanvasMaterializationCommitService | None = None,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2] | None = None,
        storyboard_authoring: StoryboardSequenceAuthoringService | None = None,
        storyboard_gateway: VideoAgentGateway | None = None,
        storyboard_promotion: StoryboardPromptReadyPromotionService | None = None,
        prompt_ready_activation: Callable[..., object] | None = None,
        parent_derived: ParentDerivedMaterializationCoordinator | None = None,
        prompt_dispatch: AgentCanvasPromptPreparationDispatchRepository | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        materialization_repository = AgentCanvasMaterializationRepository(
            workflows.database,
            conversations.events,
        )
        self._commit_service = commit_service or AgentCanvasMaterializationCommitService(
            materialization_repository,
            GuidedProductionJourneyReducer(),
        )
        self._prompt_dispatch = prompt_dispatch or AgentCanvasPromptPreparationDispatchRepository(
            workflows.database,
            conversations.events,
        )
        self._parent_derived = parent_derived or ParentDerivedMaterializationCoordinator(
            workflows=workflows,
            conversations=conversations,
            materializations=materialization_repository,
        )
        self._plan_compiler = CapabilityMaterializationPlanCompiler()
        self._asset_resolver = asset_resolver
        self._storyboard_authoring = storyboard_authoring
        self._storyboard_gateway = storyboard_gateway
        self._working_documents = AgentWorkingDocumentRepository(
            workflows.database,
            conversations.events,
        )
        self._requirements = AgentCanvasRequirementRepository(workflows.database)
        self._duration_authority = GuidedDurationAuthorityPolicy()
        self._prompt_ready_activation = prompt_ready_activation
        self._storyboard_promotion = storyboard_promotion or (
            StoryboardPromptReadyPromotionService(
                workflows,
                conversations,
                StoryboardPromptReadyPromotionRepository(
                    workflows.database,
                    conversations.events,
                ),
                self._working_documents,
                AgentCanvasExecutionSettingsRepository(
                    workflows.database,
                    conversations.events,
                ),
            )
        )

    def publish(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        result: BaseModel,
        lease_guard: Callable[[], None],
    ) -> str | None:
        recovered = self.resume_committed(envelope, lease_guard)
        if recovered is not None:
            return recovered

        lease_guard()
        self._validate_target(envelope)
        validate_materialization_reference_snapshots(
            envelope,
            workflows=self._workflows,
            asset_resolver=self._asset_resolver,
        )
        materialization_context = (
            result
            if isinstance(result, CapabilityMaterializationContextV1)
            else materialization_context_from_state(
                envelope,
                conversations=self._conversations,
                workflows=self._workflows,
                asset_resolver=self._asset_resolver,
            )
        )
        if isinstance(result, CapabilityMaterializationContextV1):
            normalization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1 = (
                self._storyboard_normalization(envelope, result)
                if envelope.capability_id == "storyboard_design"
                else result
            )
        elif isinstance(result, MaterializationNormalizationV1):
            normalization = result
        else:
            normalization = CapabilityMaterializationNormalizer().normalize(
                capability_id=envelope.capability_id,
                result=result,
                context=materialization_context,
            )

        session = self._conversations.get_guidance_session(envelope.workflow_id)
        authority_documents: tuple[MaterializationDocumentWriteV1, ...] = ()
        if isinstance(normalization, MaterializationNormalizationV1):
            normalization, authority_documents = self._prepare_storyboard(
                envelope,
                normalization,
                materialization_context,
                session.session_id,
            )
        authority_documents += self._prepare_guided_document_stage(
            envelope,
            normalization,
            materialization_context,
            session.session_id,
        )
        preview_bundle = self._plan_compiler.compile_draft_bundle(envelope, normalization)
        authority_documents += self._prepare_bgm_plan(
            envelope,
            session.session_id,
            preview_bundle.nodes,
        )
        authority_documents += self._prepare_anchor_registry(
            envelope,
            session.session_id,
            preview_bundle.nodes,
        )
        workflow = self._workflows.get_workflow(envelope.workflow_id)
        frozen_prompt_context = stage_authoring_context_from_materialization(
            materialization_context,
            session_id=session.session_id,
            session_revision=session.revision,
            stage=session.journey.stage,
            occurrence_id=(
                envelope.occurrence_id
                or (
                    session.journey.active_action.occurrence_id
                    if session.journey.active_action is not None
                    else None
                )
            ),
            references=envelope.reference_plan.references,
        )
        plan = self._plan_compiler.compile(
            envelope,
            normalization,
            snapshot=MaterializationAuthoringSnapshotV1(
                workflow_revision=workflow.revision,
                session_revision=session.revision,
                proposal_revision=envelope.proposal_revision,
                target_node_revision=envelope.target_node_revision,
                current_journey=session.journey,
            ),
            storyboard_documents=authority_documents,
            prompt_context=frozen_prompt_context,
        )
        lease_guard()
        try:
            outcome = self._commit_service.commit(plan)
        except Exception as error:
            if envelope.capability_id != "character_design":
                raise
            raise V2PersistenceError(
                "character_pair_publication_failed",
                "Character reference pair publication failed atomically.",
                stage="capability_materialization_publication",
            ) from error
        if envelope.operation_kind == "parent" and envelope.capability_id == "character_design":
            self._parent_derived.reconcile_after_parent(envelope, lease_guard=lease_guard)
        self._prepare_prompts(
            envelope,
            materialization_context,
            session_id=session.session_id,
            session_revision=session.revision,
            stage=session.journey.stage,
            occurrence_id=(
                session.journey.active_action.occurrence_id
                if session.journey.active_action is not None
                else None
            ),
            node_ids=outcome.node_ids,
            operation_ids=outcome.prompt_preparation_ids,
            lease_guard=lease_guard,
        )
        self._prepare_storyboard_dependencies(
            envelope,
            materialization_context,
            outcome,
            session_id=session.session_id,
            lease_guard=lease_guard,
        )
        lease_guard()
        self._storyboard_promotion.promote(
            outcome,
            action_turn_id=envelope.action_turn_id,
            session_id=session.session_id,
        )
        self._activate_prompt_ready_media(envelope, outcome)
        if envelope.operation_kind == "parent" and envelope.capability_id != "character_design":
            self._parent_derived.reconcile_after_parent(envelope, lease_guard=lease_guard)
        return outcome.node_ids[0] if outcome.node_ids else None

    def _prepare_guided_document_stage(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1,
        context: CapabilityMaterializationContextV1,
        session_id: str,
    ) -> tuple[MaterializationDocumentWriteV1, ...]:
        if envelope.capability_id != "script_authoring":
            return ()
        stage = self._conversations.get_guidance_session(envelope.workflow_id).journey.stage
        if stage not in {"narrative_direction", "style_lock", "storyboard_plan"}:
            raise V2PersistenceError(
                "guided_document_stage_invalid",
                "Script Writer can author only the fixed document stages.",
                stage="capability_materialization_publication",
            )
        text = _document_authoring_text(envelope, normalization)
        if not text:
            raise V2PersistenceError(
                "guided_document_content_invalid",
                "Document-only guided authorship requires non-empty accepted content.",
                stage="capability_materialization_publication",
            )
        requirement = self._requirements.get_current(envelope.workflow_id)
        current = self._working_documents.get_by_kind(
            envelope.workflow_id,
            session_id,
            "storyboard_production_plan",
        )
        if current is None:
            authority_plan = self._duration_authority.plan_sequences(
                requirement,
                aspect_ratio=context.explicit_constraints.get("aspect_ratio", "16:9"),
                explicit_sequence_count=context.explicit_constraints.get(
                    "storyboard_sequence_count"
                ),
            )
            segments = tuple(
                StoryboardNarrativeSegmentV2(
                    sequence_id=f"sequence-{window.order}",
                    order=window.order,
                    start_seconds=window.start_seconds,
                    end_seconds=window.end_seconds,
                    narrative_goal=(
                        f"Sequence {window.order} local narrative direction "
                        f"({window.start_seconds:g}-{window.end_seconds:g}s)."
                    ),
                    start_state=(
                        "Opening state" if window.order == 1 else "Continue prior sequence."
                    ),
                    end_state=(
                        "Close the authored direction."
                        if window.order == len(authority_plan.windows)
                        else "Hand off to the next sequence."
                    ),
                    continuity_from_previous=(
                        None if window.order == 1 else "Continue from the prior sequence."
                    ),
                    terminal_policy=(
                        "close" if window.order == len(authority_plan.windows) else "continue"
                    ),
                )
                for window in authority_plan.windows
            )
            try:
                content = StoryboardProductionPlanContentV3(
                    narrative_outline=text,
                    requirement_revision_id=requirement.revision_id,
                    requirement_revision_no=requirement.revision_no,
                    global_parameters=StoryboardPlanGlobalParametersV2(
                        aspect_ratio=authority_plan.aspect_ratio,
                        total_duration_seconds=authority_plan.total_duration_seconds,
                        segment_count=len(authority_plan.windows),
                    ),
                    segments=segments,
                    rows=(),
                    segment_materializations=tuple(
                        StoryboardSegmentMaterializationV3(
                            sequence_id=segment.sequence_id,
                            materialization_id=_sequence_materialization_id(
                                envelope.materialization_id,
                                segment.sequence_id,
                            ),
                        )
                        for segment in segments
                    ),
                )
            except ValidationError as error:
                raise V2PersistenceError(
                    "agent_working_document_content_invalid",
                    "Agent working document content is invalid.",
                    stage="capability_materialization_publication",
                ) from error
            document_id = (
                "adoc_" + _digest(f"{envelope.workflow_id}:{session_id}:storyboard-plan")[:32]
            )
            document = AgentWorkingDocumentV2(
                document_id=document_id,
                workflow_id=envelope.workflow_id,
                guidance_session_id=session_id,
                kind="storyboard_production_plan",
                title="Storyboard Production Plan",
                revision=1,
                content_schema_version=3,
                content_digest=self._working_documents.digest_content(content),
                content=content,
                created_by_agent_run_id=envelope.materialization_id,
                updated_by_agent_run_id=envelope.materialization_id,
                created_at=envelope.created_at,
                updated_at=envelope.created_at,
            )
            return (
                MaterializationDocumentWriteV1(
                    document_type="agent_working_document",
                    document_id=document_id,
                    payload=document.model_dump(mode="json"),
                    relation_metadata={"guided_stage": stage},
                ),
            )
        if not isinstance(current.content, StoryboardProductionPlanContentV3):
            raise V2PersistenceError(
                "agent_storyboard_plan_invalid",
                "The guided document stage requires the authoritative V3 Storyboard Plan.",
                stage="capability_materialization_publication",
            )
        self._duration_authority.validate_plan(requirement, current.content)
        outline = (
            f"{current.content.narrative_outline}\nStyle lock: {text}"
            if stage == "style_lock"
            else text
        )
        next_content = current.content.model_copy(update={"narrative_outline": outline})
        operation = f"accept_{stage}"
        request_digest = self._working_documents.digest_mutation(
            document_id=current.document_id,
            expected_revision=current.revision,
            operation=operation,
            content=next_content,
            agent_run_id=envelope.materialization_id,
        )
        return (
            MaterializationDocumentWriteV1(
                document_type="agent_working_document",
                document_id=current.document_id,
                mutation_plan=AgentDocumentMutationPlanV3(
                    document_id=current.document_id,
                    expected_revision=current.revision,
                    next_revision=current.revision + 1,
                    operation=operation,
                    idempotency_key=f"guided-document:{envelope.materialization_id}",
                    request_digest=request_digest,
                    next_content=next_content,
                ),
                relation_metadata={"guided_stage": stage},
            ),
        )

    def _prepare_bgm_plan(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        session_id: str,
        nodes: tuple,
    ) -> tuple[MaterializationDocumentWriteV1, ...]:
        if envelope.capability_id != "bgm_direction":
            return ()
        current = self._working_documents.get_by_kind(
            envelope.workflow_id,
            session_id,
            "storyboard_production_plan",
        )
        if current is None:
            return ()
        if not isinstance(current.content, StoryboardProductionPlanContentV3):
            raise V2PersistenceError(
                "agent_storyboard_plan_invalid",
                "BGM planning requires the authoritative V3 Storyboard Plan.",
                stage="capability_materialization_publication",
            )
        requirement = self._requirements.get_current(envelope.workflow_id)
        self._duration_authority.validate_plan(requirement, current.content)
        bgm_node = next(
            (node for node in nodes if node.node_type == "audio" and node.creative_role == "bgm"),
            None,
        )
        if bgm_node is None:
            raise V2PersistenceError(
                "agent_storyboard_plan_invalid",
                "BGM materialization did not plan an Audio Node.",
                stage="capability_materialization_publication",
            )
        next_content = current.content.model_copy(
            update={
                "planned_nodes": tuple(
                    item for item in current.content.planned_nodes if item.node_role != "bgm"
                )
                + (
                    StoryboardPlannedNodeV3(
                        node_role="bgm",
                        node_id=bgm_node.node_id,
                        node_revision=bgm_node.revision,
                        materialization_id=envelope.materialization_id,
                    ),
                ),
                "excluded_media": tuple(
                    item for item in current.content.excluded_media if item.node_role != "bgm"
                ),
            }
        )
        operation = "register_planned_bgm"
        request_digest = self._working_documents.digest_mutation(
            document_id=current.document_id,
            expected_revision=current.revision,
            operation=operation,
            content=next_content,
            agent_run_id=envelope.materialization_id,
        )
        return (
            MaterializationDocumentWriteV1(
                document_type="agent_working_document",
                document_id=current.document_id,
                mutation_plan=AgentDocumentMutationPlanV3(
                    document_id=current.document_id,
                    expected_revision=current.revision,
                    next_revision=current.revision + 1,
                    operation=operation,
                    idempotency_key=f"storyboard-plan:bgm:{envelope.materialization_id}",
                    request_digest=request_digest,
                    next_content=next_content,
                ),
                relation_metadata={"node_id": bgm_node.node_id, "node_role": "bgm"},
            ),
        )

    def _prepare_anchor_registry(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        session_id: str,
        nodes: tuple,
    ) -> tuple[MaterializationDocumentWriteV1, ...]:
        role_by_capability = {
            "world_setting": "world_setting",
            "product_design": "product",
            "prop_design": "prop",
            "character_design": "character",
            "scene_design": "scene",
        }
        semantic_role = role_by_capability.get(envelope.capability_id)
        if semantic_role is None and envelope.style_skill_run_id is None:
            return ()
        source_node = (
            next((node for node in nodes if node.creative_role == semantic_role), None)
            if semantic_role is not None
            else None
        )
        if semantic_role is not None and source_node is None:
            raise V2PersistenceError(
                "agent_anchor_source_invalid",
                "Accepted identity materialization did not plan its source Node.",
                stage="capability_materialization_publication",
            )
        requirement = self._requirements.get_current(envelope.workflow_id)
        current = self._working_documents.get_by_kind(
            envelope.workflow_id,
            session_id,
            "anchor_registry",
        )
        if current is not None and not isinstance(current.content, AnchorRegistryContentV3):
            raise V2PersistenceError(
                "agent_anchor_source_invalid",
                "The current Anchor Registry is not authoritative V3 content.",
                stage="capability_materialization_publication",
            )
        next_revision = 1 if current is None else current.revision + 1
        existing_content = (
            AnchorRegistryContentV3(schema_version="3") if current is None else current.content
        )
        anchors = existing_content.anchors
        affected_aliases: list[str] = []
        replaced = False
        attached_derived = False
        if semantic_role is not None and source_node is not None:
            current_anchor = existing_content.current_anchor(semantic_role)
            source = AgentAnchorNodeSourceV3(
                workflow_id=envelope.workflow_id,
                node_id=source_node.node_id,
                node_revision=source_node.revision,
            )
            materialized_role = _anchor_materialized_role(envelope)
            if envelope.operation_kind == "derivative":
                if current_anchor is None or envelope.parent_snapshot is None:
                    raise V2PersistenceError(
                        "parent_materialization_missing",
                        "The accepted parent identity is not available in the Anchor Registry.",
                        stage="capability_materialization_publication",
                    )
                expected_parent_role = (
                    "character_main" if semantic_role == "character" else "product_main"
                )
                if (
                    not isinstance(current_anchor.source, AgentAnchorNodeSourceV3)
                    or current_anchor.source.node_id != envelope.parent_snapshot.node_id
                    or current_anchor.source.node_revision != envelope.parent_snapshot.node_revision
                    or envelope.parent_snapshot.semantic_role != expected_parent_role
                ):
                    raise V2PersistenceError(
                        "parent_materialization_revision_stale",
                        "The Anchor Registry parent identity no longer matches the derivative.",
                        stage="capability_materialization_publication",
                    )
                role_sources = current_anchor.role_sources or (
                    AgentAnchorRoleSourceV3(
                        role=expected_parent_role,
                        source=current_anchor.source,
                    ),
                )
                existing_role = next(
                    (item for item in role_sources if item.role == materialized_role),
                    None,
                )
                if existing_role is not None and existing_role.source != source:
                    raise V2PersistenceError(
                        "derived_materialization_conflict",
                        "The derived identity role is already attached to another Node.",
                        stage="capability_materialization_publication",
                    )
                next_anchor = current_anchor.model_copy(
                    update={
                        "role_sources": (
                            role_sources
                            if existing_role is not None
                            else (
                                *role_sources,
                                AgentAnchorRoleSourceV3(role=materialized_role, source=source),
                            )
                        ),
                        "acceptance_evidence": (
                            *current_anchor.acceptance_evidence,
                            _anchor_acceptance(
                                envelope,
                                requirement_revision_id=requirement.revision_id,
                                requirement_revision_no=requirement.revision_no,
                                document_revision=next_revision,
                                evidence_scope=materialized_role,
                                node_revision=source_node.revision,
                            ),
                        ),
                    }
                )
                anchors = tuple(
                    next_anchor if anchor.alias == current_anchor.alias else anchor
                    for anchor in anchors
                )
                affected_aliases.append(current_anchor.alias)
                attached_derived = True
            else:
                if current_anchor is not None:
                    anchors = tuple(
                        anchor.model_copy(update={"lifecycle": "retired"})
                        if anchor.alias == current_anchor.alias
                        else anchor
                        for anchor in anchors
                    )
                    replaced = True
                alias = _next_authoritative_alias(semantic_role, anchors)
                affected_aliases.append(alias)
                anchors += (
                    AgentAnchorV3(
                        alias=alias,
                        identity_id="identity_"
                        + _digest(f"{envelope.materialization_id}:{semantic_role}")[:32],
                        semantic_role=semantic_role,
                        display_name=envelope.selected_option.title,
                        summary=envelope.selected_option.public_summary,
                        lifecycle=("active" if semantic_role == "world_setting" else "planned"),
                        source=source,
                        role_sources=(
                            (AgentAnchorRoleSourceV3(role=materialized_role, source=source),)
                            if materialized_role is not None
                            else ()
                        ),
                        acceptance_evidence=(
                            _anchor_acceptance(
                                envelope,
                                requirement_revision_id=requirement.revision_id,
                                requirement_revision_no=requirement.revision_no,
                                document_revision=next_revision,
                                evidence_scope=semantic_role,
                                node_revision=source_node.revision,
                            ),
                        ),
                    ),
                )
        if envelope.style_skill_run_id is not None:
            snapshot = self._conversations.get_active_creative_direction_snapshot(
                envelope.workflow_id
            )
            if (
                snapshot.skill_run_id != envelope.style_skill_run_id
                or snapshot.source_skill_id is None
                or snapshot.source_skill_version is None
                or snapshot.source_skill_digest is None
            ):
                raise V2PersistenceError(
                    "style_skill_snapshot_invalid",
                    "The selected Style Skill snapshot is incomplete or stale.",
                    stage="capability_materialization_publication",
                )
            style_source = AgentAnchorSkillSnapshotSourceV3(
                skill_id=snapshot.source_skill_id,
                skill_version=snapshot.source_skill_version,
                package_digest=_sha256_digest(snapshot.source_skill_digest),
            )
            current_style = existing_content.current_anchor("style")
            if current_style is None or current_style.source != style_source:
                if current_style is not None:
                    anchors = tuple(
                        anchor.model_copy(update={"lifecycle": "retired"})
                        if anchor.alias == current_style.alias
                        else anchor
                        for anchor in anchors
                    )
                    replaced = True
                style_alias = _next_authoritative_alias("style", anchors)
                affected_aliases.append(style_alias)
                anchors += (
                    AgentAnchorV3(
                        alias=style_alias,
                        identity_id="identity_"
                        + _digest(f"{envelope.style_skill_run_id}:style")[:32],
                        semantic_role="style",
                        display_name=snapshot.source_skill_id,
                        summary=f"Approved Style Skill {snapshot.source_skill_id}.",
                        lifecycle="active",
                        source=style_source,
                        acceptance_evidence=(
                            _anchor_acceptance(
                                envelope,
                                requirement_revision_id=requirement.revision_id,
                                requirement_revision_no=requirement.revision_no,
                                document_revision=next_revision,
                                evidence_scope="style",
                                node_revision=None,
                            ),
                        ),
                    ),
                )
        next_content = AnchorRegistryContentV3(schema_version="3", anchors=anchors)
        document_id = (
            current.document_id
            if current is not None
            else "adoc_" + _digest(f"{envelope.workflow_id}:{session_id}:anchor-registry")[:32]
        )
        if current is None:
            document = AgentWorkingDocumentV2(
                document_id=document_id,
                workflow_id=envelope.workflow_id,
                guidance_session_id=session_id,
                kind="anchor_registry",
                title="Anchor Registry",
                revision=1,
                content_schema_version=3,
                content_digest=self._working_documents.digest_content(next_content),
                content=next_content,
                created_by_agent_run_id=envelope.materialization_id,
                updated_by_agent_run_id=envelope.materialization_id,
                created_at=envelope.created_at,
                updated_at=envelope.created_at,
            )
            return (
                MaterializationDocumentWriteV1(
                    document_type="agent_working_document",
                    document_id=document_id,
                    payload=document.model_dump(mode="json"),
                    relation_metadata={"anchor_aliases": affected_aliases},
                ),
            )
        operation = (
            "attach_derived_anchor_role"
            if attached_derived
            else "replace_anchor"
            if replaced
            else (
                "register_planned_anchor" if semantic_role is not None else "activate_style_anchor"
            )
        )
        request_digest = self._working_documents.digest_mutation(
            document_id=document_id,
            expected_revision=current.revision,
            operation=operation,
            content=next_content,
            agent_run_id=envelope.materialization_id,
        )
        return (
            MaterializationDocumentWriteV1(
                document_type="agent_working_document",
                document_id=document_id,
                mutation_plan=AgentDocumentMutationPlanV3(
                    document_id=document_id,
                    expected_revision=current.revision,
                    next_revision=current.revision + 1,
                    operation=operation,
                    idempotency_key=f"anchor:{envelope.materialization_id}",
                    request_digest=request_digest,
                    next_content=next_content,
                ),
                relation_metadata={"anchor_aliases": affected_aliases},
            ),
        )

    def resume_committed(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        lease_guard: Callable[[], None],
    ) -> str | None:
        """Resume only prompt preparation after an immutable commit."""

        outcome = self._commit_service.get_completed_outcome(
            envelope.materialization_id,
            envelope.action_turn_id,
        )
        if outcome is None:
            return None
        if envelope.operation_kind == "parent" and envelope.capability_id == "character_design":
            self._parent_derived.reconcile_after_parent(envelope, lease_guard=lease_guard)
        pending_preparations: list[tuple[str, str]] = []
        for node_id, operation_id in zip(
            outcome.node_ids,
            outcome.prompt_preparation_ids,
            strict=True,
        ):
            node = self._workflows.get_node(envelope.workflow_id, node_id)
            if node.prompt_preparation.operation_id != operation_id:
                raise V2PersistenceError(
                    "prompt_preparation_dispatch_stale",
                    "Committed prompt-preparation operation is no longer current.",
                    stage="capability_materialization_publication",
                    details={"node_id": node_id, "operation_id": operation_id},
                )
            if node.prompt_preparation.status == "ready":
                continue
            pending_preparations.append((node_id, operation_id))
        pending_preparations = tuple(pending_preparations)
        session = self._conversations.get_guidance_session(envelope.workflow_id)
        if pending_preparations:
            # A committed materialization is recovered from the exact
            # dispatch operation that was persisted with its Draft.  Rebuilding
            # context from the mutable requirement/session state here could
            # silently change the prompt after a restart or a later Journey
            # revision.  Resolve every pending operation before preparing any
            # sibling so malformed or missing authority fails closed.
            persisted_contexts = {
                node_id: self._load_persisted_prompt_context(
                    workflow_id=envelope.workflow_id,
                    node_id=node_id,
                    operation_id=operation_id,
                )
                for node_id, operation_id in pending_preparations
            }
            self._prepare_prompts(
                envelope,
                next(iter(persisted_contexts.values())),
                session_id=session.session_id,
                session_revision=outcome.session_revision,
                stage=outcome.journey_stage,
                occurrence_id=(
                    envelope.occurrence_id if envelope.capability_id == "character_design" else None
                ),
                node_ids=tuple(item[0] for item in pending_preparations),
                operation_ids=tuple(item[1] for item in pending_preparations),
                lease_guard=lease_guard,
                context_by_node=persisted_contexts,
            )
        context = materialization_context_from_state(
            envelope,
            conversations=self._conversations,
            workflows=self._workflows,
            asset_resolver=self._asset_resolver,
            validate_references=False,
        )
        self._prepare_storyboard_dependencies(
            envelope,
            context,
            outcome,
            session_id=session.session_id,
            lease_guard=lease_guard,
        )
        lease_guard()
        self._storyboard_promotion.promote(
            outcome,
            action_turn_id=envelope.action_turn_id,
            session_id=session.session_id,
        )
        self._activate_prompt_ready_media(envelope, outcome)
        if envelope.operation_kind == "parent" and envelope.capability_id != "character_design":
            self._parent_derived.reconcile_after_parent(envelope, lease_guard=lease_guard)
        return outcome.node_ids[0] if outcome.node_ids else None

    def _load_persisted_prompt_context(
        self,
        *,
        workflow_id: str,
        node_id: str,
        operation_id: str,
    ) -> StageAuthoringContextV1:
        """Load and verify the immutable context for one recovery operation."""

        dispatch = self._prompt_dispatch.get_by_node_operation(
            workflow_id,
            node_id,
            operation_id,
        )
        if dispatch is None:
            raise V2PersistenceError(
                "prompt_preparation_dispatch_missing",
                "Prompt-preparation recovery has no matching dispatch authority.",
                stage="capability_materialization_publication",
                details={"node_id": node_id, "operation_id": operation_id},
            )
        if any(
            getattr(dispatch, field, None) != expected
            for field, expected in (
                ("workflow_id", workflow_id),
                ("node_id", node_id),
                ("operation_id", operation_id),
            )
        ):
            raise V2PersistenceError(
                "prompt_preparation_dispatch_stale",
                "Prompt-preparation dispatch identity does not match recovery authority.",
                stage="capability_materialization_publication",
            )
        payload = getattr(dispatch, "context_json", None)
        if not isinstance(payload, Mapping) or not payload:
            raise V2PersistenceError(
                "prompt_preparation_context_missing",
                "Prompt-preparation dispatch has no immutable context snapshot.",
                stage="capability_materialization_publication",
            )
        try:
            context = StageAuthoringContextV1.model_validate(dict(payload))
        except (TypeError, ValueError, ValidationError) as error:
            raise V2PersistenceError(
                "prompt_preparation_context_invalid",
                "Persisted prompt-preparation context is invalid.",
                stage="capability_materialization_publication",
            ) from error
        persisted_digest = getattr(dispatch, "context_digest", None)
        if not isinstance(persisted_digest, str) or not persisted_digest:
            raise V2PersistenceError(
                "prompt_preparation_context_invalid",
                "Persisted prompt-preparation context has no digest proof.",
                stage="capability_materialization_publication",
            )
        try:
            current_digest = context_digest(context)
        except (TypeError, ValueError) as error:
            raise V2PersistenceError(
                "prompt_preparation_context_invalid",
                "Persisted prompt-preparation context cannot be serialized.",
                stage="capability_materialization_publication",
            ) from error
        if current_digest != persisted_digest or context.workflow_id != workflow_id:
            raise V2PersistenceError(
                "prompt_preparation_dispatch_stale",
                "Persisted prompt-preparation context does not match its dispatch proof.",
                stage="capability_materialization_publication",
            )
        return context

    def _activate_prompt_ready_media(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        outcome,
    ) -> None:
        if envelope.capability_id != "bgm_direction" or self._prompt_ready_activation is None:
            return
        self._prompt_ready_activation(
            outcome.workflow_id,
            outcome.node_ids,
            source_id=outcome.materialization_id,
        )

    @staticmethod
    def _storyboard_normalization(
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
    ) -> MaterializationNormalizationV1:
        draft_key, _, _, title_suffix, _ = stage_definitions("storyboard_design")[0]
        summary = envelope.selected_option.public_summary
        style_prompt = next(
            (
                value.strip()
                for key in ("role_guidance", "global_guidance", "summary")
                if isinstance((value := context.style_projection.get(key)), str) and value.strip()
            ),
            "Detailed semi-realistic advertising illustration",
        )
        style = VisualStyleContractV2(
            style_prompt=style_prompt,
            source=("video_skill" if context.style_projection else "platform_default"),
        )
        result = StoryboardMaterializationResultV1(
            title=stage_draft_title(envelope.selected_option.title, title_suffix),
            summary_prompt=summary,
            generation_prompt=f"Create one text-free 3x3 storyboard grid. {summary}",
            structured_content=StoryboardGridContentV2(
                sequence_summary=summary,
                narrative_goal=envelope.selected_option.public_summary,
                style=style,
                panels=tuple(
                    StoryboardPanelV2(
                        panel_index=index,
                        beat=f"Narrative beat {index}: {summary}",
                        composition=f"Distinct composition {index}",
                        camera=f"Camera setup {index}",
                        subject_action=f"Ordered action {index}",
                        continuity_from_previous=(
                            "Opening state" if index == 1 else f"Continue from panel {index - 1}"
                        ),
                    )
                    for index in range(1, 10)
                ),
            ),
        )
        return MaterializationNormalizationV1(
            result=result,
            parameters=stage_draft_parameters("storyboard_design", draft_key, context),
            parameter_provenance={},
            mode="deterministic_fallback",
        )

    def _validate_target(self, envelope: ProposalApplicationEnvelopeV1) -> None:
        if envelope.target_node_id is None:
            return
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

    def _prepare_storyboard(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        normalization: MaterializationNormalizationV1,
        context: CapabilityMaterializationContextV1,
        session_id: str,
    ) -> tuple[MaterializationNormalizationV1, tuple[MaterializationDocumentWriteV1, ...]]:
        if (
            envelope.capability_id != "storyboard_design"
            or self._storyboard_authoring is None
            or self._storyboard_gateway is None
        ):
            return normalization, ()

        requirement = self._requirements.get_current(envelope.workflow_id)
        current = self._working_documents.get_by_kind(
            envelope.workflow_id,
            session_id,
            "storyboard_production_plan",
        )
        if current is not None:
            if not isinstance(current.content, StoryboardProductionPlanContentV3):
                raise V2PersistenceError(
                    "agent_storyboard_plan_invalid",
                    "Storyboard Grid preparation requires the authoritative V3 Storyboard Plan.",
                    stage="capability_materialization_publication",
                )
            content = current.content
            self._duration_authority.validate_plan(requirement, content)
            document_id = current.document_id
            document_revision = current.revision
        else:
            authority_plan = self._duration_authority.plan_sequences(
                requirement,
                aspect_ratio=context.explicit_constraints.get("aspect_ratio", "16:9"),
                explicit_sequence_count=context.explicit_constraints.get(
                    "storyboard_sequence_count"
                ),
            )
            context = context.model_copy(
                update={
                    "capability_facts": {
                        **context.capability_facts,
                        "storyboard_sequence_plan": authority_plan.model_dump(mode="json"),
                    }
                }
            )
            outline = self._storyboard_gateway.plan_storyboard_sequence_outline(
                context,
                request_identity=f"{envelope.materialization_id}:outline",
            )
            legacy_outline = self._storyboard_authoring.build_outline_content(
                outline,
                authority_plan,
            )
            content = StoryboardProductionPlanContentV3(
                schema_version="3",
                narrative_outline=legacy_outline.narrative_outline,
                requirement_revision_id=requirement.revision_id,
                requirement_revision_no=requirement.revision_no,
                global_parameters=legacy_outline.global_parameters,
                segments=legacy_outline.segments,
                rows=(),
                segment_materializations=tuple(
                    StoryboardSegmentMaterializationV3(
                        sequence_id=segment.sequence_id,
                        materialization_id=_sequence_materialization_id(
                            envelope.materialization_id,
                            segment.sequence_id,
                        ),
                    )
                    for segment in legacy_outline.segments
                ),
            )
            document_id = "adoc_" + _digest(f"{envelope.materialization_id}:storyboard-plan")[:32]
            document_revision = 1
        node_id = "node_" + _digest(envelope.materialization_id)[:32]
        segment_drafts: dict[str, StoryboardSegmentMaterializationDraftV2] = {}
        for sequence in content.segments:
            sequence_id = sequence.sequence_id
            segment_context = self._storyboard_authoring.build_segment_context_from_content(
                envelope.workflow_id,
                document_id,
                document_revision,
                AgentWorkingDocumentRepository.digest_content(content),
                content,
                sequence_id,
                style_excerpt=str(context.style_projection)[:8_192],
            )
            segment_draft = self._storyboard_gateway.materialize_storyboard_segment(
                segment_context,
                request_identity=f"{envelope.materialization_id}:{sequence_id}",
            )
            segment_drafts[sequence_id] = segment_draft
            content = self._storyboard_authoring.plan_materialized_sequence_v3(
                content,
                sequence_id,
                segment_draft,
                planned_node=(
                    StoryboardPlannedNodeV3(
                        sequence_id=sequence_id,
                        node_role="storyboard_grid",
                        node_id=node_id,
                        node_revision=1,
                        materialization_id=envelope.materialization_id,
                    )
                    if sequence.order == 1
                    else None
                ),
                materialization_id=_sequence_materialization_id(
                    envelope.materialization_id,
                    sequence_id,
                ),
            )
        first_sequence = _first_storyboard_sequence(content)
        if current is None:
            document_write = MaterializationDocumentWriteV1(
                document_type="agent_working_document",
                document_id=document_id,
                payload=AgentWorkingDocumentV2(
                    document_id=document_id,
                    workflow_id=envelope.workflow_id,
                    guidance_session_id=session_id,
                    kind="storyboard_production_plan",
                    title="Storyboard Production Plan",
                    revision=1,
                    content_schema_version=3,
                    content_digest=AgentWorkingDocumentRepository.digest_content(content),
                    content=content,
                    created_by_agent_run_id=envelope.materialization_id,
                    updated_by_agent_run_id=envelope.materialization_id,
                    created_at=envelope.created_at,
                    updated_at=envelope.created_at,
                ).model_dump(mode="json"),
                relation_metadata={
                    "node_id": node_id,
                    "sequence_id": first_sequence.sequence_id,
                },
            )
        else:
            operation = "materialize_storyboard_grids"
            document_write = MaterializationDocumentWriteV1(
                document_type="agent_working_document",
                document_id=document_id,
                mutation_plan=AgentDocumentMutationPlanV3(
                    document_id=document_id,
                    expected_revision=current.revision,
                    next_revision=current.revision + 1,
                    operation=operation,
                    idempotency_key=f"storyboard-grids:{envelope.materialization_id}",
                    request_digest=self._working_documents.digest_mutation(
                        document_id=document_id,
                        expected_revision=current.revision,
                        operation=operation,
                        content=content,
                        agent_run_id=envelope.materialization_id,
                    ),
                    next_content=content,
                ),
                relation_metadata={
                    "node_id": node_id,
                    "sequence_id": first_sequence.sequence_id,
                },
            )
        original = StoryboardMaterializationResultV1.model_validate(normalization.result)
        sequence = first_sequence
        sequence_id = sequence.sequence_id
        segment = segment_drafts[sequence_id]
        result = original.model_copy(
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
        return (
            normalization.model_copy(
                update={
                    "result": result,
                    "parameters": {
                        **normalization.parameters,
                        "source_agent_document_id": document_id,
                        "source_sequence_id": sequence_id,
                    },
                }
            ),
            (document_write,),
        )

    def _prepare_prompts(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1 | StageAuthoringContextV1,
        *,
        session_id: str,
        session_revision: int,
        stage: JourneyStageV2,
        occurrence_id: str | None,
        node_ids: tuple[str, ...],
        operation_ids: tuple[str, ...],
        lease_guard: Callable[[], None],
        context_by_node: Mapping[str, StageAuthoringContextV1] | None = None,
    ) -> None:
        if not operation_ids:
            return
        if context_by_node is not None:
            # A dependency wave must carry one immutable context for every
            # operation.  Never let a missing entry fall back to a sibling (or
            # to mutable session state), because that would prepare a prompt
            # under the wrong identity and digest.
            missing_context_nodes = tuple(
                node_id for node_id in node_ids if node_id not in context_by_node
            )
            if missing_context_nodes:
                raise V2PersistenceError(
                    "prompt_preparation_context_missing",
                    "Prompt-preparation context is missing for a required Node.",
                    stage="capability_materialization_publication",
                    details={"node_ids": list(missing_context_nodes)},
                )
            invalid_context_nodes = tuple(
                node_id
                for node_id in node_ids
                if not isinstance(context_by_node[node_id], StageAuthoringContextV1)
            )
            if invalid_context_nodes:
                raise V2PersistenceError(
                    "prompt_preparation_context_invalid",
                    "Prompt-preparation context is invalid for a required Node.",
                    stage="capability_materialization_publication",
                    details={"node_ids": list(invalid_context_nodes)},
                )
            stage_context = context_by_node[node_ids[0]] if node_ids else context
        elif isinstance(context, StageAuthoringContextV1):
            stage_context = context
        else:
            stage_context = stage_authoring_context_from_materialization(
                context,
                session_id=session_id,
                session_revision=session_revision,
                stage=stage,
                occurrence_id=occurrence_id,
                references=envelope.reference_plan.references,
            )
        prompt_service = NodePromptPreparationService(self._workflows)
        if self._storyboard_gateway is not None:
            prompt_service = NodePromptPreparationService(
                self._workflows,
                role_brief_author=lambda role_context, request_identity: (
                    self._storyboard_gateway.author_role_brief(
                        role_context,
                        request_identity=request_identity,
                    )
                ),
                asset_resolver=self._asset_resolver,
            )
        errors: list[Exception] = []
        operation_by_node = dict(zip(node_ids, operation_ids, strict=True))
        for node_id in node_ids:
            operation_id = operation_by_node.get(node_id)
            if operation_id is None:
                continue
            lease_guard()
            try:
                prompt_service.prepare(
                    envelope.workflow_id,
                    node_id,
                    operation_id=operation_id,
                    context=(
                        context_by_node[node_id] if context_by_node is not None else stage_context
                    ),
                )
            except Exception as error:  # noqa: BLE001 - preserve sibling preparation.
                errors.append(error)
        if errors:
            raise V2PersistenceError(
                "prompt_preparation_failed",
                "One or more Draft prompts could not be prepared.",
                stage="capability_materialization_publication",
                details={"retryable": True},
            ) from errors[0]

    def _prepare_storyboard_dependencies(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
        outcome,
        *,
        session_id: str,
        lease_guard: Callable[[], None],
    ) -> None:
        """Prepare the transitive source Drafts before strict promotion.

        The materialization commit and continuation identity are the durable
        retry boundary. An idempotent event records the exact dependency set so
        restart/replay can resume without a second state machine.
        """

        if outcome.journey_stage != "storyboard_grids":
            return
        workflow = self._workflows.get_workflow(envelope.workflow_id)
        dependency_discovery = getattr(
            self._storyboard_promotion,
            "required_dependency_node_ids",
            None,
        )
        if dependency_discovery is None:
            return
        anchor_discovery = getattr(self._storyboard_promotion, "_guided_anchor_node_ids", None)
        anchors = (
            anchor_discovery(envelope.workflow_id, session_id)
            if anchor_discovery is not None
            else frozenset()
        )
        dependency_ids = dependency_discovery(
            workflow,
            outcome.node_ids,
            guided_anchor_node_ids=anchors,
        )
        nodes = {node.node_id: node for node in workflow.nodes}
        pending: list[tuple[str, str]] = []
        contexts: dict[str, StageAuthoringContextV1] = {}
        prompt_service = NodePromptPreparationService(self._workflows)
        for node_id in dependency_ids:
            node = nodes.get(node_id)
            if node is None or node.status != "draft":
                continue
            operation_id = node.prompt_preparation.operation_id
            stale = False
            evidence = node.prompt_preparation.assertion_evidence
            if node.prompt_preparation.status == "ready" and evidence is not None:
                try:
                    current_sources = current_source_snapshots_for_evidence(
                        evidence,
                        workflow,
                        self._asset_resolver,
                    )
                    stale = current_sources != evidence.source_snapshots
                except V2PersistenceError:
                    stale = True
            if stale:
                if not operation_id:
                    raise V2PersistenceError(
                        "storyboard_prompt_ready_authority_invalid",
                        "Stale Draft source has no prompt preparation operation.",
                        stage="storyboard_prompt_ready_promotion",
                    )
                invalidated = prompt_service.invalidate_for_dependency_change(
                    envelope.workflow_id,
                    node_id,
                    operation_id=operation_id,
                )
                # Invalidation creates a new fenced preparation identity.  Do
                # not carry the stale operation into the next dependency wave;
                # the returned Node is the only current snapshot authority.
                node = invalidated
                operation_id = node.prompt_preparation.operation_id
                if not operation_id:
                    raise V2PersistenceError(
                        "storyboard_prompt_ready_authority_invalid",
                        "Invalidated Draft source has no successor operation.",
                        stage="storyboard_prompt_ready_promotion",
                    )
                turn = self._conversations.get_turn(envelope.action_turn_id)
                self._conversations.events.append(
                    V2EventInsert(
                        workflow_id=envelope.workflow_id,
                        node_id=node_id,
                        conversation_id=turn.conversation_id,
                        turn_id=envelope.action_turn_id,
                        action_id=f"storyboard-prompt-ready:{outcome.materialization_id}",
                        event_type="downstream_prompt_evidence_invalidated",
                        transition_key=(
                            f"storyboard-prompt-ready:{outcome.materialization_id}:"
                            f"{node_id}:invalidated:{invalidated.revision}"
                        ),
                        created_at=datetime.now(timezone.utc).isoformat(),
                        payload={
                            "materialization_id": outcome.materialization_id,
                            "target_node_id": node_id,
                            "operation_id": operation_id,
                            "reason": "required_source_revision_or_asset_version_changed",
                        },
                    )
                )
            if node.prompt_preparation.status == "ready" and not stale:
                continue
            if not operation_id:
                raise V2PersistenceError(
                    "storyboard_prompt_ready_authority_invalid",
                    "Required Draft source has no prompt preparation operation.",
                    stage="storyboard_prompt_ready_promotion",
                    details={"invariant": "required_source_operation"},
                )
            occurrence_id = (
                str(node.metadata["occurrence_id"])
                if node.creative_role == "character" and node.metadata.get("occurrence_id")
                else None
            )
            source_context = stage_authoring_context_from_materialization(
                context,
                session_id=session_id,
                session_revision=outcome.session_revision,
                stage=outcome.journey_stage,
                occurrence_id=occurrence_id,
                references=envelope.reference_plan.references,
            )
            if node.creative_role == "character":
                source_context = source_context.model_copy(
                    update={
                        "internal_skill_ref": (
                            "agent/skills/video_agent_character_design/SKILL.md"
                        ),
                    }
                )
            contexts[node_id] = source_context
            pending.append((node_id, operation_id))
        if not pending:
            return
        pending.sort()
        action_id = f"storyboard-prompt-ready:{outcome.materialization_id}"
        turn = self._conversations.get_turn(envelope.action_turn_id)
        payload = {
            "materialization_id": outcome.materialization_id,
            "barrier_status": "pending",
            "source_node_ids": [item[0] for item in pending],
            "operation_ids": [item[1] for item in pending],
        }
        self._conversations.events.append(
            V2EventInsert(
                workflow_id=envelope.workflow_id,
                node_id=outcome.node_ids[0] if outcome.node_ids else None,
                conversation_id=turn.conversation_id,
                turn_id=envelope.action_turn_id,
                action_id=action_id,
                event_type="storyboard_prompt_ready_dependency_barrier",
                transition_key=f"{action_id}:pending",
                created_at=datetime.now(timezone.utc).isoformat(),
                payload=payload,
            )
        )
        self._prepare_prompts(
            envelope,
            context,
            session_id=session_id,
            session_revision=outcome.session_revision,
            stage=outcome.journey_stage,
            occurrence_id=None,
            node_ids=tuple(item[0] for item in pending),
            operation_ids=tuple(item[1] for item in pending),
            lease_guard=lease_guard,
            context_by_node=contexts,
        )

        # Upstream preparation can publish new Node revisions or AssetVersions
        # after a downstream Draft was initially prepared. Re-scan the closure
        # and prepare another deterministic wave before promotion admits any
        # execution with stale reference evidence.
        refreshed_workflow = self._workflows.get_workflow(envelope.workflow_id)
        refreshed_nodes = {node.node_id: node for node in refreshed_workflow.nodes}
        followup_pending: list[tuple[str, str]] = []
        followup_contexts: dict[str, StageAuthoringContextV1] = {}
        for node_id in dependency_ids:
            node = refreshed_nodes.get(node_id)
            if node is None or node.status != "draft":
                continue
            evidence = node.prompt_preparation.assertion_evidence
            if node.prompt_preparation.status != "ready" or evidence is None:
                continue
            try:
                current_sources = current_source_snapshots_for_evidence(
                    evidence,
                    refreshed_workflow,
                    self._asset_resolver,
                )
                stale = current_sources != evidence.source_snapshots
            except V2PersistenceError:
                stale = True
            if not stale:
                continue
            operation_id = node.prompt_preparation.operation_id
            if not operation_id:
                raise V2PersistenceError(
                    "storyboard_prompt_ready_authority_invalid",
                    "Stale Draft source has no prompt preparation operation.",
                    stage="storyboard_prompt_ready_promotion",
                )
            invalidated = prompt_service.invalidate_for_dependency_change(
                envelope.workflow_id,
                node_id,
                operation_id=operation_id,
            )
            # The dependency wave may publish a new Node revision and must be
            # prepared under the successor identity returned by invalidation.
            node = invalidated
            operation_id = node.prompt_preparation.operation_id
            if not operation_id:
                raise V2PersistenceError(
                    "storyboard_prompt_ready_authority_invalid",
                    "Invalidated Draft source has no successor operation.",
                    stage="storyboard_prompt_ready_promotion",
                )
            self._conversations.events.append(
                V2EventInsert(
                    workflow_id=envelope.workflow_id,
                    node_id=node_id,
                    conversation_id=turn.conversation_id,
                    turn_id=envelope.action_turn_id,
                    action_id=action_id,
                    event_type="downstream_prompt_evidence_invalidated",
                    transition_key=f"{action_id}:{node_id}:invalidated:{invalidated.revision}",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    payload={
                        "materialization_id": outcome.materialization_id,
                        "target_node_id": node_id,
                        "operation_id": operation_id,
                        "reason": "upstream_dependency_wave_published_new_revision",
                    },
                )
            )
            occurrence_id = (
                str(node.metadata["occurrence_id"])
                if node.creative_role == "character" and node.metadata.get("occurrence_id")
                else None
            )
            followup_contexts[node_id] = stage_authoring_context_from_materialization(
                context,
                session_id=session_id,
                session_revision=outcome.session_revision,
                stage=outcome.journey_stage,
                occurrence_id=occurrence_id,
                references=envelope.reference_plan.references,
            )
            if node.creative_role == "character":
                followup_contexts[node_id] = followup_contexts[node_id].model_copy(
                    update={
                        "internal_skill_ref": "agent/skills/video_agent_character_design/SKILL.md"
                    }
                )
            followup_pending.append((node_id, operation_id))
        if followup_pending:
            followup_pending.sort()
            self._prepare_prompts(
                envelope,
                context,
                session_id=session_id,
                session_revision=outcome.session_revision,
                stage=outcome.journey_stage,
                occurrence_id=None,
                node_ids=tuple(item[0] for item in followup_pending),
                operation_ids=tuple(item[1] for item in followup_pending),
                lease_guard=lease_guard,
                context_by_node=followup_contexts,
            )
        self._conversations.events.append(
            V2EventInsert(
                workflow_id=envelope.workflow_id,
                node_id=outcome.node_ids[0] if outcome.node_ids else None,
                conversation_id=turn.conversation_id,
                turn_id=envelope.action_turn_id,
                action_id=action_id,
                event_type="storyboard_prompt_ready_dependency_barrier_satisfied",
                transition_key=f"{action_id}:satisfied",
                created_at=datetime.now(timezone.utc).isoformat(),
                payload={**payload, "barrier_status": "satisfied"},
            )
        )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _first_storyboard_sequence(content: StoryboardProductionPlanContentV3):
    sequence = next((item for item in content.segments if item.order == 1), None)
    if sequence is None:
        raise V2PersistenceError(
            "agent_storyboard_plan_invalid",
            "The Storyboard Plan has no first sequence.",
            stage="capability_materialization_publication",
        )
    return sequence


def _sequence_materialization_id(parent_materialization_id: str, sequence_id: str) -> str:
    return "materialization_" + _digest(f"{parent_materialization_id}:{sequence_id}")[:32]


def _document_authoring_text(
    envelope: ProposalApplicationEnvelopeV1,
    normalization: MaterializationNormalizationV1 | CapabilityMaterializationContextV1,
) -> str:
    if isinstance(normalization, MaterializationNormalizationV1):
        structured = normalization.result.structured_content
        content = getattr(structured, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return "\n".join(
        item.strip()
        for item in (
            envelope.selected_option.public_summary,
            *tuple(getattr(envelope.selected_option, "key_decisions", ())),
        )
        if item and item.strip()
    )[:16_384]


def _sha256_digest(value: str) -> str:
    normalized = value.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise V2PersistenceError(
            "style_skill_snapshot_invalid",
            "The selected Style Skill digest is invalid.",
            stage="capability_materialization_publication",
        )
    return f"sha256:{normalized}"


def _anchor_acceptance(
    envelope: ProposalApplicationEnvelopeV1,
    *,
    requirement_revision_id: str,
    requirement_revision_no: int,
    document_revision: int,
    evidence_scope: str,
    node_revision: int | None,
) -> AnchorAcceptanceEvidenceV1:
    return AnchorAcceptanceEvidenceV1(
        evidence_id="evidence_"
        + _digest(f"{envelope.materialization_id}:anchor:{evidence_scope}")[:32],
        actor=envelope.selection_actor,
        decision=("accepted" if envelope.selection_actor == "user" else "delegated"),
        action_id=envelope.action_turn_id,
        requirement_revision_id=requirement_revision_id,
        requirement_revision_no=requirement_revision_no,
        node_revision=node_revision,
        document_revision=document_revision,
        recorded_at=envelope.created_at,
    )


def _next_authoritative_alias(semantic_role: str, anchors: tuple[AgentAnchorV3, ...]) -> str:
    prefix = {
        "world_setting": "WORLD",
        "product": "PRODUCT",
        "prop": "PROP",
        "character": "CHARACTER",
        "scene": "SCENE",
        "style": "STYLE",
        "composition": "COMPOSITION",
    }[semantic_role]
    existing = {anchor.alias for anchor in anchors}
    for index in range(1, 100):
        candidate = f"{prefix}{index:02d}"
        if candidate not in existing:
            return candidate
    raise V2PersistenceError(
        "agent_anchor_alias_conflict",
        "The Anchor Registry alias range is exhausted.",
        stage="capability_materialization_publication",
    )


def _anchor_materialized_role(
    envelope: ProposalApplicationEnvelopeV1,
) -> str | None:
    if envelope.capability_id == "product_design":
        return "product_multiview" if envelope.operation_kind == "derivative" else "product_main"
    if envelope.capability_id == "character_design":
        return (
            "character_turnaround" if envelope.operation_kind == "derivative" else "character_main"
        )
    return None
