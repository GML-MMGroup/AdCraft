"""Field-by-field bounded contexts for Agent Canvas progressive guidance."""

from __future__ import annotations

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2, ProjectAssetSummaryV2
from app.schemas.agent_canvas_conversation import ConceptProposalV2, VideoSkillRunV2
from app.schemas.agent_canvas_creative_session import (
    CreationModeV2,
    GuidedSessionStateV2,
    NextGuidanceDecisionV2,
    StyleGuidanceContextV2,
)
from app.schemas.agent_operation_contexts import (
    DelegatedProposalChoiceContextV2,
    DelegatedProposalOptionSummaryV2,
    DirectorGuidanceContextV2,
    GuidanceBindingSummaryV2,
    GuidanceImageReferenceV2,
    GuidanceNodeSummaryV2,
    GuidanceProposalSummaryV2,
    GuidanceSpecialistContextV2,
    GuidanceStyleSummaryV2,
)
from app.services.agent_canvas_guidance_ownership import topic_ownership_projection
from app.services.agent_canvas_guidance_stage_policy import GuidanceStagePolicyV2
from app.schemas.agent_canvas_world_setting import WorldSettingContextEnvelopeV2


class GuidanceContextBuilder:
    """Build Pi contexts from explicit public summaries, never repository rows."""

    def build_director(
        self,
        workflow: AgentCanvasWorkflowV2,
        *,
        conversation_id: str,
        user_input: str,
        conversation_summary: str,
        session: GuidedSessionStateV2 | None,
        open_proposal: ConceptProposalV2 | None,
        style_run: VideoSkillRunV2 | None,
        style_summary: str,
        style_guidance: StyleGuidanceContextV2 | None = None,
        mentioned_node_ids: tuple[str, ...],
        image_assets: tuple[ProjectAssetSummaryV2, ...],
        model_capabilities: dict[str, object] | None = None,
        creation_mode: CreationModeV2 = "guided_production",
    ) -> DirectorGuidanceContextV2:
        node_ids = {node.node_id for node in workflow.nodes}
        if any(node_id not in node_ids for node_id in mentioned_node_ids):
            raise _context_error("A mentioned Node does not belong to the Workflow.")
        stage_policy = _stage_policy(
            workflow,
            session=session,
            creation_mode=creation_mode,
        )
        return DirectorGuidanceContextV2(
            context_kind="director_guidance",
            workflow_id=workflow.workflow_id,
            workflow_revision=workflow.revision,
            conversation_id=conversation_id,
            user_input=user_input,
            conversation_summary=conversation_summary,
            topic_ownership=topic_ownership_projection(),
            goal=session.goal if session else None,
            element_decisions=session.element_decisions if session else (),
            guidance_session=session,
            open_proposal=(
                GuidanceProposalSummaryV2(
                    proposal_id=open_proposal.proposal_id,
                    topic_id=open_proposal.topic_id or open_proposal.proposal_kind,
                    proposal_kind=open_proposal.proposal_kind,
                    option_summaries=tuple(
                        option.summary_prompt for option in open_proposal.options
                    ),
                )
                if open_proposal is not None
                else None
            ),
            stage_policy=stage_policy,
            nodes=tuple(_node_summary(node) for node in workflow.nodes),
            bindings=tuple(_binding_summary(binding) for binding in workflow.bindings),
            style=(
                GuidanceStyleSummaryV2(
                    skill_run_id=style_run.skill_run_id,
                    skill_id=style_run.skill_id,
                    skill_version=style_run.skill_version,
                    summary=style_summary,
                )
                if style_run is not None
                else None
            ),
            style_guidance=style_guidance,
            mentioned_node_ids=mentioned_node_ids,
            image_references=tuple(_image_reference(asset) for asset in image_assets),
            model_capabilities=model_capabilities or {},
        )

    def build_specialist(
        self,
        workflow: AgentCanvasWorkflowV2,
        *,
        decision: NextGuidanceDecisionV2,
        session: GuidedSessionStateV2,
        user_instruction: str,
        style_excerpt: str,
        style_guidance: StyleGuidanceContextV2 | None = None,
        accepted_anchors: tuple[str, ...],
        image_assets: tuple[ProjectAssetSummaryV2, ...],
        relevant_node_ids: tuple[str, ...] = (),
        targeted_prompt_baseline: str | None = None,
        world_setting: WorldSettingContextEnvelopeV2 | None = None,
        proposal_mode: str = "choice_set",
    ) -> GuidanceSpecialistContextV2:
        if decision.action != "propose_topic":
            raise _context_error("A Specialist context requires a topic proposal.")
        node_ids = set(relevant_node_ids)
        relevant_nodes = tuple(node for node in workflow.nodes if node.node_id in node_ids)
        relevant_bindings = tuple(
            binding for binding in workflow.bindings if binding.target_node_id in node_ids
        )
        return GuidanceSpecialistContextV2(
            context_kind="guidance_specialist",
            specialist_name=decision.specialist_name,
            workflow_id=workflow.workflow_id,
            workflow_revision=workflow.revision,
            topic_id=decision.topic_id,
            topic_kind=decision.topic_kind,
            topic_title=decision.topic_title,
            topic_objective=decision.topic_objective,
            candidate_count=(1 if proposal_mode == "single_plan" else decision.candidate_count),
            proposal_mode=proposal_mode,
            user_instruction=user_instruction,
            goal=session.goal,
            relevant_decisions=tuple(
                item
                for item in session.element_decisions
                if item.element_kind in {decision.topic_kind, "product", "scene"}
            ),
            style_excerpt=style_excerpt,
            style_guidance=style_guidance,
            accepted_anchors=accepted_anchors,
            image_references=tuple(_image_reference(asset) for asset in image_assets),
            relevant_nodes=tuple(_node_summary(node) for node in relevant_nodes),
            relevant_bindings=tuple(_binding_summary(binding) for binding in relevant_bindings),
            targeted_prompt_baseline=targeted_prompt_baseline,
            world_setting=world_setting,
        )

    def build_delegated_choice(
        self,
        proposal: ConceptProposalV2,
        *,
        session: GuidedSessionStateV2,
        style_summary: str,
        image_assets: tuple[ProjectAssetSummaryV2, ...] = (),
    ) -> DelegatedProposalChoiceContextV2:
        references = tuple(_image_reference(asset) for asset in image_assets)
        return DelegatedProposalChoiceContextV2(
            context_kind="delegated_proposal_choice",
            workflow_id=proposal.workflow_id,
            proposal_id=proposal.proposal_id,
            proposal_revision=proposal.proposal_revision,
            goal=session.goal,
            relevant_decisions=session.element_decisions,
            options=tuple(
                DelegatedProposalOptionSummaryV2(
                    option_id=option.option_id,
                    title=option.title,
                    summary=option.summary_prompt,
                    displayed_references=references,
                )
                for option in proposal.options
            ),
            style_summary=style_summary,
        )


def _node_summary(node) -> GuidanceNodeSummaryV2:
    return GuidanceNodeSummaryV2(
        node_id=node.node_id,
        node_type=node.node_type,
        title=node.title,
        status=node.status,
        semantic_purpose=node.summary_prompt or node.creative_role,
    )


def _stage_policy(workflow, *, session, creation_mode):
    policy = GuidanceStagePolicyV2()
    if creation_mode != "guided_production":
        return policy.unrestricted()
    if session is None:
        from app.schemas.agent_canvas_creative_session import GuidanceStagePolicyResultV2

        return GuidanceStagePolicyResultV2(
            allowed_stage_kinds=("world_setting",),
            recommended_stage_kinds=("world_setting",),
            blocking_facts=("world_setting_required",),
            completion_allowed=False,
        )
    stage_by_role = {
        "world_setting": "world_setting",
        "script": "script",
        "product": "product",
        "prop": "prop",
        "character": "character",
        "scene": "scene",
        "storyboard_sequence": "storyboard",
        "storyboard_video": "video",
        "bgm": "bgm",
        "editing": "editing",
    }
    existing = {
        stage_by_role[node.creative_role]
        for node in workflow.nodes
        if node.creative_role in stage_by_role
    }
    existing.update(
        "bgm" if topic.topic_kind == "audio" else topic.topic_kind
        for topic in session.topics
        if topic.status == "selected" and topic.topic_kind != "creative_direction"
    )
    return policy.evaluate(
        session=session,
        existing_stage_kinds=tuple(existing),
    )


def _binding_summary(binding) -> GuidanceBindingSummaryV2:
    source_id = getattr(binding.source, "source_node_id", None) or getattr(
        binding.source,
        "source_asset_id",
        None,
    )
    return GuidanceBindingSummaryV2(
        binding_id=binding.binding_id,
        source_id=source_id,
        target_node_id=binding.target_node_id,
        input_role=binding.input_role,
        required=binding.required,
    )


def _image_reference(asset: ProjectAssetSummaryV2) -> GuidanceImageReferenceV2:
    if asset.media_type != "image" or asset.status != "ready" or not asset.media_url:
        raise _context_error("Guidance references must be Ready project images.")
    return GuidanceImageReferenceV2(
        asset_id=asset.asset_id,
        display_name=asset.display_name,
        media_url=asset.media_url,
        semantic_purpose=asset.source_semantic_role or "image_reference",
    )


def _context_error(message: str) -> V2PersistenceError:
    return V2PersistenceError(
        "specialist_context_invalid",
        message,
        stage="guidance_context_builder",
    )
