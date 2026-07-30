"""Compile bounded Agent intent into canonical Agent Canvas commands."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import AgentCanvasWorkflowV2
from app.schemas.agent_canvas_conversation import ChatTurnV2
from app.schemas.agent_runtime import (
    AgentActionEnvelopeV2,
    AgentCommandPlanCreateV2,
)


class ResolvedAgentMentionsV2(BaseModel):
    """Validated IDs exposed to one Director turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    explicit_node_ids: tuple[str, ...] = ()
    explicit_image_asset_ids: tuple[str, ...] = ()
    candidate_node_ids: tuple[str, ...] = ()
    candidate_image_asset_ids: tuple[str, ...] = ()

    @property
    def allowed_node_ids(self) -> frozenset[str]:
        if self.explicit_node_ids:
            return frozenset(self.explicit_node_ids)
        return frozenset(self.candidate_node_ids)

    @property
    def allowed_image_asset_ids(self) -> frozenset[str]:
        if self.explicit_image_asset_ids:
            return frozenset(self.explicit_image_asset_ids)
        return frozenset(self.candidate_image_asset_ids)


class AgentCommandPlanCompiler:
    """Validate target ownership and assign command risk in Python."""

    def compile(
        self,
        *,
        workflow: AgentCanvasWorkflowV2,
        turn: ChatTurnV2,
        envelope: AgentActionEnvelopeV2,
        resolved_mentions: ResolvedAgentMentionsV2,
    ) -> AgentCommandPlanCreateV2:
        draft = envelope.command_plan
        if draft is None:
            raise _error(
                "agent_command_plan_missing",
                "Agent response did not include a command plan.",
            )
        if turn.workflow_id != workflow.workflow_id:
            raise _error(
                "agent_command_workflow_mismatch",
                "Agent command turn does not belong to the workflow.",
            )

        workflow_node_ids = {node.node_id for node in workflow.nodes}
        allowed_node_ids = resolved_mentions.allowed_node_ids
        allowed_asset_ids = resolved_mentions.allowed_image_asset_ids
        binding_ids = {binding.binding_id for binding in workflow.bindings}

        for operation in draft.operations:
            payload = operation.model_dump(mode="python")
            for node_id in _node_ids(payload):
                if node_id not in workflow_node_ids or node_id not in allowed_node_ids:
                    raise _error(
                        "agent_command_operation_not_allowed",
                        "Agent command references a node outside the resolved context.",
                    )
            for asset_id in _image_asset_ids(payload):
                if asset_id not in allowed_asset_ids:
                    raise _error(
                        "agent_command_operation_not_allowed",
                        "Agent command references an image outside the resolved context.",
                    )
            if operation.operation_type == "delete_binding":
                if operation.binding_id not in binding_ids:
                    raise _error(
                        "agent_command_operation_invalid",
                        "Agent command binding was not found.",
                    )

        risk = _risk_for(draft.operations, workflow)
        return AgentCommandPlanCreateV2(
            workflow_id=workflow.workflow_id,
            conversation_id=turn.conversation_id,
            source_turn_id=turn.turn_id,
            base_workflow_revision=workflow.revision,
            operations=draft.operations,
            continuation_requested=draft.continuation_requested,
            risk=risk,
            confirmation_required=risk != "reversible_authoring",
            target_summary=_target_summary(draft.operations),
        )


def _node_ids(value: Any) -> tuple[str, ...]:
    return _reference_ids(value, kind="node_id", field="node_id")


def _image_asset_ids(value: Any) -> tuple[str, ...]:
    direct = list(_reference_ids(value, kind="image_asset", field="asset_id"))
    if isinstance(value, dict):
        source_asset_id = value.get("source_asset_id")
        if isinstance(source_asset_id, str):
            direct.append(source_asset_id)
    return tuple(direct)


def _reference_ids(value: Any, *, kind: str, field: str) -> tuple[str, ...]:
    found: list[str] = []

    def visit(current: Any) -> None:
        if isinstance(current, dict):
            if current.get("kind") == kind and isinstance(current.get(field), str):
                found.append(current[field])
            for child in current.values():
                visit(child)
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child)

    visit(value)
    return tuple(found)


def _risk_for(operations, workflow: AgentCanvasWorkflowV2) -> str:
    operation_types = {operation.operation_type for operation in operations}
    if operation_types & {"request_node_run"}:
        return "external_effect"
    if operation_types & {"delete_node", "delete_binding"}:
        return "destructive_authoring"
    for operation in operations:
        if operation.operation_type != "prepare_composition":
            continue
        editing_ref = operation.editing_node
        if editing_ref is None or editing_ref.kind != "node_id":
            continue
        existing_sources = {
            binding.source.node_id
            for binding in workflow.bindings
            if binding.target_node_id == editing_ref.node_id
            and binding.source.kind == "node"
            and binding.binding_kind in {"video_reference", "audio_reference"}
        }
        requested_sources = {
            reference.node_id
            for reference in operation.ordered_video_nodes
            if reference.kind == "node_id"
        }
        if operation.bgm_audio_node is not None and operation.bgm_audio_node.kind == "node_id":
            requested_sources.add(operation.bgm_audio_node.node_id)
        if existing_sources - requested_sources:
            return "destructive_authoring"
    return "reversible_authoring"


def _target_summary(operations) -> str:
    return ", ".join(
        f"{operation.operation_type}:{operation.operation_id}" for operation in operations
    )


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_command_plan_compiler")
