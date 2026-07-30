"""Atomic authoring preparation for Agent Canvas Editing nodes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    CanvasPositionV2,
)
from app.schemas.agent_canvas_editing import (
    EditingManifestV2,
    EditingNodeContentV2,
    EditingPreviewV2,
)
from app.schemas.agent_runtime import (
    AgentNodeIdRefV2,
    AgentNodeRefV2,
    AgentPrepareCompositionOperationV2,
    AgentPrepareCompositionResultV2,
)
from app.services.agent_canvas_connection_policy import (
    AgentCanvasConnectionPolicyService,
)


class AgentCanvasCompositionPreparationService:
    """Validate and persist one complete composition authoring change."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        *,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
    ) -> None:
        self._workflows = workflows
        self._connection_policy = connection_policy or AgentCanvasConnectionPolicyService()

    def prepare(
        self,
        *,
        workflow_id: str,
        operation: AgentPrepareCompositionOperationV2,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgentPrepareCompositionResultV2:
        if not idempotency_key:
            raise _error("idempotency_key_required", "Idempotency-Key is required.")
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        video_nodes = tuple(
            self._resolve_node(reference, nodes, expected_type="video")
            for reference in operation.ordered_video_nodes
        )
        bgm_node = (
            self._resolve_node(
                operation.bgm_audio_node,
                nodes,
                expected_type="audio",
                expected_role="bgm",
            )
            if operation.bgm_audio_node is not None
            else None
        )
        existing = (
            self._resolve_node(
                operation.editing_node,
                nodes,
                expected_type="editing",
            )
            if operation.editing_node is not None
            else None
        )
        now = datetime.now(timezone.utc)
        node_id = existing.node_id if existing is not None else f"node_{uuid4().hex}"
        bindings = self._bindings(
            workflow_id=workflow_id,
            target_node_id=node_id,
            video_nodes=video_nodes,
            bgm_node=bgm_node,
            created_at=now,
        )
        current_content = (
            EditingNodeContentV2.model_validate(existing.structured_content)
            if existing is not None
            else EditingNodeContentV2()
        )
        manifest = EditingManifestV2(
            ordered_video_binding_ids=tuple(
                binding.binding_id
                for binding in bindings
                if binding.binding_kind == "video_reference"
            ),
            bgm_audio_binding_id=next(
                (
                    binding.binding_id
                    for binding in bindings
                    if binding.binding_kind == "audio_reference"
                ),
                None,
            ),
            bgm_volume=operation.bgm_volume,
            output=operation.output,
            manifest_revision=(
                current_content.manifest.manifest_revision + 1 if existing is not None else 1
            ),
        )
        content = current_content.model_copy(
            update={
                "manifest": manifest,
                "dirty": True,
                "preview": EditingPreviewV2(),
                "active_export": None,
            }
        )
        position = existing.position if existing is not None else CanvasPositionV2(x=0, y=0)
        node = CanvasNodeV2(
            node_id=node_id,
            workflow_id=workflow_id,
            node_type="editing",
            semantic_role="final_composition",
            title=operation.title or existing.title,
            status="draft",
            summary_prompt=existing.summary_prompt if existing is not None else None,
            generation_prompt=(existing.generation_prompt if existing is not None else None),
            structured_content=content.model_dump(mode="json"),
            model_id=existing.model_id if existing is not None else None,
            parameters=existing.parameters if existing is not None else {},
            output_asset_id=(existing.output_asset_id if existing is not None else None),
            position=position,
            revision=(existing.revision + 1 if existing is not None else 1),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        fingerprint = hashlib.sha256(
            f"{workflow_id}:{operation.model_dump_json()}".encode()
        ).hexdigest()
        return self._workflows.prepare_composition(
            node=node,
            bindings=bindings,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )

    def _bindings(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        video_nodes: tuple[CanvasNodeV2, ...],
        bgm_node: CanvasNodeV2 | None,
        created_at: datetime,
    ) -> tuple[CanvasBindingV2, ...]:
        result: list[CanvasBindingV2] = []
        for display_order, source in enumerate(video_nodes):
            decision = self._connection_policy.require(
                source_node_type="video",
                target_node_type="editing",
                input_role="source_video",
            )
            result.append(
                CanvasBindingV2(
                    binding_id=f"binding_{uuid4().hex}",
                    workflow_id=workflow_id,
                    source=CanvasBindingSourceNodeV2(node_id=source.node_id),
                    target_node_id=target_node_id,
                    binding_kind=decision.binding_kind or "video_reference",
                    input_role=decision.input_role or "source_video",
                    required=False,
                    display_order=display_order,
                    created_at=created_at,
                )
            )
        if bgm_node is not None:
            decision = self._connection_policy.require(
                source_node_type="audio",
                target_node_type="editing",
                input_role="audio_reference",
            )
            result.append(
                CanvasBindingV2(
                    binding_id=f"binding_{uuid4().hex}",
                    workflow_id=workflow_id,
                    source=CanvasBindingSourceNodeV2(node_id=bgm_node.node_id),
                    target_node_id=target_node_id,
                    binding_kind=decision.binding_kind or "audio_reference",
                    input_role=decision.input_role or "audio_reference",
                    required=False,
                    display_order=len(result),
                    created_at=created_at,
                )
            )
        return tuple(result)

    @staticmethod
    def _resolve_node(
        reference: AgentNodeRefV2,
        nodes: dict[str, CanvasNodeV2],
        *,
        expected_type: str,
        expected_role: str | None = None,
    ) -> CanvasNodeV2:
        if not isinstance(reference, AgentNodeIdRefV2):
            raise _error(
                "composition_source_unresolved",
                "Composition service requires resolved node references.",
            )
        node = nodes.get(reference.node_id)
        if node is None:
            raise _error(
                "composition_source_not_found",
                "Composition source was not found in the Workflow.",
            )
        if node.node_type != expected_type:
            code = (
                "composition_video_source_invalid"
                if expected_type == "video"
                else "composition_bgm_source_invalid"
                if expected_type == "audio"
                else "composition_target_invalid"
            )
            raise _error(code, "Composition source has an incompatible node type.")
        if expected_role is not None and node.semantic_role != expected_role:
            raise _error(
                "composition_bgm_source_invalid",
                "Composition audio source must use the bgm semantic role.",
            )
        return node


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(
        code,
        message,
        stage="agent_canvas_composition_preparation",
    )
