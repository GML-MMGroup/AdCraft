"""Typed binding validation and immutable input resolution for Agent Canvas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingCreateRequestV2,
    CanvasBindingPatchRequestV2,
    CanvasBindingMutationResponseV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    ProjectAssetSummaryV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedTextInputSnapshotV2,
    StorageAccessDescriptorV2,
)
from app.services.agent_canvas_authoring_validation import (
    BindingValidationState,
    validate_node_binding,
)
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService


@dataclass(frozen=True, slots=True)
class ResolvedRunInputs:
    """Resolved runnable inputs plus bounded optional-source omissions."""

    inputs: tuple[ResolvedInputSnapshotV2, ...]
    optional_omissions: tuple[dict[str, str], ...] = ()


class AgentCanvasBindingService:
    """Persist real edges and resolve bounded, storage-backed inputs."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        documents: AgentCanvasDocumentRepository,
        *,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2],
        binding_capability_validator: (
            Callable[[object, frozenset[str], int], object] | None
        ) = None,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
    ) -> None:
        self._workflows = workflows
        self._documents = documents
        self._asset_resolver = asset_resolver
        self._binding_capability_validator = binding_capability_validator
        self._connection_policy = connection_policy or AgentCanvasConnectionPolicyService()

    def create(
        self,
        workflow_id: str,
        request: CanvasBindingCreateRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasBindingV2:
        workflow = self._workflows.get_workflow(workflow_id)
        target = self._workflows.get_node(workflow_id, request.target_node_id)
        incoming = tuple(
            binding for binding in workflow.bindings if binding.target_node_id == target.node_id
        )
        if isinstance(request.source, CanvasBindingSourceNodeV2):
            source = self._workflows.get_node(workflow_id, request.source.node_id)
            validate_node_binding(
                bindings=tuple(
                    BindingValidationState(
                        source_node_id=(
                            binding.source.node_id
                            if isinstance(binding.source, CanvasBindingSourceNodeV2)
                            else None
                        ),
                        target_node_id=binding.target_node_id,
                        binding_kind=binding.input_role,
                    )
                    for binding in workflow.bindings
                ),
                source_node_id=source.node_id,
                source_node_type=source.node_type,
                source_semantic_role=source.semantic_role,
                target_node_id=target.node_id,
                target_node_type=target.node_type,
                binding_kind=request.input_role,
            )
            policy_decision = self._connection_policy.decide(
                source_node_type=source.node_type,
                target_node_type=target.node_type,
                input_role=request.input_role,
            )
        else:
            asset = self._resolve_asset(request.source.asset_id)
            if asset.media_type != "image":
                raise _media_incompatible_error()
            policy_decision = self._connection_policy.decide(
                source_node_type="image",
                target_node_type=target.node_type,
                input_role=request.input_role,
                is_image_asset=True,
            )
        if not policy_decision.accepted or request.input_role != policy_decision.input_role:
            raise _media_incompatible_error()
        if self._binding_capability_validator is not None and target.model_id is not None:
            input_types = {
                _binding_input_type(binding.input_role)
                for binding in incoming
                if binding.target_node_id == target.node_id
            }
            input_types.add(_binding_input_type(request.input_role))
            reference_count = sum(
                _binding_input_type(binding.input_role) in {"image", "video", "audio"}
                for binding in incoming
            ) + (1 if policy_decision.input_type in {"image", "video", "audio"} else 0)
            capability_decision = self._binding_capability_validator(
                target,
                frozenset(input_types),
                reference_count,
            )
            if not getattr(capability_decision, "accepted", False):
                raise _binding_model_incompatible_error(capability_decision)
        now = datetime.now(timezone.utc)
        binding = CanvasBindingV2(
            binding_id=f"binding_{uuid4().hex}",
            workflow_id=workflow_id,
            source=request.source,
            target_node_id=request.target_node_id,
            input_role=policy_decision.input_role or "text_context",
            required=request.required,
            enabled=request.enabled,
            order=min(
                request.order if request.order is not None else len(incoming),
                len(incoming),
            ),
            label=request.label,
            metadata=request.metadata,
            created_at=now,
            updated_at=now,
        )
        self._workflows.add_binding(binding, expected_revision=expected_revision)
        return binding

    def delete(
        self,
        workflow_id: str,
        binding_id: str,
        *,
        expected_revision: int,
    ):
        return self._workflows.remove_binding(
            workflow_id,
            binding_id,
            expected_revision=expected_revision,
        )

    def patch(
        self,
        workflow_id: str,
        binding_id: str,
        request: CanvasBindingPatchRequestV2,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> CanvasBindingMutationResponseV2:
        workflow = self._workflows.get_workflow(workflow_id)
        existing = next((item for item in workflow.bindings if item.binding_id == binding_id), None)
        if existing is None:
            raise V2PersistenceError(
                "binding_not_found",
                "Binding was not found.",
                stage="agent_canvas_binding_service",
            )
        target = self._workflows.get_node(workflow_id, existing.target_node_id)
        if isinstance(existing.source, CanvasBindingSourceNodeV2):
            source = self._workflows.get_node(workflow_id, existing.source.node_id)
            policy_decision = self._connection_policy.require(
                source_node_type=source.node_type,
                target_node_type=target.node_type,
                input_role=request.input_role or existing.input_role,
            )
        else:
            asset = self._resolve_asset(existing.source.asset_id)
            if asset.media_type != "image":
                raise _media_incompatible_error()
            policy_decision = self._connection_policy.require(
                source_node_type="image",
                target_node_type=target.node_type,
                input_role=request.input_role or existing.input_role,
                is_image_asset=True,
            )
        incoming = tuple(
            item for item in workflow.bindings if item.target_node_id == existing.target_node_id
        )
        order = request.order if request.order is not None else existing.order
        updated = existing.model_copy(
            update={
                "input_role": policy_decision.input_role or existing.input_role,
                "required": request.required if request.required is not None else existing.required,
                "enabled": request.enabled if request.enabled is not None else existing.enabled,
                "order": min(order, len(incoming) - 1),
                "label": request.label if request.label is not None else existing.label,
                "metadata": (
                    request.metadata if request.metadata is not None else existing.metadata
                ),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._workflows.update_binding(
            binding=updated,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

    def snapshot_prompt_context(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> tuple[ResolvedTextInputSnapshotV2, ...]:
        workflow = self._workflows.get_workflow(workflow_id)
        snapshots: list[ResolvedTextInputSnapshotV2] = []
        for binding in workflow.bindings:
            if (
                binding.target_node_id != target_node_id
                or not binding.enabled
                or binding.input_role != "text_context"
                or not isinstance(binding.source, CanvasBindingSourceNodeV2)
            ):
                continue
            source = self._workflows.get_node(workflow_id, binding.source.node_id)
            document = self._documents.get(source.node_id)
            content = str(document.content.get("content", ""))
            snapshots.append(
                ResolvedTextInputSnapshotV2(
                    source_node_id=source.node_id,
                    source_node_revision=source.revision,
                    binding_kind="text_context",
                    document_kind=document.document_kind,
                    content=content[:16000],
                    content_hash=document.content_hash,
                    binding_id=binding.binding_id,
                    input_role=binding.input_role,
                    required=binding.required,
                    display_order=binding.display_order,
                )
            )
        result = tuple(snapshots)
        self._documents.put_prompt_context_snapshot(
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            inputs=result,
        )
        return result

    def resolve_run_inputs(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> tuple[ResolvedInputSnapshotV2, ...]:
        return self.resolve_run_input_resolution(workflow_id, target_node_id).inputs

    def resolve_run_input_resolution(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> "ResolvedRunInputs":
        target = self._workflows.get_node(workflow_id, target_node_id)
        text_inputs: tuple[ResolvedTextInputSnapshotV2, ...] = ()
        if target.prompt_context_snapshot_id is not None:
            text_inputs = self._documents.get_prompt_context_snapshot(
                target.prompt_context_snapshot_id
            ).inputs
        media_inputs, optional_omissions = self._resolve_media_inputs(workflow_id, target_node_id)
        return ResolvedRunInputs(
            inputs=tuple(
                sorted(
                    (*text_inputs, *media_inputs),
                    key=lambda item: (item.display_order, item.binding_id or ""),
                )
            ),
            optional_omissions=optional_omissions,
        )

    def _resolve_media_inputs(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> tuple[tuple[ResolvedMediaInputSnapshotV2, ...], tuple[dict[str, str], ...]]:
        workflow = self._workflows.get_workflow(workflow_id)
        resolved: list[ResolvedMediaInputSnapshotV2] = []
        optional_omissions: list[dict[str, str]] = []
        for binding in workflow.bindings:
            if (
                binding.target_node_id != target_node_id
                or not binding.enabled
                or binding.input_role
                not in {
                    "image_reference",
                    "video_reference",
                    "audio_reference",
                }
            ):
                continue
            source_node_id: str | None = None
            source_revision: int | None = None
            if isinstance(binding.source, CanvasBindingSourceNodeV2):
                source = self._workflows.get_node(workflow_id, binding.source.node_id)
                if source.status != "ready" or source.output_asset_id is None:
                    if binding.required:
                        raise V2PersistenceError(
                            "binding_source_not_ready",
                            "A required media binding source is not ready.",
                            stage="agent_canvas_binding_service",
                        )
                    optional_omissions.append(
                        {
                            "binding_id": binding.binding_id,
                            "source_node_id": source.node_id,
                            "reason": "binding_source_not_ready",
                        }
                    )
                    continue
                asset = self._resolve_asset(source.output_asset_id)
                source_kind = "node_output"
                source_node_id = source.node_id
                source_revision = source.revision
                source_semantic_role = source.semantic_role
            else:
                asset = self._resolve_asset(binding.source.asset_id)
                source_kind = "image_asset"
                source_semantic_role = asset.source_semantic_role
            resolved.append(
                ResolvedMediaInputSnapshotV2(
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_node_revision=source_revision,
                    binding_kind=binding.input_role,
                    source_semantic_role=source_semantic_role,
                    asset_id=asset.asset_id,
                    media_type=asset.media_type,
                    asset_checksum=asset.checksum,
                    access_descriptor=StorageAccessDescriptorV2(
                        asset_id=asset.asset_id,
                        media_url=asset.media_url or asset.preview_url or "",
                        checksum=asset.checksum,
                    ),
                    binding_id=binding.binding_id,
                    input_role=binding.input_role,
                    required=binding.required,
                    display_order=binding.display_order,
                )
            )
        return tuple(resolved), tuple(optional_omissions)

    def _resolve_asset(self, asset_id: str) -> ProjectAssetSummaryV2:
        try:
            asset = self._asset_resolver(asset_id)
        except (KeyError, LookupError) as error:
            raise V2PersistenceError(
                "binding_source_not_found",
                "Binding source asset was not found.",
                stage="agent_canvas_binding_service",
            ) from error
        if asset.status != "ready" or not (asset.media_url or asset.preview_url):
            raise V2PersistenceError(
                "binding_source_not_ready",
                "Binding source asset is not ready.",
                stage="agent_canvas_binding_service",
            )
        return asset


def _media_incompatible_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_media_incompatible",
        "Binding kind is incompatible with the source media.",
        stage="agent_canvas_binding_service",
    )


def _binding_input_type(binding_kind: str) -> str:
    return {
        "text_context": "text",
        "image_reference": "image",
        "video_reference": "video",
        "audio_reference": "audio",
    }[binding_kind]


def _binding_model_incompatible_error(decision: object) -> V2PersistenceError:
    error = V2PersistenceError(
        "binding_model_incompatible",
        "Selected model is incompatible with the complete binding set.",
        stage="agent_canvas_binding_service",
    )
    error.details = {
        "target_node_id": getattr(decision, "target_node_id"),
        "selected_model_id": getattr(decision, "selected_model_id"),
        "required_input_types": sorted(getattr(decision, "required_input_types")),
        "compatible_model_ids": list(getattr(decision, "compatible_model_ids")),
        "switch_model_required": True,
    }
    return error
