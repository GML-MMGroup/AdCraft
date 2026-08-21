"""Deterministic capability ownership and routing policy for Agent Canvas."""

from __future__ import annotations

from dataclasses import dataclass

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_capabilities import (
    CapabilityDefinitionV1,
    CapabilityIdV1,
    CapabilityPolicyContextV1,
    CapabilityPolicyResultV1,
    NextActionCommandV1,
    ValidatedNextActionV1,
)
from app.schemas.agent_canvas_creative_session import CreativeElementDecisionV2


_DEFINITIONS: tuple[CapabilityDefinitionV1, ...] = (
    CapabilityDefinitionV1(
        capability_id="world_setting",
        display_name="World Setting",
        operation="propose_world_setting_options",
        result_contract_name="WorldSettingProposalResultV1",
        node_type="text",
        creative_role="world_setting",
        default_candidate_count=3,
    ),
    CapabilityDefinitionV1(
        capability_id="product_design",
        display_name="Product Designer",
        operation="propose_product_options",
        result_contract_name="ProductProposalResultV1",
        node_type="image",
        creative_role="product",
        default_candidate_count=3,
        allowed_reference_roles=("world_setting_reference", "style_reference"),
    ),
    CapabilityDefinitionV1(
        capability_id="prop_design",
        display_name="Prop Designer",
        operation="propose_prop_options",
        result_contract_name="PropProposalResultV1",
        node_type="image",
        creative_role="prop",
        default_candidate_count=3,
        allowed_reference_roles=(
            "world_setting_reference",
            "product_reference",
            "style_reference",
        ),
    ),
    CapabilityDefinitionV1(
        capability_id="character_design",
        display_name="Character Designer",
        operation="propose_character_options",
        result_contract_name="CharacterProposalResultV1",
        node_type="image",
        creative_role="character",
        default_candidate_count=3,
        allowed_reference_roles=("world_setting_reference", "style_reference"),
    ),
    CapabilityDefinitionV1(
        capability_id="scene_design",
        display_name="Scene Designer",
        operation="propose_scene_options",
        result_contract_name="SceneProposalResultV1",
        node_type="image",
        creative_role="scene",
        default_candidate_count=3,
        allowed_reference_roles=(
            "world_setting_reference",
            "style_reference",
        ),
    ),
    CapabilityDefinitionV1(
        capability_id="script_authoring",
        display_name="Script Writer",
        operation="propose_script_options",
        result_contract_name="ScriptProposalResultV1",
        node_type="script",
        creative_role="script",
        default_candidate_count=3,
        allowed_reference_roles=("world_setting_reference",),
    ),
    CapabilityDefinitionV1(
        capability_id="storyboard_design",
        display_name="Storyboard Artist",
        operation="propose_storyboard_options",
        result_contract_name="StoryboardProposalResultV1",
        node_type="image",
        creative_role="storyboard_sequence",
        default_candidate_count=3,
        allowed_reference_roles=(
            "world_setting_reference",
            "subject_reference",
            "environment_reference",
            "product_reference",
            "prop_reference",
            "style_reference",
        ),
    ),
    CapabilityDefinitionV1(
        capability_id="video_direction",
        display_name="Video Director",
        operation="propose_video_options",
        result_contract_name="VideoProposalResultV1",
        node_type="video",
        creative_role="storyboard_video",
        default_candidate_count=3,
        allowed_reference_roles=(
            "world_setting_reference",
            "storyboard_visual_reference",
            "subject_reference",
            "environment_reference",
            "product_reference",
            "prop_reference",
        ),
    ),
    CapabilityDefinitionV1(
        capability_id="bgm_direction",
        display_name="BGM Director",
        operation="propose_bgm_options",
        result_contract_name="BgmProposalResultV1",
        node_type="audio",
        creative_role="bgm",
        default_candidate_count=3,
        allowed_reference_roles=("world_setting_reference", "style_reference"),
    ),
    CapabilityDefinitionV1(
        capability_id="quick_media",
        display_name="Quick Media Agent",
        operation="propose_quick_media",
        result_contract_name="QuickMediaProposalResultV1",
        node_type=None,
        creative_role=None,
        default_candidate_count=1,
        allowed_reference_roles=(
            "subject_reference",
            "environment_reference",
            "style_reference",
        ),
    ),
)

_GUIDED_CAPABILITIES: tuple[CapabilityIdV1, ...] = tuple(
    definition.capability_id
    for definition in _DEFINITIONS
    if definition.capability_id != "quick_media"
)

_ELEMENT_CAPABILITIES: dict[str, CapabilityIdV1] = {
    "world_setting": "world_setting",
    "product": "product_design",
    "prop": "prop_design",
    "character": "character_design",
    "scene": "scene_design",
    "script": "script_authoring",
    "storyboard": "storyboard_design",
    "video": "video_direction",
    "audio": "bgm_direction",
}


@dataclass(frozen=True)
class CapabilityRequirementFacts:
    required: tuple[CapabilityIdV1, ...]
    optional: tuple[CapabilityIdV1, ...]
    excluded: tuple[CapabilityIdV1, ...]


def derive_capability_requirement_facts(
    decisions: tuple[CreativeElementDecisionV2, ...],
) -> CapabilityRequirementFacts:
    buckets: dict[str, list[CapabilityIdV1]] = {
        "include": [],
        "unspecified": [],
        "exclude": [],
    }
    for decision in decisions:
        capability_id = _ELEMENT_CAPABILITIES.get(decision.element_kind)
        if capability_id is not None and capability_id not in buckets[decision.presence]:
            buckets[decision.presence].append(capability_id)
    return CapabilityRequirementFacts(
        required=tuple(buckets["include"]),
        optional=tuple(buckets["unspecified"]),
        excluded=tuple(buckets["exclude"]),
    )


class CapabilityPolicyService:
    """Own stable capability definitions and evaluate current allowed actions."""

    def __init__(self) -> None:
        self._definitions = {definition.capability_id: definition for definition in _DEFINITIONS}

    @property
    def capability_ids(self) -> tuple[CapabilityIdV1, ...]:
        return tuple(definition.capability_id for definition in _DEFINITIONS)

    def definition(self, capability_id: CapabilityIdV1) -> CapabilityDefinitionV1:
        return self._definitions[capability_id]

    @staticmethod
    def internal_script_checkpoint_definition() -> CapabilityDefinitionV1:
        return CapabilityDefinitionV1(
            capability_id="script_authoring",
            display_name="Script Writer",
            operation="author_guided_script_checkpoint",
            result_contract_name="ScriptMaterializationResultV1",
            node_type=None,
            creative_role=None,
            default_candidate_count=1,
            allowed_reference_roles=("world_setting_reference",),
        )

    def evaluate(self, context: CapabilityPolicyContextV1) -> CapabilityPolicyResultV1:
        if context.journey_capability is not None:
            unavailable = {
                *context.open_proposal_capabilities,
                *context.active_materialization_capabilities,
            }
            allowed = (
                () if context.journey_capability in unavailable else (context.journey_capability,)
            )
            return CapabilityPolicyResultV1(
                allowed_capabilities=allowed,
                recommended_capabilities=allowed,
                completion_allowed=False,
                blocking_facts=(
                    () if allowed else (f"journey_capability_busy:{context.journey_capability}",)
                ),
            )
        if context.targeted_capability is not None:
            hard_unavailable = {
                *context.completed_capabilities,
                *context.excluded_capabilities,
                *context.open_proposal_capabilities,
                *context.active_materialization_capabilities,
            }
            allowed = (
                ()
                if context.targeted_capability in hard_unavailable
                else (context.targeted_capability,)
            )
            return CapabilityPolicyResultV1(
                allowed_capabilities=allowed,
                recommended_capabilities=allowed,
                completion_allowed=False,
                targeted_resume=(
                    bool(allowed) and context.targeted_capability in context.deferred_capabilities
                ),
            )

        unavailable = {
            *context.completed_capabilities,
            *context.excluded_capabilities,
            *context.open_proposal_capabilities,
            *context.active_materialization_capabilities,
            *context.deferred_capabilities,
        }
        eligible = (
            context.required_capabilities if context.required_capabilities else _GUIDED_CAPABILITIES
        )
        allowed = tuple(capability for capability in eligible if capability not in unavailable)
        required_missing = tuple(
            capability
            for capability in context.required_capabilities
            if capability not in context.completed_capabilities
            and capability not in context.excluded_capabilities
        )
        required_deferred = tuple(
            capability
            for capability in _GUIDED_CAPABILITIES
            if capability in required_missing
            and capability in context.deferred_capabilities
            and capability not in context.open_proposal_capabilities
            and capability not in context.active_materialization_capabilities
        )
        completion_allowed = (
            not required_missing
            and bool(context.completed_capabilities)
            and not context.open_proposal_capabilities
            and not context.active_materialization_capabilities
        )
        return CapabilityPolicyResultV1(
            allowed_capabilities=allowed,
            recommended_capabilities=allowed,
            completion_allowed=completion_allowed,
            blocking_facts=tuple(
                f"required_capability_missing:{capability}" for capability in required_missing
            ),
            required_deferred_capabilities=required_deferred,
        )

    def validate_next_action(
        self,
        command: NextActionCommandV1,
        policy: CapabilityPolicyResultV1,
    ) -> ValidatedNextActionV1:
        if command.action == "invoke_capability":
            if command.capability_id not in policy.allowed_capabilities:
                raise V2PersistenceError(
                    "next_action_application_failed",
                    "The requested capability is not allowed in the current state.",
                    stage="capability_policy",
                )
            assert command.capability_id is not None
            return ValidatedNextActionV1(
                command=command,
                definition=self.definition(command.capability_id),
                source_action=("user_resumed_deferred_topic" if policy.targeted_resume else None),
            )
        if command.action == "finish" and policy.required_deferred_capabilities:
            capability_id = policy.required_deferred_capabilities[0]
            redirected = NextActionCommandV1(
                action="invoke_capability",
                capability_id=capability_id,
                objective=(
                    "Revisit this deferred capability because it remains required "
                    "by the accepted brief."
                ),
            )
            return ValidatedNextActionV1(
                command=redirected,
                definition=self.definition(capability_id),
                source_action="required_deferred_final_review",
            )
        if command.action == "finish" and not policy.completion_allowed:
            raise V2PersistenceError(
                "next_action_application_failed",
                "The current guidance state is not complete.",
                stage="capability_policy",
            )
        return ValidatedNextActionV1(command=command)
