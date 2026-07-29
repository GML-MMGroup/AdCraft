"""Node lifecycle rules for Agent Canvas V1 authoring."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingV2,
    CanvasNodeCreateRequestV2,
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
)
from app.schemas.agent_canvas_editing import default_editing_content


class AgentCanvasNodeService:
    """Apply visible node lifecycle invariants before persistence."""

    def __init__(self, repository: AgentCanvasWorkflowRepository) -> None:
        self._repository = repository

    def create(
        self,
        workflow_id: str,
        request: CanvasNodeCreateRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasNodeV2:
        now = datetime.now(timezone.utc)
        source = (
            self._repository.get_node(workflow_id, request.clone_inputs_from_node_id)
            if request.clone_inputs_from_node_id is not None
            else None
        )
        node = CanvasNodeV2(
            node_id=f"node_{uuid4().hex}",
            workflow_id=workflow_id,
            node_type=request.node_type,
            semantic_role=request.semantic_role,
            title=request.title,
            status=_initial_status(request),
            summary_prompt=request.summary_prompt,
            generation_prompt=request.generation_prompt,
            structured_content=(
                default_editing_content()
                if request.node_type == "editing" and not request.structured_content
                else request.structured_content
            ),
            model_id=request.model_id,
            parameters=request.parameters,
            prompt_context_snapshot_id=(
                source.prompt_context_snapshot_id if source is not None else None
            ),
            output_asset_id=request.source_asset_id,
            video_skill_run_id=request.video_skill_run_id,
            position=request.position,
            revision=1,
            error=None,
            created_at=now,
            updated_at=now,
        )
        bindings = (
            _copy_incoming_bindings(
                self._repository.get_workflow(workflow_id),
                source_node_id=source.node_id,
                target_node_id=node.node_id,
                now=now,
            )
            if source is not None
            else ()
        )
        self._repository.add_node_with_bindings(
            node,
            bindings,
            expected_revision=expected_revision,
        )
        return node

    def patch(
        self,
        workflow_id: str,
        node_id: str,
        request: CanvasNodePatchRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasNodeV2:
        current = self._repository.get_node(workflow_id, node_id)
        changes = request.model_dump(exclude_unset=True)
        if (
            current.status == "ready"
            and current.node_type in {"image", "video", "audio", "editing"}
            and _changes_generated_output_definition(current, changes)
        ):
            raise V2PersistenceError(
                "node_output_immutable",
                "Ready media output cannot be overwritten in place.",
                stage="agent_canvas_node_service",
            )
        updated = current.model_copy(
            update={
                **changes,
                "status": _patched_status(current, changes),
                "revision": current.revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._repository.update_node(updated, expected_revision=expected_revision)
        return updated

    def delete(
        self,
        workflow_id: str,
        node_id: str,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        return self._repository.delete_node(
            workflow_id,
            node_id,
            expected_revision=expected_revision,
        )


def _initial_status(request: CanvasNodeCreateRequestV2) -> str:
    if request.source_asset_id is not None:
        return "ready"
    if request.node_type in {"text", "script"} and request.structured_content:
        return "ready"
    return "draft"


def _copy_incoming_bindings(
    workflow: AgentCanvasWorkflowV2,
    *,
    source_node_id: str,
    target_node_id: str,
    now: datetime,
) -> tuple[CanvasBindingV2, ...]:
    return tuple(
        binding.model_copy(
            update={
                "binding_id": f"binding_{uuid4().hex}",
                "target_node_id": target_node_id,
                "created_at": now,
            }
        )
        for binding in workflow.bindings
        if binding.target_node_id == source_node_id
    )


def _changes_generated_output_definition(
    current: CanvasNodeV2,
    changes: dict[str, object],
) -> bool:
    immutable_fields = {
        "generation_prompt",
        "model_id",
        "parameters",
        "structured_content",
    }
    return any(
        field in changes and changes[field] != getattr(current, field) for field in immutable_fields
    )


def _patched_status(current: CanvasNodeV2, changes: dict[str, object]) -> str:
    if current.node_type not in {"text", "script"}:
        return current.status
    content = changes.get("structured_content", current.structured_content)
    return "ready" if content else "draft"
