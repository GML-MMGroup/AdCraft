"""Deterministic publication of one validated capability Materialization."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256

from pydantic import BaseModel

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_materialization_repository import (
    AgentCanvasMaterializationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_working_document_repository import AgentWorkingDocumentRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_ad_media import (
    StoryboardGridContentV2,
    StoryboardPanelV2,
    VisualStyleContractV2,
)
from app.schemas.agent_canvas_production_journey import JourneyStageV1
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
from app.schemas.agent_working_documents import (
    AgentWorkingDocumentV2,
    StoryboardNodeRecordV2,
)
from app.services.agent_canvas_conversation import (
    VideoAgentGateway,
)
from app.services.agent_canvas_materialization_runtime import (
    materialization_context_from_state,
    validate_materialization_reference_snapshots,
)
from app.services.agent_canvas_materialization_normalizer import (
    CapabilityMaterializationNormalizer,
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
from app.services.agent_canvas_storyboard_sequence_windows import (
    StoryboardSequenceWindowPlanner,
)
from app.services.agent_canvas_capability_draft_bundle import (
    stage_definitions,
    stage_draft_parameters,
    stage_draft_title,
)
from app.services.agent_canvas_prompt_preparation import NodePromptPreparationService
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
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._commit_service = commit_service or AgentCanvasMaterializationCommitService(
            AgentCanvasMaterializationRepository(workflows.database, conversations.events),
            GuidedProductionJourneyReducer(),
        )
        self._plan_compiler = CapabilityMaterializationPlanCompiler()
        self._asset_resolver = asset_resolver
        self._storyboard_authoring = storyboard_authoring
        self._storyboard_gateway = storyboard_gateway

    def publish(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        result: BaseModel,
        lease_guard: Callable[[], None],
    ) -> str:
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
        storyboard_documents: tuple[MaterializationDocumentWriteV1, ...] = ()
        if isinstance(normalization, MaterializationNormalizationV1):
            normalization, storyboard_documents = self._prepare_storyboard(
                envelope,
                normalization,
                materialization_context,
                session.session_id,
            )
        workflow = self._workflows.get_workflow(envelope.workflow_id)
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
            storyboard_documents=storyboard_documents,
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
        self._prepare_prompts(
            envelope,
            materialization_context,
            session_id=session.session_id,
            session_revision=session.revision,
            stage=session.journey.stage,
            foundation_item_id=(
                session.journey.active_action.foundation_item_id
                if session.journey.active_action is not None
                else None
            ),
            node_ids=outcome.node_ids,
            operation_ids=outcome.prompt_preparation_ids,
            lease_guard=lease_guard,
        )
        if not outcome.node_ids:
            raise V2PersistenceError(
                "materialization_outcome_invalid",
                "Materialization did not create a Draft Node.",
                stage="capability_materialization_publication",
            )
        return outcome.node_ids[0]

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
        if not outcome.node_ids:
            raise V2PersistenceError(
                "materialization_outcome_invalid",
                "Materialization did not create a Draft Node.",
                stage="capability_materialization_publication",
            )
        pending_preparations = tuple(
            (node_id, operation_id)
            for node_id, operation_id in zip(
                outcome.node_ids,
                outcome.prompt_preparation_ids,
                strict=True,
            )
            if self._workflows.get_node(
                envelope.workflow_id,
                node_id,
            ).prompt_preparation.status
            != "ready"
        )
        if not pending_preparations:
            return outcome.node_ids[0]
        context = materialization_context_from_state(
            envelope,
            conversations=self._conversations,
            workflows=self._workflows,
            asset_resolver=self._asset_resolver,
            validate_references=False,
        )
        session = self._conversations.get_guidance_session(envelope.workflow_id)
        self._prepare_prompts(
            envelope,
            context,
            session_id=session.session_id,
            session_revision=outcome.session_revision,
            stage=outcome.journey_stage,
            foundation_item_id=None,
            node_ids=tuple(item[0] for item in pending_preparations),
            operation_ids=tuple(item[1] for item in pending_preparations),
            lease_guard=lease_guard,
        )
        return outcome.node_ids[0]

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
                narrative_goal=" ".join(envelope.selected_option.key_decisions),
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

        authority_plan = StoryboardSequenceWindowPlanner.plan(
            total_duration_seconds=context.explicit_constraints.get("duration_seconds", 15),
            aspect_ratio=context.explicit_constraints.get("aspect_ratio", "16:9"),
            explicit_sequence_count=context.explicit_constraints.get("storyboard_sequence_count"),
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
        content = self._storyboard_authoring.build_outline_content(outline, authority_plan)
        document_id = "adoc_" + _digest(f"{envelope.materialization_id}:storyboard-plan")[:32]
        sequence_id = content.segments[0].sequence_id
        content_digest = AgentWorkingDocumentRepository.digest_content(content)
        segment_context = self._storyboard_authoring.build_segment_context_from_content(
            envelope.workflow_id,
            document_id,
            1,
            content_digest,
            content,
            sequence_id,
            style_excerpt=str(context.style_projection)[:8_192],
        )
        segment = self._storyboard_gateway.materialize_storyboard_segment(
            segment_context,
            request_identity=f"{envelope.materialization_id}:{sequence_id}",
        )
        content = self._storyboard_authoring.materialize_segment_content(
            content,
            sequence_id,
            segment,
        )
        node_id = "node_" + _digest(envelope.materialization_id)[:32]
        content = content.model_copy(
            update={
                "node_records": (
                    StoryboardNodeRecordV2(
                        sequence_id=sequence_id,
                        node_role="storyboard_grid",
                        node_id=node_id,
                    ),
                )
            }
        )
        document = AgentWorkingDocumentV2(
            document_id=document_id,
            workflow_id=envelope.workflow_id,
            guidance_session_id=session_id,
            kind="storyboard_production_plan",
            title="Storyboard Production Plan",
            revision=1,
            content_digest=AgentWorkingDocumentRepository.digest_content(content),
            content=content,
            created_by_agent_run_id=envelope.materialization_id,
            updated_by_agent_run_id=envelope.materialization_id,
            created_at=envelope.created_at,
            updated_at=envelope.created_at,
        )
        original = StoryboardMaterializationResultV1.model_validate(normalization.result)
        sequence = content.segments[0]
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
            (
                MaterializationDocumentWriteV1(
                    document_type="agent_working_document",
                    document_id=document_id,
                    payload=document.model_dump(mode="json"),
                    relation_metadata={
                        "node_id": node_id,
                        "sequence_id": sequence_id,
                    },
                ),
            ),
        )

    def _prepare_prompts(
        self,
        envelope: ProposalApplicationEnvelopeV1,
        context: CapabilityMaterializationContextV1,
        *,
        session_id: str,
        session_revision: int,
        stage: JourneyStageV1,
        foundation_item_id: str | None,
        node_ids: tuple[str, ...],
        operation_ids: tuple[str, ...],
        lease_guard: Callable[[], None],
    ) -> None:
        if not operation_ids:
            return
        stage_context = stage_authoring_context_from_materialization(
            context,
            session_id=session_id,
            session_revision=session_revision,
            stage=stage,
            foundation_item_id=foundation_item_id,
            references=envelope.reference_plan.references,
        )
        prompt_service = NodePromptPreparationService(self._workflows)
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
                    context=stage_context,
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


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
