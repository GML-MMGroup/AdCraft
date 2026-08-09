"""Node lifecycle rules for Agent Canvas V1 authoring."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingV2,
    CanvasNodeCreateRequestV2,
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
)
from app.schemas.agent_canvas_editing import default_editing_content
from app.schemas.agent_canvas_video_parameters import CanvasParameterProvenanceV2
from app.services.agent_canvas_authoring_validation import validate_node_patch
from app.services.model_selection import ModelSelectionService


class AgentCanvasNodeService:
    """Apply visible node lifecycle invariants before persistence."""

    def __init__(
        self,
        repository: AgentCanvasWorkflowRepository,
        *,
        model_selection: ModelSelectionService | None = None,
    ) -> None:
        self._repository = repository
        self._model_selection = model_selection

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
            creative_role=request.creative_role,
            title=request.title,
            status=_initial_status(request),
            summary_prompt=request.summary_prompt,
            generation_prompt=request.generation_prompt,
            structured_content=(
                default_editing_content()
                if request.node_type == "editing" and not request.structured_content
                else request.structured_content
            ),
            model_selection_mode=request.model_selection_mode,
            model_ref=request.model_ref,
            parameters=request.parameters,
            parameter_provenance=_manual_parameter_provenance(request.parameters),
            prompt_context_snapshot_id=(
                source.prompt_context_snapshot_id if source is not None else None
            ),
            output_asset_id=request.source_asset_id,
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
        if self._model_selection is not None:
            self._model_selection.validate_authoring(node)
            node = node.model_copy(
                update={"model_summary": self._model_selection.summary_for(node.model_ref)}
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
        if "parameters" in changes:
            changes["parameter_provenance"] = _manual_parameter_provenance(request.parameters or {})
        status = validate_node_patch(
            status=current.status,
            node_type=current.node_type,
            current=current.model_dump(mode="python"),
            changes=changes,
        )
        updated = current.model_copy(
            update={
                **changes,
                "status": status,
                "revision": current.revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        if self._model_selection is not None:
            self._model_selection.validate_authoring(updated)
            updated = updated.model_copy(
                update={"model_summary": self._model_selection.summary_for(updated.model_ref)}
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


def _manual_parameter_provenance(
    parameters: dict[str, object],
) -> dict[str, CanvasParameterProvenanceV2]:
    return {
        field: CanvasParameterProvenanceV2(
            origin="manual",
            requested_value=value,
            effective_value=value,
        )
        for field, value in parameters.items()
        if isinstance(value, (str, int, float, bool))
    }


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
                "updated_at": now,
            }
        )
        for binding in workflow.bindings
        if binding.target_node_id == source_node_id
    )
