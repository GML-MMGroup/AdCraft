"""Node lifecycle rules for Agent Canvas V1 authoring."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from app.persistence.agent_canvas_repository import (
    AgentCanvasWorkflowRepository,
    _has_managed_prompt_preparation,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingV2,
    CanvasNodeCreateRequestV2,
    CanvasNodePatchRequestV2,
    CanvasNodeV2,
)
from app.schemas.agent_canvas_editing import default_editing_content
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_role_prompt_preparation import EditablePromptProjectionV1
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
        candidate_validator: Callable[[AgentCanvasWorkflowV2], None] | None = None,
    ) -> None:
        self._repository = repository
        self._model_selection = model_selection
        self._candidate_validator = candidate_validator

    def create(
        self,
        workflow_id: str,
        request: CanvasNodeCreateRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasNodeV2:
        now = datetime.now(timezone.utc)
        workflow = self._repository.get_workflow(workflow_id)
        normalized_generation_prompt = normalize_manual_generation_prompt(request.generation_prompt)
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
            generation_prompt=normalized_generation_prompt,
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
            prompt_preparation=_initial_prompt_preparation(request, now),
            created_at=now,
            updated_at=now,
        )
        if normalized_generation_prompt is not None:
            node = node.model_copy(
                update={
                    "prompt_presentation": _editable_prompt_projection(
                        normalized_generation_prompt,
                        source="user_edited",
                        revision=1,
                    )
                }
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
        if self._candidate_validator is not None:
            self._candidate_validator(
                workflow.model_copy(
                    update={
                        "nodes": (*workflow.nodes, node),
                        "bindings": (*workflow.bindings, *bindings),
                    }
                )
            )
        self._repository.add_node_with_bindings(
            node,
            bindings,
            expected_revision=expected_revision,
        )
        return self._repository.get_node(workflow_id, node.node_id)

    def patch(
        self,
        workflow_id: str,
        node_id: str,
        request: CanvasNodePatchRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasNodeV2:
        current = self._repository.get_node(workflow_id, node_id)
        workflow = self._repository.get_workflow(workflow_id)
        changes = request.model_dump(exclude_unset=True)
        now = datetime.now(timezone.utc)
        source_only_product = (
            current.node_type == "image"
            and current.creative_role == "product"
            and current.execution_mode == "source_only"
            and current.metadata.get("source_input_kind") in {"main", "multiview"}
        )
        if source_only_product:
            immutable_changes = {
                "model_selection_mode",
                "model_ref",
                "parameters",
                "structured_content",
            } & changes.keys()
            if immutable_changes:
                raise V2PersistenceError(
                    "ready_node_immutable",
                    "Source-only Product Nodes only allow generation prompt text edits.",
                    stage="agent_canvas_nodes",
                )
        if "parameters" in changes:
            changes["parameter_provenance"] = _manual_parameter_provenance(request.parameters or {})
        if "generation_prompt" in changes:
            normalized_prompt = normalize_manual_generation_prompt(request.generation_prompt)
            changes["generation_prompt"] = normalized_prompt
            changes["prompt_presentation"] = (
                _editable_prompt_projection(
                    normalized_prompt,
                    source="user_edited",
                    revision=current.revision + 1,
                    prior=current.prompt_presentation,
                )
                if normalized_prompt is not None
                else None
            )
        if (
            current.status == "draft"
            and _has_managed_prompt_preparation(current)
            and _changes_prompt_authority(changes)
        ):
            changes["prompt_preparation"] = _queued_prompt_preparation(
                current.prompt_preparation,
                now,
            )
        elif "generation_prompt" in changes and not source_only_product:
            if changes["generation_prompt"] is None:
                changes["prompt_preparation"] = NodePromptPreparationV1.waiting_user(updated_at=now)
            elif not _has_managed_prompt_preparation(current):
                changes["prompt_preparation"] = _ready_prompt_preparation(
                    str(changes["generation_prompt"]),
                    now,
                )
        status = (
            current.status
            if source_only_product
            else validate_node_patch(
                status=current.status,
                node_type=current.node_type,
                current=current.model_dump(mode="python"),
                changes=changes,
            )
        )
        updated = current.model_copy(
            update={
                **changes,
                "status": status,
                "revision": current.revision + 1,
                "updated_at": now,
            }
        )
        if self._model_selection is not None:
            self._model_selection.validate_authoring(updated)
            updated = updated.model_copy(
                update={"model_summary": self._model_selection.summary_for(updated.model_ref)}
            )
        if self._candidate_validator is not None:
            self._candidate_validator(
                workflow.model_copy(
                    update={
                        "nodes": tuple(
                            updated if item.node_id == node_id else item for item in workflow.nodes
                        )
                    }
                )
            )
        self._repository.update_node(updated, expected_revision=expected_revision)
        return self._repository.get_node(workflow_id, node_id)

    def delete(
        self,
        workflow_id: str,
        node_id: str,
        *,
        expected_revision: int,
    ) -> AgentCanvasWorkflowV2:
        workflow = self._repository.get_workflow(workflow_id)
        if self._candidate_validator is not None:
            self._candidate_validator(
                workflow.model_copy(
                    update={
                        "nodes": tuple(item for item in workflow.nodes if item.node_id != node_id),
                        "bindings": tuple(
                            binding
                            for binding in workflow.bindings
                            if getattr(binding.source, "source_node_id", None) != node_id
                            and binding.target_node_id != node_id
                        ),
                    }
                )
            )
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


def normalize_manual_generation_prompt(value: str | None) -> str | None:
    """Normalize user-authored prompt text at the persistence boundary."""

    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _initial_prompt_preparation(
    request: CanvasNodeCreateRequestV2,
    now: datetime,
) -> NodePromptPreparationV1:
    prompt = normalize_manual_generation_prompt(request.generation_prompt)
    if not prompt and request.node_type in {"text", "script"}:
        prompt = str(request.structured_content.get("content") or "").strip() or None
    if not prompt and request.source_asset_id is not None:
        prompt = request.source_asset_id
    if prompt:
        return _ready_prompt_preparation(prompt, now)
    return NodePromptPreparationV1.waiting_user(updated_at=now)


def _ready_prompt_preparation(
    prompt: str,
    now: datetime,
) -> NodePromptPreparationV1:
    normalized_prompt = normalize_manual_generation_prompt(prompt)
    if normalized_prompt is None:
        return NodePromptPreparationV1.waiting_user(updated_at=now)
    return NodePromptPreparationV1(
        status="ready",
        operation_id=None,
        attempt_no=0,
        context_snapshot_id=None,
        prompt_digest=sha256(normalized_prompt.encode("utf-8")).hexdigest(),
        error=None,
        updated_at=now,
    )


def _queued_prompt_preparation(
    current: NodePromptPreparationV1,
    now: datetime,
) -> NodePromptPreparationV1:
    return NodePromptPreparationV1(
        status="queued",
        operation_id=None,
        attempt_no=current.attempt_no,
        context_snapshot_id=None,
        prompt_digest=None,
        error=None,
        updated_at=now,
    )


def _editable_prompt_projection(
    text: str,
    *,
    source: Literal["agent_authored", "deterministic_projection", "user_edited"],
    revision: int,
    prior: EditablePromptProjectionV1 | None = None,
) -> EditablePromptProjectionV1:
    return EditablePromptProjectionV1(
        text=text,
        locale=prior.locale if prior is not None else "und",
        source=source,
        revision=revision,
        brief_digest=prior.brief_digest if prior is not None else None,
        prompt_digest=f"sha256:{sha256(text.encode('utf-8')).hexdigest()}",
    )


def _changes_prompt_authority(changes: dict[str, object]) -> bool:
    return bool(
        {
            "generation_prompt",
            "structured_content",
            "parameters",
            "model_selection_mode",
            "model_ref",
        }
        & changes.keys()
    )


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
