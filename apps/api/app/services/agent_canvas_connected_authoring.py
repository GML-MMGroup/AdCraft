"""Atomic click-to-create authoring for Agent Canvas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasConnectedNodeCreateRequestV2,
    CanvasConnectedNodeCreateResponseV2,
    CanvasNodeV2,
)
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_reference_semantics import AgentCanvasReferenceSemanticPolicy
from app.services.model_selection import ModelSelectionService


class AgentCanvasConnectedAuthoringService:
    """Create one Draft node and its binding in a single semantic transaction."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        connection_policy: AgentCanvasConnectionPolicyService,
        *,
        model_selection: ModelSelectionService | None = None,
        binding_capability_validator: object | None = None,
        candidate_validator: Callable[[AgentCanvasWorkflowV2], None] | None = None,
    ) -> None:
        self._workflows = workflows
        self._connection_policy = connection_policy
        self._model_selection = model_selection
        self._binding_capability_validator = binding_capability_validator
        self._candidate_validator = candidate_validator
        self._reference_semantics = AgentCanvasReferenceSemanticPolicy()

    def create_connected_node(
        self,
        workflow_id: str,
        request: CanvasConnectedNodeCreateRequestV2,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> CanvasConnectedNodeCreateResponseV2:
        if not idempotency_key:
            raise V2PersistenceError(
                "idempotency_key_required",
                "Idempotency-Key is required.",
                stage="agent_canvas_connected_authoring",
            )
        if (
            request.node.clone_inputs_from_node_id is not None
            or request.node.source_asset_id is not None
        ):
            raise V2PersistenceError(
                "connected_node_payload_invalid",
                "Connected node creation accepts only a new Draft node payload.",
                stage="agent_canvas_connected_authoring",
            )
        workflow = self._workflows.get_workflow(workflow_id)
        anchor = self._workflows.get_node(workflow_id, request.anchor_node_id)
        now = datetime.now(timezone.utc)
        node = CanvasNodeV2(
            node_id=f"node_{uuid4().hex}",
            workflow_id=workflow_id,
            node_type=request.node.node_type,
            creative_role=request.node.creative_role,
            role_contract_version=request.node.role_contract_version,
            title=request.node.title,
            status="draft",
            summary_prompt=request.node.summary_prompt,
            generation_prompt=request.node.generation_prompt,
            structured_content=request.node.structured_content,
            model_selection_mode=request.node.model_selection_mode,
            model_ref=request.node.model_ref,
            parameters=request.node.parameters,
            prompt_context_snapshot_id=None,
            output_asset_id=None,
            position=request.node.position,
            revision=1,
            error=None,
            created_at=now,
            updated_at=now,
        )
        source, target = (node, anchor) if request.direction == "upstream" else (anchor, node)
        if self._model_selection is not None:
            self._model_selection.validate_authoring(node)
        decision = self._connection_policy.require(
            source_node_type=source.node_type,
            target_node_type=target.node_type,
            input_role=request.binding.input_role,
        )
        incoming = tuple(
            binding for binding in workflow.bindings if binding.target_node_id == target.node_id
        )
        if self._binding_capability_validator is not None:
            input_types = {_input_type(binding.binding_kind) for binding in incoming}
            input_types.add(decision.input_type or "text")
            reference_count = sum(
                _input_type(binding.binding_kind) in {"image", "video", "audio"}
                for binding in incoming
            ) + (1 if decision.input_type in {"image", "video", "audio"} else 0)
            capability = self._binding_capability_validator(
                target,
                frozenset(input_types),
                reference_count,
            )
            if not getattr(capability, "accepted", False):
                raise V2PersistenceError(
                    "provider_inputs_unsupported",
                    "Selected model does not support the complete prospective input set.",
                    stage="agent_canvas_connected_authoring",
                )
        binding = CanvasBindingV2(
            binding_id=f"binding_{uuid4().hex}",
            workflow_id=workflow_id,
            source=CanvasBindingSourceNodeV2(source_node_id=source.node_id),
            target_node_id=target.node_id,
            input_role=decision.input_role or "text_context",
            required=request.binding.required,
            enabled=True,
            order=min(
                request.binding.order if request.binding.order is not None else len(incoming),
                len(incoming),
            ),
            metadata=self._reference_semantics.external_metadata(
                source_role=source.creative_role,
                target_role=target.creative_role,
            ),
            created_at=now,
            updated_at=now,
        )
        if self._candidate_validator is not None:
            candidate_nodes = (
                (*workflow.nodes, node)
                if node.node_id not in {item.node_id for item in workflow.nodes}
                else workflow.nodes
            )
            self._candidate_validator(
                workflow.model_copy(
                    update={
                        "nodes": candidate_nodes,
                        "bindings": (*workflow.bindings, binding),
                    }
                )
            )
        return self._workflows.add_connected_node(
            node=node,
            binding=binding,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_fingerprint=sha256(request.model_dump_json().encode()).hexdigest(),
        )


def _input_type(binding_kind: str) -> str:
    return {
        "text_context": "text",
        "image_reference": "image",
        "video_reference": "video",
        "audio_reference": "audio",
    }[binding_kind]
