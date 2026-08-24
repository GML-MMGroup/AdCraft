"""Closed operation registry for the single production Video Agent."""

from __future__ import annotations

from types import MappingProxyType

from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_capabilities import (
    AgentCapabilityContractV1,
    VideoAgentOperationDefinitionV1,
)


class VideoAgentOperationRegistryError(ValueError):
    """A Video Agent operation or capability mapping is not registered."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_CAPABILITIES: tuple[tuple[CapabilityIdV1, str, str, str, str, str], ...] = (
    (
        "world_setting",
        "world_setting",
        "ProposalCardResultV2",
        "video_agent_world_setting",
        "world_setting",
        "World Setting Designer",
    ),
    (
        "product_design",
        "product",
        "ProposalCardResultV2",
        "video_agent_product_design",
        "product",
        "Product Designer",
    ),
    (
        "prop_design",
        "prop",
        "ProposalCardResultV2",
        "video_agent_prop_design",
        "prop",
        "Prop Designer",
    ),
    (
        "character_design",
        "character",
        "ProposalCardResultV2",
        "video_agent_character_design",
        "character",
        "Character Designer",
    ),
    (
        "scene_design",
        "scene",
        "ProposalCardResultV2",
        "video_agent_scene_design",
        "scene",
        "Scene Designer",
    ),
    (
        "script_authoring",
        "script",
        "ProposalCardResultV2",
        "video_agent_script_authoring",
        "script",
        "Script Writer",
    ),
    (
        "storyboard_design",
        "storyboard",
        "ProposalCardResultV2",
        "video_agent_storyboard_design",
        "storyboard",
        "Storyboard Artist",
    ),
    (
        "video_direction",
        "video",
        "ProposalCardResultV2",
        "video_agent_video_direction",
        "video",
        "Video Director",
    ),
    (
        "bgm_direction",
        "bgm",
        "ProposalCardResultV2",
        "video_agent_bgm_direction",
        "bgm",
        "BGM Director",
    ),
)


def _definition(
    operation: str,
    context_contract_name: str,
    result_contract_name: str,
    *,
    capability_id: CapabilityIdV1 | None = None,
    internal_skill_id: str | None = None,
    style_projection_role: str | None = None,
    display_name: str | None = None,
    validation_profile: str | None = None,
) -> VideoAgentOperationDefinitionV1:
    return VideoAgentOperationDefinitionV1(
        operation=operation,
        capability_id=capability_id,
        internal_skill_id=internal_skill_id,
        style_projection_role=style_projection_role,
        context_contract_name=context_contract_name,
        result_contract_name=result_contract_name,
        display_name=display_name,
        validation_profile=validation_profile,
    )


def _capability_definitions() -> tuple[VideoAgentOperationDefinitionV1, ...]:
    definitions: list[VideoAgentOperationDefinitionV1] = []
    for capability_id, operation_stem, contract, skill, style_role, display in _CAPABILITIES:
        for prefix in ("propose", "revise"):
            definitions.append(
                _definition(
                    f"{prefix}_{operation_stem}_options",
                    "CapabilityInvocationContextV2",
                    contract,
                    capability_id=capability_id,
                    internal_skill_id=skill,
                    style_projection_role=style_role,
                    display_name=display,
                    validation_profile="proposal_candidate_count_v1",
                )
            )
    return tuple(definitions)


_DEFINITIONS: tuple[VideoAgentOperationDefinitionV1, ...] = (
    _definition("decide_turn_intent", "TurnIntentContextV2", "CompactTurnIntentDecisionV3"),
    _definition("decide_next_action", "NextActionContextV1", "NextActionCommandV1"),
    _definition("command_replan", "AgentCommandReplanContextV2", "AgentCommandPlanDraftV2"),
    _definition(
        "workflow_conversation",
        "WorkflowConversationAgentContext",
        "WorkflowConversationReply",
    ),
    _definition(
        "conversation_summary",
        "ConversationSummaryAgentContext",
        "ConversationSummaryResult",
    ),
    _definition("author_decision_bundle", "NextActionContextV1", "DecisionBundleDraftV1"),
    _definition(
        "author_role_brief",
        "RolePromptPreparationContextV2",
        "RoleCreativeBriefV2",
        internal_skill_id="video_agent_role_prompt_authoring",
        display_name="Role Prompt Author",
    ),
    _definition(
        "plan_storyboard_sequence_outline",
        "CapabilityMaterializationContextV1",
        "StoryboardSequenceOutlineDraftV2",
        capability_id="storyboard_design",
        internal_skill_id="video_agent_storyboard_design",
        style_projection_role="storyboard",
        display_name="Storyboard Artist",
    ),
    _definition(
        "materialize_storyboard_segment",
        "StoryboardSegmentAuthoringContextV2",
        "StoryboardSegmentMaterializationDraftV2",
        capability_id="storyboard_design",
        internal_skill_id="video_agent_storyboard_design",
        style_projection_role="storyboard",
        display_name="Storyboard Artist",
    ),
    _definition(
        "author_guided_script_checkpoint",
        "CapabilityInvocationContextV2",
        "ScriptMaterializationResultV1",
        capability_id="script_authoring",
        internal_skill_id="video_agent_script_authoring",
        style_projection_role="script",
        display_name="Script Writer",
    ),
    *_capability_definitions(),
    _definition(
        "free_image",
        "QuickMediaAgentContext",
        "V2QuickMediaPromptPlan",
        capability_id="quick_media",
        internal_skill_id="video_agent_quick_media",
        style_projection_role="quick_media",
        display_name="Quick Media",
    ),
    _definition(
        "free_video",
        "QuickMediaAgentContext",
        "V2QuickMediaPromptPlan",
        capability_id="quick_media",
        internal_skill_id="video_agent_quick_media",
        style_projection_role="quick_media",
        display_name="Quick Media",
    ),
    _definition(
        "free_audio",
        "QuickMediaAgentContext",
        "V2QuickMediaPromptPlan",
        capability_id="quick_media",
        internal_skill_id="video_agent_quick_media",
        style_projection_role="quick_media",
        display_name="Quick Media",
    ),
    _definition(
        "materialize_quick_media",
        "CapabilityMaterializationContextV1",
        "QuickMediaMaterializationResultV1",
        capability_id="quick_media",
        internal_skill_id="video_agent_quick_media",
        style_projection_role="quick_media",
        display_name="Quick Media",
    ),
    _definition("execute_canvas_text", "AgentRunContext", "AgentCanvasTextOutput"),
    _definition(
        "execute_canvas_script",
        "AgentRunContext",
        "AgentCanvasScriptOutput",
        capability_id="script_authoring",
        internal_skill_id="video_agent_script_authoring",
        style_projection_role="script",
        display_name="Script Writer",
    ),
    _definition(
        "compile_video_parameters",
        "VideoParameterIntentContextV3",
        "VideoParameterIntentV3",
        capability_id="video_direction",
        internal_skill_id="video_agent_video_direction",
        style_projection_role="video",
        display_name="Video Director",
    ),
    _definition("workflow_creation", "FrontDeskIntentAgentContext", "FrontDeskIntentOutput"),
    _definition("intent_contract_planner", "IntentContractAgentContext", "V2IntentPlan"),
    _definition(
        "script_writer",
        "ScriptWriterAgentContext",
        "V2ScriptPlanV2",
        capability_id="script_authoring",
        internal_skill_id="video_agent_script_authoring",
        style_projection_role="script",
        display_name="Script Writer",
    ),
    _definition(
        "script_edit_normalization",
        "AgentRunContext",
        "V2EditableScriptDocument",
        capability_id="script_authoring",
        internal_skill_id="video_agent_script_authoring",
        style_projection_role="script",
        display_name="Script Writer",
    ),
    _definition(
        "product_expert_brief",
        "ProductExpertAgentContext",
        "V2ProductExpertPlan",
        capability_id="product_design",
        internal_skill_id="video_agent_product_design",
        style_projection_role="product",
        display_name="Product Designer",
    ),
    _definition(
        "character_expert_brief",
        "CharacterExpertAgentContext",
        "V2CharacterExpertPlan",
        capability_id="character_design",
        internal_skill_id="video_agent_character_design",
        style_projection_role="character",
        display_name="Character Designer",
    ),
    _definition(
        "scene_expert_brief",
        "SceneExpertAgentContext",
        "V2SceneExpertPlan",
        capability_id="scene_design",
        internal_skill_id="video_agent_scene_design",
        style_projection_role="scene",
        display_name="Scene Designer",
    ),
    _definition(
        "bgm_expert_brief",
        "BgmExpertAgentContext",
        "V2BgmExpertPlan",
        capability_id="bgm_direction",
        internal_skill_id="video_agent_bgm_direction",
        style_projection_role="bgm",
        display_name="BGM Director",
    ),
    _definition(
        "product_prompt",
        "AgentRunContext",
        "V2ProductPromptPlan",
        capability_id="product_design",
        internal_skill_id="video_agent_product_design",
        style_projection_role="product",
        display_name="Product Designer",
    ),
    _definition(
        "character_prompt",
        "AgentRunContext",
        "V2CharacterPromptPlan",
        capability_id="character_design",
        internal_skill_id="video_agent_character_design",
        style_projection_role="character",
        display_name="Character Designer",
    ),
    _definition(
        "scene_prompt",
        "AgentRunContext",
        "V2ScenePromptPlan",
        capability_id="scene_design",
        internal_skill_id="video_agent_scene_design",
        style_projection_role="scene",
        display_name="Scene Designer",
    ),
    _definition(
        "storyboard_prompt",
        "AgentRunContext",
        "V2ShotCellPromptPlan",
        capability_id="storyboard_design",
        internal_skill_id="video_agent_storyboard_design",
        style_projection_role="storyboard",
        display_name="Storyboard Artist",
    ),
    _definition(
        "storyboard_detail",
        "AgentRunContext",
        "V2StoryboardDetailPlan",
        capability_id="storyboard_design",
        internal_skill_id="video_agent_storyboard_design",
        style_projection_role="storyboard",
        display_name="Storyboard Artist",
    ),
    _definition(
        "shot_video_prompt",
        "AgentRunContext",
        "V2ShotVideoPromptPlan",
        capability_id="video_direction",
        internal_skill_id="video_agent_video_direction",
        style_projection_role="video",
        display_name="Video Director",
    ),
    _definition(
        "bgm_prompt",
        "AgentRunContext",
        "V2BgmPromptPlan",
        capability_id="bgm_direction",
        internal_skill_id="video_agent_bgm_direction",
        style_projection_role="bgm",
        display_name="BGM Director",
    ),
    _definition(
        "visual_style_scope_repair",
        "AgentRunContext",
        "V2VisualStyleScopeRepairOutput",
        capability_id="world_setting",
        internal_skill_id="video_agent_world_setting",
        style_projection_role="world_setting",
        display_name="World Setting Designer",
    ),
    _definition(
        "revise_character_asset",
        "AgentRunContext",
        "SpecialistResult",
        capability_id="character_design",
        internal_skill_id="video_agent_character_design",
        style_projection_role="character",
        display_name="Character Designer",
    ),
    _definition(
        "revise_scene_asset",
        "AgentRunContext",
        "SpecialistResult",
        capability_id="scene_design",
        internal_skill_id="video_agent_scene_design",
        style_projection_role="scene",
        display_name="Scene Designer",
    ),
)


class VideoAgentOperationRegistry:
    """Resolve exact operation metadata without identity or Skill fallback."""

    def __init__(self) -> None:
        by_operation = {definition.operation: definition for definition in _DEFINITIONS}
        if len(by_operation) != len(_DEFINITIONS):
            raise VideoAgentOperationRegistryError(
                "agent_operation_registry_invalid",
                "Video Agent operations must be unique.",
            )
        self._by_operation = MappingProxyType(by_operation)
        self._capability_operations = MappingProxyType(
            {
                capability_id: (
                    self._by_operation[f"propose_{operation_stem}_options"],
                    self._by_operation[f"revise_{operation_stem}_options"],
                )
                for capability_id, operation_stem, *_ in _CAPABILITIES
            }
        )

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_operation)

    def definitions(self) -> tuple[VideoAgentOperationDefinitionV1, ...]:
        return tuple(self._by_operation.values())

    def resolve(self, operation: str) -> VideoAgentOperationDefinitionV1:
        try:
            return self._by_operation[operation]
        except KeyError as error:
            raise VideoAgentOperationRegistryError(
                "agent_operation_not_allowed",
                "Video Agent operation is not registered.",
            ) from error

    def validate_capability_contract(self, contract: AgentCapabilityContractV1) -> None:
        if len(contract.agents) != 1:
            self._invalid_contract()
        agent = contract.agents[0]
        if (
            agent.name != "video_agent"
            or agent.model_role != "agent"
            or set(agent.operations) != set(self._by_operation)
        ):
            self._invalid_contract()

    def for_capability(
        self,
        capability_id: CapabilityIdV1,
        *,
        revision: bool = False,
    ) -> VideoAgentOperationDefinitionV1:
        try:
            proposed, revised = self._capability_operations[capability_id]
        except KeyError as error:
            raise VideoAgentOperationRegistryError(
                "agent_operation_not_allowed",
                "Capability does not use the Proposal operation boundary.",
            ) from error
        return revised if revision else proposed

    @staticmethod
    def _invalid_contract() -> None:
        raise VideoAgentOperationRegistryError(
            "agent_operation_registry_invalid",
            "Agent capability contract does not match the Video Agent operation registry.",
        )
