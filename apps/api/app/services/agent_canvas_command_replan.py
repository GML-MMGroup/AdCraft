"""One-shot semantic-conflict recovery for Agent Canvas command plans."""

from __future__ import annotations

import json
from typing import Protocol

from app.persistence.agent_canvas_command_repository import (
    AgentCanvasCommandRepository,
)
from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2
from app.schemas.agent_operation_contexts import AgentCommandReplanContextV2
from app.schemas.agent_runtime import (
    AgentActionEnvelopeV2,
    AgentCommandPlanDraftV2,
    AgentCommandPlanV2,
    AgentCommandReplanResultV2,
)
from app.services.agent_canvas_command_compiler import (
    AgentCommandPlanCompiler,
    ResolvedAgentMentionsV2,
)


class CommandReplanGateway(Protocol):
    def replan(
        self,
        context: AgentCommandReplanContextV2,
    ) -> AgentCommandPlanDraftV2: ...


class AgentCommandReplanService:
    """Persist at most one validated replacement for a stale command plan."""

    def __init__(
        self,
        *,
        commands: AgentCanvasCommandRepository,
        conversations: AgentCanvasConversationRepository,
        workflows: AgentCanvasWorkflowRepository,
        compiler: AgentCommandPlanCompiler,
        gateway: CommandReplanGateway,
    ) -> None:
        self._commands = commands
        self._conversations = conversations
        self._workflows = workflows
        self._compiler = compiler
        self._gateway = gateway

    def current_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        return self._workflows.get_workflow(workflow_id)

    def replan_once(
        self,
        *,
        original_plan: AgentCommandPlanV2,
        current_workflow: AgentCanvasWorkflowV2,
        confirmation_granted: bool,
    ) -> AgentCommandReplanResultV2:
        if original_plan.replacement_plan_id is not None:
            raise _error(
                "agent_command_replan_exhausted",
                "Agent command conflict replan was already used.",
            )
        turn = self._conversations.get_turn(original_plan.source_turn_id)
        node_ids, asset_ids = _direct_references(original_plan)
        node_by_id = {node.node_id: node for node in current_workflow.nodes}
        current_summaries = tuple(
            json.dumps(
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "semantic_role": node.semantic_role,
                    "title": node.title,
                    "status": node.status,
                    "revision": node.revision,
                },
                sort_keys=True,
            )
            for node_id in node_ids
            if (node := node_by_id.get(node_id)) is not None
        )
        replacement_draft = self._gateway.replan(
            AgentCommandReplanContextV2(
                context_kind="agent_command_replan",
                workflow_id=current_workflow.workflow_id,
                workflow_revision=current_workflow.revision,
                conversation_id=original_plan.conversation_id,
                original_user_intent=str(turn.request.get("text") or ""),
                original_plan_summary=original_plan.target_summary,
                current_target_summaries=current_summaries,
                conflict_code="workflow_revision_conflict",
            )
        )
        compiled = self._compiler.compile(
            workflow=current_workflow,
            turn=turn,
            envelope=AgentActionEnvelopeV2(
                assistant_message="Replanned the stale canvas command.",
                command_plan=replacement_draft,
            ),
            resolved_mentions=ResolvedAgentMentionsV2(
                explicit_node_ids=node_ids,
                explicit_image_asset_ids=asset_ids,
                candidate_node_ids=node_ids,
                candidate_image_asset_ids=asset_ids,
            ),
        )
        replacement, _ = self._commands.create_or_get_plan(
            compiled,
            idempotency_key=f"replan:{original_plan.plan_id}",
        )
        equivalent = (
            replacement.operation_fingerprint == original_plan.operation_fingerprint
            and _risk_rank(replacement.risk) <= _risk_rank(original_plan.risk)
        )
        confirmation_transferred = confirmation_granted and equivalent
        replacement = self._commands.link_replacement_plan(
            original_plan.plan_id,
            replacement.plan_id,
            transfer_confirmation=confirmation_transferred,
        )
        return AgentCommandReplanResultV2(
            original_plan_id=original_plan.plan_id,
            replacement_plan=replacement,
            confirmation_transferred=confirmation_transferred,
        )


def _direct_references(
    plan: AgentCommandPlanV2,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    node_ids: list[str] = []
    asset_ids: list[str] = []

    def visit(value) -> None:
        if isinstance(value, dict):
            if value.get("kind") == "node_id" and isinstance(value.get("node_id"), str):
                node_ids.append(value["node_id"])
            if value.get("kind") == "image_asset" and isinstance(value.get("asset_id"), str):
                asset_ids.append(value["asset_id"])
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit([operation.model_dump(mode="python") for operation in plan.operations])
    return tuple(dict.fromkeys(node_ids)), tuple(dict.fromkeys(asset_ids))


def _risk_rank(risk: str) -> int:
    return {
        "reversible_authoring": 0,
        "destructive_authoring": 1,
        "external_effect": 2,
    }[risk]


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_command_replan_service")
