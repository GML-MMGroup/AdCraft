"""Installation-scoped hard-deadline policies for production Agent operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.schemas.agent_operation_recovery import (
    AgentOperationPolicyClassV2,
    AgentOperationPolicyV2,
)
from app.schemas.agent_runtime import AgentRunRequest
from app.services.v2_agent_capability_contract import V2AgentCapabilityContractService
from app.services.video_agent_operation_registry import VideoAgentOperationRegistry


@dataclass(frozen=True)
class _OperationBudget:
    hard_deadline_seconds: int
    primary_timeout_seconds: int
    recovery_timeout_seconds: int
    persistence_reserve_seconds: int
    max_output_tokens: int
    thinking_budget_tokens: int | None


_CLASS_BUDGETS: Mapping[AgentOperationPolicyClassV2, _OperationBudget] = {
    "routing": _OperationBudget(180, 110, 50, 20, 1_024, None),
    "proposal": _OperationBudget(300, 190, 80, 30, 3_072, 2_048),
    "materialization": _OperationBudget(420, 270, 120, 30, 4_096, 3_072),
    "long_form": _OperationBudget(600, 390, 180, 30, 8_192, 4_096),
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
    "author_decision_bundle",
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
    "materialize_storyboard_segment",
    "materialize_quick_media",
}
_LONG_FORM_OPERATIONS = {
    "execute_canvas_script",
    "script_edit_normalization",
    "script_writer",
    "storyboard_detail",
    "plan_storyboard_sequence_outline",
}


class AgentOperationPolicyError(ValueError):
    """A production Agent operation has no unambiguous policy."""


class AgentOperationPolicyRegistryV2:
    def __init__(
        self,
        *,
        deadline_overrides: Mapping[AgentOperationPolicyClassV2, int] | None = None,
    ) -> None:
        invalid_overrides = {
            policy_class: seconds
            for policy_class, seconds in (deadline_overrides or {}).items()
            if seconds != _CLASS_BUDGETS[policy_class].hard_deadline_seconds
        }
        if invalid_overrides:
            raise AgentOperationPolicyError("agent_operation_policy_invalid:deadline_override")
        self._budgets = {
            policy_class: _OperationBudget(
                hard_deadline_seconds=budget.hard_deadline_seconds,
                primary_timeout_seconds=budget.primary_timeout_seconds,
                recovery_timeout_seconds=budget.recovery_timeout_seconds,
                persistence_reserve_seconds=budget.persistence_reserve_seconds,
                max_output_tokens=budget.max_output_tokens,
                thinking_budget_tokens=budget.thinking_budget_tokens,
            )
            for policy_class, budget in _CLASS_BUDGETS.items()
        }
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
        if agent_name == "video_agent" and operation == "decide_turn_intent":
            return AgentOperationPolicyV2(
                policy_id="video_agent.decide_turn_intent.v3",
                agent_name=agent_name,
                operation=operation,
                contract_id=contract_id,
                policy_class="routing",
                hard_deadline_seconds=300,
                primary_timeout_seconds=240,
                recovery_timeout_seconds=55,
                persistence_reserve_seconds=5,
                max_output_tokens=2_048,
                reasoning_mode="low",
                enable_thinking=False,
                thinking_budget_tokens=None,
                transport_retry_limit=0,
                structured_repair_limit=1,
                max_model_submissions=2,
                recovery_mode="structured_repair_only",
                fallback_class="none",
            )
        policy_class = _policy_class(
            agent_name=agent_name,
            operation=operation,
            contract_id=contract_id,
        )
        budget = self._budgets[policy_class]
        return AgentOperationPolicyV2(
            policy_id=f"agent.{policy_class}.v1",
            agent_name=agent_name,
            operation=operation,
            contract_id=contract_id,
            policy_class=policy_class,
            hard_deadline_seconds=budget.hard_deadline_seconds,
            primary_timeout_seconds=budget.primary_timeout_seconds,
            recovery_timeout_seconds=budget.recovery_timeout_seconds,
            persistence_reserve_seconds=budget.persistence_reserve_seconds,
            max_output_tokens=budget.max_output_tokens,
            reasoning_mode="low" if policy_class == "routing" else "deep",
            enable_thinking=policy_class != "routing",
            thinking_budget_tokens=budget.thinking_budget_tokens,
            max_model_submissions=2,
            recovery_mode="transport_retry_or_structured_repair",
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


def freeze_agent_run_operation_policy(
    request: AgentRunRequest,
    *,
    now: datetime | None = None,
    registry: AgentOperationPolicyRegistryV2 | None = None,
) -> AgentRunRequest:
    """Freeze the canonical policy into a durable request before persistence."""

    definition = VideoAgentOperationRegistry().resolve(request.operation)
    operation_policy = (registry or AgentOperationPolicyRegistryV2()).resolve(
        agent_name=request.agent_name,
        operation=request.operation,
        contract_id=request.contract_name or definition.result_contract_name,
    )
    run_policy = request.policy.model_copy(
        update={
            "operation_policy_id": operation_policy.policy_id,
            "operation_class": operation_policy.policy_class,
            "transport_retry_limit": operation_policy.transport_retry_limit,
            "structured_repair_limit": operation_policy.structured_repair_limit,
            "timeout_seconds": float(operation_policy.hard_deadline_seconds),
            "primary_timeout_seconds": operation_policy.primary_timeout_seconds,
            "recovery_timeout_seconds": operation_policy.recovery_timeout_seconds,
            "persistence_reserve_seconds": operation_policy.persistence_reserve_seconds,
            "max_model_submissions": operation_policy.max_model_submissions,
            "recovery_mode": operation_policy.recovery_mode,
            "max_output_tokens": operation_policy.max_output_tokens,
            "reasoning_mode": operation_policy.reasoning_mode,
            "enable_thinking": operation_policy.enable_thinking,
            "thinking_budget_tokens": operation_policy.thinking_budget_tokens,
        }
    )
    timestamp = now or datetime.now(timezone.utc)
    policy_deadline = timestamp + timedelta(seconds=operation_policy.hard_deadline_seconds)
    return request.model_copy(
        update={
            "deadline_at": min(request.deadline_at, policy_deadline),
            "policy": run_policy,
            "audit_metadata": {
                **request.audit_metadata,
                "agent_operation_policy": operation_policy.model_dump(mode="json"),
                "agent_run_policy": run_policy.model_dump(mode="json"),
            },
        }
    )


def _policy_class(
    *,
    agent_name: str,
    operation: str,
    contract_id: str,
) -> AgentOperationPolicyClassV2:
    del agent_name, contract_id
    matches: tuple[AgentOperationPolicyClassV2, ...] = tuple(
        policy_class
        for policy_class, operations in (
            ("routing", _ROUTING_OPERATIONS),
            ("proposal", _PROPOSAL_OPERATIONS),
            ("materialization", _MATERIALIZATION_OPERATIONS),
            ("long_form", _LONG_FORM_OPERATIONS),
        )
        if operation in operations
    )
    if len(matches) != 1:
        raise AgentOperationPolicyError("agent_operation_policy_unknown")
    return matches[0]
