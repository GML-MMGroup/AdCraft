"""Typed binding validation and immutable input resolution for Agent Canvas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.agent_canvas_requirement_repository import (
    AgentCanvasRequirementRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingCreateRequestV2,
    CanvasBindingPatchRequestV2,
    CanvasBindingMutationResponseV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    AgentCanvasPromptContextSnapshotV2,
    AgentCanvasWorkflowV2,
    ProjectAssetSummaryV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedTextInputSnapshotV2,
    StorageAccessDescriptorV2,
)
from app.schemas.agent_canvas_runtime import NodeRunBindingSnapshotV2
from app.services.agent_canvas_authoring_validation import (
    BindingValidationState,
    validate_node_binding,
    validate_ready_node_input_history,
)
from app.services.agent_canvas_connection_policy import AgentCanvasConnectionPolicyService
from app.services.agent_canvas_world_setting import WorldSettingBindingPolicy


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
        asset_version_resolver: Callable[[str, str], ProjectAssetSummaryV2] | None = None,
        binding_capability_validator: (
            Callable[[object, frozenset[str], int], object] | None
        ) = None,
        connection_policy: AgentCanvasConnectionPolicyService | None = None,
    ) -> None:
        self._workflows = workflows
        self._documents = documents
        self._asset_resolver = asset_resolver
        self._asset_version_resolver = asset_version_resolver
        self._binding_capability_validator = binding_capability_validator
        self._connection_policy = connection_policy or AgentCanvasConnectionPolicyService()
        self._world_setting_policy = WorldSettingBindingPolicy()
        self._requirements = AgentCanvasRequirementRepository(workflows.database)

    def create(
        self,
        workflow_id: str,
        request: CanvasBindingCreateRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasBindingV2:
        workflow = self._workflows.get_workflow(workflow_id)
        target = self._workflows.get_node(workflow_id, request.target_node_id)
        validate_ready_node_input_history(status=target.status, node_type=target.node_type)
        incoming = tuple(
            binding for binding in workflow.bindings if binding.target_node_id == target.node_id
        )
        world_setting_source = False
        if isinstance(request.source, CanvasBindingSourceNodeV2):
            source = self._workflows.get_node(workflow_id, request.source.node_id)
            world_setting_source = source.creative_role == "world_setting"
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
        if self._binding_capability_validator is not None and target.node_type in {
            "image",
            "video",
            "audio",
        }:
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
            metadata=(
                self._world_setting_policy.metadata_for_target(
                    target.creative_role,
                    request.metadata,
                )
                if world_setting_source
                else request.metadata
            ),
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
        workflow = self._workflows.get_workflow(workflow_id)
        existing = next((item for item in workflow.bindings if item.binding_id == binding_id), None)
        if existing is None:
            raise V2PersistenceError(
                "binding_not_found",
                "Binding was not found.",
                stage="agent_canvas_binding_service",
            )
        target = self._workflows.get_node(workflow_id, existing.target_node_id)
        validate_ready_node_input_history(status=target.status, node_type=target.node_type)
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
        validate_ready_node_input_history(status=target.status, node_type=target.node_type)
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
                "metadata": self._binding_metadata(
                    source_role=(
                        source.creative_role
                        if isinstance(existing.source, CanvasBindingSourceNodeV2)
                        else None
                    ),
                    target_role=target.creative_role,
                    metadata=(
                        request.metadata if request.metadata is not None else existing.metadata
                    ),
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

    def _binding_metadata(
        self,
        *,
        source_role: str | None,
        target_role: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        if source_role != "world_setting":
            return metadata
        return self._world_setting_policy.metadata_for_target(target_role, metadata)

    def snapshot_prompt_context(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> tuple[ResolvedTextInputSnapshotV2, ...]:
        return self.capture_prompt_context_snapshot(
            workflow_id,
            target_node_id,
        ).inputs

    def capture_prompt_context_snapshot(
        self,
        workflow_id: str,
        target_node_id: str,
        *,
        node_run_id: str | None = None,
    ) -> AgentCanvasPromptContextSnapshotV2:
        if node_run_id is not None:
            existing = self._documents.find_prompt_context_snapshot(
                workflow_id=workflow_id,
                target_node_id=target_node_id,
                operation=node_run_id,
            )
            if existing is not None:
                return existing
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
            try:
                document = self._documents.get(source.node_id)
                document_kind = document.document_kind
                content = str(document.content.get("content", ""))
                content_hash = document.content_hash
            except V2PersistenceError as error:
                if error.code != "canvas_document_not_found":
                    raise
                document_kind = "script" if source.node_type == "script" else "text"
                content = str(source.structured_content.get("content", ""))
                content_hash = hashlib.sha256(content.encode()).hexdigest()
            snapshots.append(
                ResolvedTextInputSnapshotV2(
                    source_node_id=source.node_id,
                    source_node_revision=source.revision,
                    binding_kind="text_context",
                    document_kind=document_kind,
                    content=content[:16000],
                    content_hash=content_hash,
                    source_semantic_role=source.semantic_role,
                    binding_metadata=binding.metadata,
                    source_structured_content=source.structured_content,
                    binding_id=binding.binding_id,
                    input_role=binding.input_role,
                    required=binding.required,
                    display_order=binding.display_order,
                )
            )
        result = tuple(
            sorted(snapshots, key=lambda item: (item.display_order, item.binding_id or ""))
        )
        content_digest = hashlib.sha256(
            "\n".join(item.content_hash for item in result).encode()
        ).hexdigest()
        requirement_lineage = self._requirement_lineage(
            workflow_id,
            target_node_id=target_node_id,
            content_digest=content_digest,
        )
        return self._documents.put_prompt_context_snapshot(
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            inputs=result,
            operation=node_run_id,
            binding_ids=tuple(item.binding_id for item in result if item.binding_id is not None),
            content_digest=content_digest,
            **requirement_lineage,
        )

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
        else:
            text_inputs = self.snapshot_prompt_context(workflow_id, target_node_id)
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
                    binding_metadata=binding.metadata,
                    asset_id=asset.asset_id,
                    asset_version_id=asset.version_id,
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

    def resolve_asset_version(
        self,
        asset_id: str,
        version_id: str | None,
    ) -> ProjectAssetSummaryV2:
        if version_id is None:
            return self._resolve_asset(asset_id)
        try:
            asset = (
                self._asset_version_resolver(asset_id, version_id)
                if self._asset_version_resolver is not None
                else self._resolve_asset(asset_id)
            )
        except (KeyError, LookupError) as error:
            raise V2PersistenceError(
                "asset_version_not_found",
                "Asset version was not found.",
                stage="agent_canvas_binding_service",
            ) from error
        if asset.version_id not in {None, version_id}:
            raise V2PersistenceError(
                "asset_version_not_found",
                "Asset version was not found.",
                stage="agent_canvas_binding_service",
            )
        return asset

    def get_workflow(self, workflow_id: str) -> AgentCanvasWorkflowV2:
        return self._workflows.get_workflow(workflow_id)

    def resolve_media_input_snapshots(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> tuple[tuple[ResolvedMediaInputSnapshotV2, ...], tuple[dict[str, str], ...]]:
        return self._resolve_media_inputs(workflow_id, target_node_id)

    def resolve_frozen_run_input_resolution(
        self,
        workflow_id: str,
        target_node_id: str,
        binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...],
        *,
        node_run_id: str,
    ) -> ResolvedRunInputs:
        """Resolve only bindings captured when the execution was accepted."""

        existing = self._documents.find_prompt_context_snapshot(
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            operation=node_run_id,
        )
        frozen_text_by_binding = (
            {item.binding_id: item for item in existing.inputs if item.binding_id is not None}
            if existing is not None
            else {}
        )
        text_inputs: list[ResolvedTextInputSnapshotV2] = []
        media_inputs: list[ResolvedMediaInputSnapshotV2] = []
        optional_omissions: list[dict[str, str]] = []
        for binding in sorted(binding_snapshots, key=lambda item: (item.order, item.binding_id)):
            if binding.input_role == "text_context":
                if binding.source_kind != "node_output":
                    raise _frozen_binding_error()
                frozen_input = frozen_text_by_binding.get(binding.binding_id)
                if frozen_input is not None:
                    text_inputs.append(frozen_input)
                    continue
                source = self._workflows.get_node(workflow_id, binding.source_id)
                try:
                    document = self._documents.get(source.node_id)
                    document_kind = document.document_kind
                    content = str(document.content.get("content", ""))
                    content_hash = document.content_hash
                except V2PersistenceError as error:
                    if error.code != "canvas_document_not_found":
                        raise
                    document_kind = "script" if source.node_type == "script" else "text"
                    content = str(source.structured_content.get("content", ""))
                    content_hash = hashlib.sha256(content.encode()).hexdigest()
                text_inputs.append(
                    ResolvedTextInputSnapshotV2(
                        source_node_id=source.node_id,
                        source_node_revision=binding.source_node_revision or source.revision,
                        binding_kind="text_context",
                        document_kind=document_kind,
                        content=content[:16_000],
                        content_hash=content_hash,
                        source_semantic_role=(binding.source_semantic_role or source.semantic_role),
                        binding_metadata=binding.binding_metadata,
                        source_structured_content=source.structured_content,
                        binding_id=binding.binding_id,
                        input_role="text_context",
                        required=binding.required,
                        display_order=binding.order,
                    )
                )
                continue

            asset: ProjectAssetSummaryV2
            source_node_id: str | None = None
            source_semantic_role: str | None = None
            if binding.source_kind == "node_output":
                source = self._workflows.get_node(workflow_id, binding.source_id)
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
                source_node_id = source.node_id
                source_semantic_role = source.semantic_role
            else:
                asset = self._resolve_asset(binding.source_id)
                source_semantic_role = asset.source_semantic_role
            media_inputs.append(
                ResolvedMediaInputSnapshotV2(
                    source_kind=binding.source_kind,
                    source_node_id=source_node_id,
                    source_node_revision=(
                        binding.source_node_revision if source_node_id is not None else None
                    ),
                    binding_kind=binding.input_role,
                    source_semantic_role=source_semantic_role,
                    binding_metadata=binding.binding_metadata,
                    asset_id=asset.asset_id,
                    asset_version_id=asset.version_id,
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
                    display_order=binding.order,
                )
            )

        if existing is None:
            content_digest = hashlib.sha256(
                "\n".join(item.content_hash for item in text_inputs).encode()
            ).hexdigest()
            text_snapshot = self._documents.put_prompt_context_snapshot(
                workflow_id=workflow_id,
                target_node_id=target_node_id,
                inputs=tuple(text_inputs),
                operation=node_run_id,
                binding_ids=tuple(item.binding_id for item in text_inputs if item.binding_id),
                content_digest=content_digest,
                **self._requirement_lineage(
                    workflow_id,
                    target_node_id=target_node_id,
                    content_digest=content_digest,
                ),
            )
        else:
            text_snapshot = existing
        return ResolvedRunInputs(
            inputs=tuple(
                sorted(
                    (*text_snapshot.inputs, *media_inputs),
                    key=lambda item: (item.display_order, item.binding_id or ""),
                )
            ),
            optional_omissions=tuple(optional_omissions),
        )

    def get_prompt_context_snapshot_for_run(
        self,
        workflow_id: str,
        target_node_id: str,
        *,
        node_run_id: str,
    ) -> AgentCanvasPromptContextSnapshotV2:
        snapshot = self._documents.find_prompt_context_snapshot(
            workflow_id=workflow_id,
            target_node_id=target_node_id,
            operation=node_run_id,
        )
        if snapshot is None:
            raise V2PersistenceError(
                "run_input_snapshot_not_found",
                "The frozen prompt input snapshot was not found.",
                stage="agent_canvas_binding_service",
            )
        return snapshot

    def _requirement_lineage(
        self,
        workflow_id: str,
        *,
        target_node_id: str,
        content_digest: str,
    ) -> dict[str, object]:
        revision = self._requirements.get_current(workflow_id)
        projection_digest = hashlib.sha256(
            f"{revision.digest}:{target_node_id}:{content_digest}".encode("utf-8")
        ).hexdigest()
        return {
            "requirement_revision_id": revision.revision_id,
            "requirement_revision_no": revision.revision_no,
            "requirement_digest": revision.digest,
            "requirement_projection_digest": projection_digest,
        }

    def resolve_asset(self, asset_id: str) -> ProjectAssetSummaryV2:
        return self._resolve_asset(asset_id)


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


def _frozen_binding_error() -> V2PersistenceError:
    return V2PersistenceError(
        "frozen_binding_invalid",
        "The frozen execution Binding is incompatible with its input role.",
        stage="agent_canvas_binding_service",
    )
