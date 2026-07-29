"""Typed binding validation and immutable input resolution for Agent Canvas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from app.persistence.agent_canvas_repository import (
    AgentCanvasDocumentRepository,
    AgentCanvasWorkflowRepository,
)
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingCreateRequestV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    ProjectAssetSummaryV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedTextInputSnapshotV2,
    StorageAccessDescriptorV2,
)


class AgentCanvasBindingService:
    """Persist real edges and resolve bounded, storage-backed inputs."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        documents: AgentCanvasDocumentRepository,
        *,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2],
        binding_capability_validator: (Callable[[object, frozenset[str]], object] | None) = None,
    ) -> None:
        self._workflows = workflows
        self._documents = documents
        self._asset_resolver = asset_resolver
        self._binding_capability_validator = binding_capability_validator

    def create(
        self,
        workflow_id: str,
        request: CanvasBindingCreateRequestV2,
        *,
        expected_revision: int,
    ) -> CanvasBindingV2:
        workflow = self._workflows.get_workflow(workflow_id)
        target = self._workflows.get_node(workflow_id, request.target_node_id)
        if isinstance(request.source, CanvasBindingSourceNodeV2):
            source = self._workflows.get_node(workflow_id, request.source.node_id)
            self._assert_acyclic(
                workflow.bindings,
                source_node_id=source.node_id,
                target_node_id=target.node_id,
            )
            _validate_node_binding_kind(source.node_type, request.binding_kind)
            if target.node_type == "editing":
                _validate_editing_binding(workflow.bindings, source, target.node_id, request)
        else:
            asset = self._resolve_asset(request.source.asset_id)
            if request.binding_kind != "image_reference" or asset.media_type != "image":
                raise _media_incompatible_error()
        if self._binding_capability_validator is not None and target.model_id is not None:
            input_types = {
                _binding_input_type(binding.binding_kind)
                for binding in workflow.bindings
                if binding.target_node_id == target.node_id
            }
            input_types.add(_binding_input_type(request.binding_kind))
            decision = self._binding_capability_validator(target, frozenset(input_types))
            if not getattr(decision, "accepted", False):
                raise _binding_model_incompatible_error(decision)
        binding = CanvasBindingV2(
            binding_id=f"binding_{uuid4().hex}",
            workflow_id=workflow_id,
            source=request.source,
            target_node_id=request.target_node_id,
            binding_kind=request.binding_kind,
            required=request.required,
            display_order=request.display_order,
            created_at=datetime.now(timezone.utc),
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
                or binding.binding_kind not in {"brief_context", "script_context"}
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
                    binding_kind=binding.binding_kind,
                    document_kind=document.document_kind,
                    content=content[:16000],
                    content_hash=document.content_hash,
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
        target = self._workflows.get_node(workflow_id, target_node_id)
        text_inputs: tuple[ResolvedTextInputSnapshotV2, ...] = ()
        if target.prompt_context_snapshot_id is not None:
            text_inputs = self._documents.get_prompt_context_snapshot(
                target.prompt_context_snapshot_id
            ).inputs
        media_inputs = self._resolve_media_inputs(workflow_id, target_node_id)
        return (*text_inputs, *media_inputs)

    def _resolve_media_inputs(
        self,
        workflow_id: str,
        target_node_id: str,
    ) -> tuple[ResolvedMediaInputSnapshotV2, ...]:
        workflow = self._workflows.get_workflow(workflow_id)
        resolved: list[ResolvedMediaInputSnapshotV2] = []
        for binding in workflow.bindings:
            if binding.target_node_id != target_node_id or binding.binding_kind not in {
                "image_reference",
                "video_reference",
                "audio_reference",
            }:
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
                    continue
                asset = self._resolve_asset(source.output_asset_id)
                source_kind = "node"
                source_node_id = source.node_id
                source_revision = source.revision
            else:
                asset = self._resolve_asset(binding.source.asset_id)
                source_kind = "image_asset"
            resolved.append(
                ResolvedMediaInputSnapshotV2(
                    source_kind=source_kind,
                    source_node_id=source_node_id,
                    source_node_revision=source_revision,
                    binding_kind=binding.binding_kind,
                    asset_id=asset.asset_id,
                    media_type=asset.media_type,
                    asset_checksum=asset.checksum,
                    access_descriptor=StorageAccessDescriptorV2(
                        asset_id=asset.asset_id,
                        media_url=asset.media_url or asset.preview_url or "",
                        checksum=asset.checksum,
                    ),
                )
            )
        return tuple(resolved)

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

    @staticmethod
    def _assert_acyclic(
        bindings: tuple[CanvasBindingV2, ...],
        *,
        source_node_id: str,
        target_node_id: str,
    ) -> None:
        if source_node_id == target_node_id:
            raise _cycle_error()
        outgoing: dict[str, set[str]] = {}
        for binding in bindings:
            if isinstance(binding.source, CanvasBindingSourceNodeV2):
                outgoing.setdefault(binding.source.node_id, set()).add(binding.target_node_id)
        pending = [target_node_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == source_node_id:
                raise _cycle_error()
            if current in visited:
                continue
            visited.add(current)
            pending.extend(outgoing.get(current, ()))


def _validate_node_binding_kind(node_type: str, binding_kind: str) -> None:
    compatible = {
        "text": {"brief_context"},
        "script": {"script_context"},
        "image": {"image_reference"},
        "video": {"video_reference"},
        "audio": {"audio_reference"},
    }
    if binding_kind not in compatible.get(node_type, set()):
        raise _media_incompatible_error()


def _validate_editing_binding(bindings, source, target_node_id: str, request) -> None:
    if source.node_type == "video" and request.binding_kind == "video_reference":
        return
    if source.node_type == "audio" and request.binding_kind == "audio_reference":
        if source.semantic_role != "bgm":
            raise V2PersistenceError(
                "editing_audio_role_invalid",
                "Editing audio input must use the bgm semantic role.",
                stage="agent_canvas_binding_service",
            )
        if any(
            binding.target_node_id == target_node_id and binding.binding_kind == "audio_reference"
            for binding in bindings
        ):
            raise V2PersistenceError(
                "editing_duplicate_bgm",
                "Editing accepts at most one BGM audio binding.",
                stage="agent_canvas_binding_service",
            )
        return
    raise _media_incompatible_error()


def _cycle_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_cycle_detected",
        "The binding would create a cycle.",
        stage="agent_canvas_binding_service",
    )


def _media_incompatible_error() -> V2PersistenceError:
    return V2PersistenceError(
        "binding_media_incompatible",
        "Binding kind is incompatible with the source media.",
        stage="agent_canvas_binding_service",
    )


def _binding_input_type(binding_kind: str) -> str:
    return {
        "brief_context": "text",
        "script_context": "text",
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
