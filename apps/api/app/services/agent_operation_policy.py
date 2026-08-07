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
    "conversation_turn",
    "decide_next_guidance_step",
    "direct_response",
    "proposal_action",
    "resolve_creation_mode",
}
_PROPOSAL_OPERATIONS = {
    "propose_concepts",
    "propose_world_setting",
    "revise_concepts",
    "revise_world_setting_options",
}
_MATERIALIZATION_OPERATIONS = {
    "execute_canvas_text",
    "materialize_draft",
    "materialize_world_setting",
}
_LONG_FORM_OPERATIONS = {"execute_canvas_script"}


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
        fallback_class = "none"
        if policy_class == "materialization":
            if operation == "materialize_world_setting":
                fallback_class = "selected_world_setting"
            elif operation == "materialize_draft":
                fallback_class = "selected_media_draft"
        return AgentOperationPolicyV2(
            policy_id=f"agent.{policy_class}.v1",
            agent_name=agent_name,
            operation=operation,
            contract_id=contract_id,
            policy_class=policy_class,
            hard_deadline_seconds=self._deadlines[policy_class],
            fallback_class=fallback_class,
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
    if operation == "materialize_draft" and agent_name == "script_writer":
        return "long_form"
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
