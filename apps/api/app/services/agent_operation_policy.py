"""Installation-scoped hard-deadline policies for production Agent operations."""

from __future__ import annotations

from collections.abc import Mapping

from app.schemas.agent_operation_recovery import (
    AgentOperationPolicyClassV2,
    AgentOperationPolicyV2,
)
from app.services.v2_agent_capability_contract import V2AgentCapabilityContractService


_DEADLINES: Mapping[AgentOperationPolicyClassV2, int] = {
    "routing": 180,
    "proposal": 300,
    "materialization": 420,
    "long_form": 600,
}
_ROUTING_OPERATIONS = {
    "command_replan",
    "compile_video_parameters",
    "conversation_summary",
    "decide_next_action",
    "decide_turn_intent",
    "intent_contract_planner",
    "visual_style_scope_repair",
    "workflow_conversation",
    "workflow_creation",
}
_PROPOSAL_OPERATIONS = {
    "bgm_expert_brief",
    "bgm_prompt",
    "character_expert_brief",
    "character_prompt",
    "free_audio",
    "free_image",
    "free_video",
    "product_expert_brief",
    "product_prompt",
    "propose_bgm_options",
    "propose_character_options",
    "propose_product_options",
    "propose_prop_options",
    "propose_scene_options",
    "propose_script_options",
    "propose_storyboard_options",
    "propose_video_options",
    "propose_world_setting_options",
    "revise_bgm_options",
    "revise_character_asset",
    "revise_character_options",
    "revise_product_options",
    "revise_prop_options",
    "revise_scene_asset",
    "revise_scene_options",
    "revise_script_options",
    "revise_storyboard_options",
    "revise_video_options",
    "revise_world_setting_options",
    "scene_expert_brief",
    "scene_prompt",
    "shot_video_prompt",
    "storyboard_prompt",
}
_MATERIALIZATION_OPERATIONS = {
    "execute_canvas_text",
    "materialize_quick_media",
}
_LONG_FORM_OPERATIONS = {
    "execute_canvas_script",
    "script_edit_normalization",
    "script_writer",
    "storyboard_detail",
}


class AgentOperationPolicyError(ValueError):
    """A production Agent operation has no unambiguous policy."""


class AgentOperationPolicyRegistryV2:
    def __init__(
        self,
        *,
        deadline_overrides: Mapping[AgentOperationPolicyClassV2, int] | None = None,
    ) -> None:
        self._deadlines = {**_DEADLINES, **(deadline_overrides or {})}
        self._capabilities = V2AgentCapabilityContractService().load()
        errors = self.validate_production_operations()
        if errors:
            raise AgentOperationPolicyError("agent_operation_policy_invalid:" + ",".join(errors))

    def resolve(
        self,
        *,
        agent_name: str,
        operation: str,
        contract_id: str,
    ) -> AgentOperationPolicyV2:
        capability = next(
            (item for item in self._capabilities.agents if item.name == agent_name),
            None,
        )
        if capability is None or operation not in capability.operations:
            raise AgentOperationPolicyError("agent_operation_policy_unknown")
        policy_class = _policy_class(
            agent_name=agent_name,
            operation=operation,
            contract_id=contract_id,
        )
        return AgentOperationPolicyV2(
            policy_id=f"agent.{policy_class}.v1",
            agent_name=agent_name,
            operation=operation,
            contract_id=contract_id,
            policy_class=policy_class,
            hard_deadline_seconds=self._deadlines[policy_class],
            fallback_class="none",
        )

    def validate_production_operations(self) -> tuple[str, ...]:
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        for capability in self._capabilities.agents:
            for operation in capability.operations:
                identity = (capability.name, operation)
                if identity in seen:
                    errors.append(f"{capability.name}:{operation}:duplicate")
                    continue
                seen.add(identity)
                try:
                    _policy_class(
                        agent_name=capability.name,
                        operation=operation,
                        contract_id="CapabilityContract",
                    )
                except AgentOperationPolicyError:
                    errors.append(f"{capability.name}:{operation}")
        return tuple(errors)


def _policy_class(
    *,
    agent_name: str,
    operation: str,
    contract_id: str,
) -> AgentOperationPolicyClassV2:
    if contract_id in {"ScriptSpecialistDraftV2", "StoryboardProductionPlanContentV2"}:
        return "long_form"
    if operation in _ROUTING_OPERATIONS:
        return "routing"
    if operation in _PROPOSAL_OPERATIONS:
        return "proposal"
    if operation in _MATERIALIZATION_OPERATIONS:
        return "materialization"
    if operation in _LONG_FORM_OPERATIONS:
        return "long_form"
    raise AgentOperationPolicyError("agent_operation_policy_unknown")
