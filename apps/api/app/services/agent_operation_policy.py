"""Installation-scoped hard-deadline policies for production Agent operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from app.schemas.agent_operation_recovery import (
    AgentOperationPolicyClassV2,
    AgentOperationPolicyV2,
)
from app.schemas.agent_runtime import AgentName, AgentRunPolicy, AgentRunRequest
from app.services.agent_run_context_registry import validate_video_agent_operation_context
from app.services.agent_run_envelope import agent_run_envelope_fields
from app.services.v2_agent_capability_contract import V2AgentCapabilityContractService
from app.services.v2_agent_contract_registry import (
    validate_video_agent_contract_parity,
)
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
    "author_role_brief",
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
    "author_guided_script_checkpoint",
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


class AgentRunRequestFactory:
    """Build a policy-complete Agent request from semantic execution facts."""

    def __init__(
        self,
        *,
        policy_registry: AgentOperationPolicyRegistryV2 | None = None,
        operation_registry: VideoAgentOperationRegistry | None = None,
    ) -> None:
        self._policy_registry = policy_registry or AgentOperationPolicyRegistryV2()
        self._operation_registry = operation_registry or VideoAgentOperationRegistry()
        validate_video_agent_contract_parity(self._operation_registry.definitions())

    def build(
        self,
        *,
        run_id: str,
        request_id: str,
        agent_name: AgentName,
        operation: str,
        context: BaseModel,
        contract_name: str,
        contract_schema: dict[str, Any],
        model_ref: str | None = None,
        parent_run_id: str | None = None,
        credential_ref: str = "llm-default",
        deadline_cap: datetime | None = None,
        validation_profile: str | None = None,
        validation_context: dict[str, Any] | None = None,
        audit_metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> AgentRunRequest:
        self._operation_registry.resolve(operation)
        validate_video_agent_operation_context(operation, context)
        operation_policy = self._policy_registry.resolve(
            agent_name=agent_name,
            operation=operation,
            contract_id=contract_name,
        )
        run_policy = AgentRunPolicy(
            operation_policy_id=operation_policy.policy_id,
            operation_class=operation_policy.policy_class,
            transport_retry_limit=operation_policy.transport_retry_limit,
            structured_repair_limit=operation_policy.structured_repair_limit,
            max_handoffs=0,
            timeout_seconds=float(operation_policy.hard_deadline_seconds),
            primary_timeout_seconds=operation_policy.primary_timeout_seconds,
            recovery_timeout_seconds=operation_policy.recovery_timeout_seconds,
            persistence_reserve_seconds=operation_policy.persistence_reserve_seconds,
            max_model_submissions=operation_policy.max_model_submissions,
            recovery_mode=operation_policy.recovery_mode,
            max_output_tokens=operation_policy.max_output_tokens,
            reasoning_mode=operation_policy.reasoning_mode,
            enable_thinking=operation_policy.enable_thinking,
            thinking_budget_tokens=operation_policy.thinking_budget_tokens,
        )
        timestamp = now or datetime.now(timezone.utc)
        policy_deadline = timestamp + timedelta(seconds=operation_policy.hard_deadline_seconds)
        deadline_at = min(deadline_cap, policy_deadline) if deadline_cap else policy_deadline
        audit = {
            **(audit_metadata or {}),
            "model_policy_id": operation_policy.policy_id,
            "result_contract_name": contract_name,
            "max_handoffs": run_policy.max_handoffs,
            "agent_operation_policy": operation_policy.model_dump(mode="json"),
            "agent_run_policy": run_policy.model_dump(mode="json"),
        }
        return AgentRunRequest(
            run_id=run_id,
            request_id=request_id,
            **agent_run_envelope_fields(context),
            parent_run_id=parent_run_id,
            agent_name=agent_name,
            operation=operation,
            deadline_at=deadline_at,
            model_policy_id=operation_policy.policy_id,
            model_ref=model_ref,
            context=context,
            policy=run_policy,
            credential_ref=credential_ref,
            contract_name=contract_name,
            contract_schema=contract_schema,
            validation_profile=validation_profile,
            validation_context=validation_context or {},
            audit_metadata=audit,
        )


def validate_agent_run_operation_policy(
    request: AgentRunRequest,
    *,
    registry: AgentOperationPolicyRegistryV2 | None = None,
) -> None:
    """Reject a contradictory policy-bearing request before persistence."""

    operation_registry = VideoAgentOperationRegistry()
    validate_video_agent_contract_parity(operation_registry.definitions())
    definition = operation_registry.resolve(request.operation)
    contract_name = request.contract_name or definition.result_contract_name
    operation_policy = (registry or AgentOperationPolicyRegistryV2()).resolve(
        agent_name=request.agent_name,
        operation=request.operation,
        contract_id=contract_name,
    )
    expected_run_policy = AgentRunRequestFactory(
        policy_registry=registry,
        operation_registry=operation_registry,
    ).build(
        run_id=request.run_id,
        request_id=request.request_id,
        parent_run_id=request.parent_run_id,
        agent_name=request.agent_name,
        operation=request.operation,
        context=request.context,
        contract_name=contract_name,
        contract_schema=request.contract_schema,
        model_ref=request.model_ref,
        deadline_cap=request.deadline_at,
        validation_profile=request.validation_profile,
        validation_context=request.validation_context,
        audit_metadata={
            key: value
            for key, value in request.audit_metadata.items()
            if key
            not in {
                "agent_operation_policy",
                "agent_run_policy",
                "max_handoffs",
                "model_policy_id",
                "result_contract_name",
            }
        },
        now=request.deadline_at - timedelta(seconds=operation_policy.hard_deadline_seconds),
    )
    if (
        request.model_policy_id != operation_policy.policy_id
        or request.policy != expected_run_policy.policy
        or request.audit_metadata.get("model_policy_id") != operation_policy.policy_id
        or request.audit_metadata.get("result_contract_name") != contract_name
        or request.audit_metadata.get("agent_operation_policy")
        != expected_run_policy.audit_metadata["agent_operation_policy"]
        or request.audit_metadata.get("agent_run_policy")
        != expected_run_policy.audit_metadata["agent_run_policy"]
    ):
        raise AgentOperationPolicyError("agent_model_policy_mismatch")


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
