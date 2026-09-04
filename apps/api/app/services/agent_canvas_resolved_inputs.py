"""Compile persisted Agent Canvas bindings into immutable run inputs."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    OmittedOptionalInputV2,
    ResolvedInputSnapshotV2,
    ResolvedMediaBindingInputV2,
    ResolvedMediaInputSnapshotV2,
    ResolvedNodeInputManifestV2,
    ResolvedTextBindingInputV2,
    ResolvedTextInputSnapshotV2,
    StorageAccessDescriptorV2,
)
from app.schemas.agent_canvas_runtime import NodeRunBindingSnapshotV2
from app.persistence.errors import V2PersistenceError
from app.services.agent_canvas_bindings import AgentCanvasBindingService

if TYPE_CHECKING:
    from app.services.agent_canvas_world_setting_context import (
        WorldSettingContextResolverV2,
    )


class AgentCanvasResolvedInputCompiler:
    """Resolve only persisted target bindings in canonical order."""

    def __init__(
        self,
        bindings: AgentCanvasBindingService,
        *,
        world_settings: "WorldSettingContextResolverV2 | None" = None,
    ) -> None:
        self._bindings = bindings
        self._world_settings = world_settings

    def compile(
        self,
        *,
        workflow_id: str,
        target_node_id: str,
        execution_id: str,
        node_run_id: str,
        run_intent_snapshot_id: str | None = None,
        binding_snapshots: tuple[NodeRunBindingSnapshotV2, ...] | None = None,
    ) -> ResolvedNodeInputManifestV2:
        workflow = self._bindings.get_workflow(workflow_id)
        _require_explicit_document_source_bindings(workflow, target_node_id)
        if binding_snapshots is None:
            text_snapshot = self._bindings.capture_prompt_context_snapshot(
                workflow_id,
                target_node_id,
                node_run_id=node_run_id,
            )
            media_snapshots, omitted = self._bindings.resolve_media_input_snapshots(
                workflow_id,
                target_node_id,
            )
        else:
            frozen = self._bindings.resolve_frozen_run_input_resolution(
                workflow_id,
                target_node_id,
                binding_snapshots,
                node_run_id=node_run_id,
            )
            text_snapshot = self._bindings.get_prompt_context_snapshot_for_run(
                workflow_id,
                target_node_id,
                node_run_id=node_run_id,
            )
            media_snapshots = tuple(
                item for item in frozen.inputs if isinstance(item, ResolvedMediaInputSnapshotV2)
            )
            omitted = frozen.optional_omissions
        resolved_text_inputs = tuple(
            ResolvedTextBindingInputV2(
                binding_id=item.binding_id or _missing_binding_id(item.source_node_id),
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                input_role=item.input_role,
                display_order=item.display_order,
                snapshot_id=text_snapshot.snapshot_id,
                document_kind=item.document_kind,
                content_digest=item.content_hash,
                content=item.content,
                source_semantic_role=item.source_semantic_role,
                binding_metadata=item.binding_metadata,
                source_structured_content=item.source_structured_content,
            )
            for item in text_snapshot.inputs
        )
        text_inputs: list[ResolvedTextBindingInputV2] = []
        world_setting_inputs = []
        omitted_list = list(omitted)
        for item in resolved_text_inputs:
            if item.source_semantic_role != "world_setting":
                text_inputs.append(item)
                continue
            if self._world_settings is None:
                error = V2PersistenceError(
                    "world_setting_context_unavailable",
                    "World Setting context resolution is unavailable.",
                    stage="agent_canvas_resolved_input_compiler",
                )
                raise error
            try:
                world_setting_inputs.append(
                    self._world_settings.resolve_for_run(
                        workflow_id=workflow_id,
                        source=item,
                    )
                )
            except V2PersistenceError:
                raise
        if len(world_setting_inputs) > 1:
            raise V2PersistenceError(
                "world_setting_binding_ambiguous",
                "A target Node cannot resolve more than one World Setting Binding.",
                stage="agent_canvas_resolved_input_compiler",
            )
        media_inputs = tuple(
            ResolvedMediaBindingInputV2(
                binding_id=item.binding_id or _missing_binding_id(item.asset_id),
                source_kind=item.source_kind,
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                input_role=item.input_role,
                source_semantic_role=item.source_semantic_role,
                binding_metadata=item.binding_metadata,
                source_structured_content=item.source_structured_content,
                display_order=item.display_order,
                asset_id=item.asset_id,
                asset_version_id=item.asset_version_id,
                media_type=item.media_type,
                checksum=item.asset_checksum,
            )
            for item in media_snapshots
        )
        omitted_inputs = tuple(
            OmittedOptionalInputV2(
                binding_id=item["binding_id"],
                source_node_id=item.get("source_node_id"),
                reason_code=item["reason"],
            )
            for item in omitted_list
        )
        created_at = (
            text_snapshot.created_at
            if text_snapshot.inputs
            else self._bindings.get_workflow(workflow_id)
            .nodes[_node_index(workflow, target_node_id)]
            .updated_at
        )
        identity = {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "node_run_id": node_run_id,
            "target_node_id": target_node_id,
            "workflow_revision": workflow.revision,
            "text_inputs": [item.model_dump(mode="json") for item in text_inputs],
            "world_setting_inputs": [item.model_dump(mode="json") for item in world_setting_inputs],
            "media_inputs": [item.model_dump(mode="json") for item in media_inputs],
            "omitted_optional_inputs": [item.model_dump(mode="json") for item in omitted_inputs],
            "run_intent_snapshot_id": run_intent_snapshot_id,
        }
        manifest_digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ResolvedNodeInputManifestV2(
            manifest_id=f"input_manifest_{manifest_digest[:24]}",
            created_at=created_at,
            manifest_digest=manifest_digest,
            delivered_asset_version_ids=tuple(
                item.asset_version_id for item in media_inputs if item.asset_version_id is not None
            ),
            **identity,
        )

    def materialize_inputs(
        self,
        manifest: ResolvedNodeInputManifestV2,
    ) -> tuple[ResolvedInputSnapshotV2, ...]:
        text_inputs = tuple(
            ResolvedTextInputSnapshotV2(
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                document_kind=item.document_kind,
                content=item.content,
                content_hash=item.content_digest,
                binding_id=item.binding_id,
                input_role=item.input_role,
                display_order=item.display_order,
            )
            for item in manifest.text_inputs
        )
        media_inputs = []
        for item in manifest.media_inputs:
            asset = self._bindings.resolve_asset_version(
                item.asset_id,
                item.asset_version_id,
            )
            media_inputs.append(
                ResolvedMediaInputSnapshotV2(
                    source_kind=item.source_kind,
                    source_node_id=item.source_node_id,
                    source_node_revision=item.source_node_revision,
                    binding_kind=item.input_role,
                    source_semantic_role=item.source_semantic_role,
                    binding_metadata=item.binding_metadata,
                    source_structured_content=item.source_structured_content,
                    asset_id=item.asset_id,
                    asset_version_id=item.asset_version_id,
                    media_type=item.media_type,
                    asset_checksum=item.checksum,
                    access_descriptor=StorageAccessDescriptorV2(
                        asset_id=item.asset_id,
                        media_url=asset.media_url or "",
                        checksum=item.checksum,
                    ),
                    binding_id=item.binding_id,
                    input_role=item.input_role,
                    display_order=item.display_order,
                )
            )
        return tuple(
            sorted(
                (*text_inputs, *media_inputs),
                key=lambda item: (item.display_order, item.binding_id or ""),
            )
        )


def _missing_binding_id(identity: str) -> str:
    return f"binding_{hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def _require_explicit_document_source_bindings(
    workflow: AgentCanvasWorkflowV2,
    target_node_id: str,
) -> None:
    target = workflow.nodes[_node_index(workflow, target_node_id)]
    required_sources = target.metadata.get("required_agent_document_source_node_ids", ())
    if not isinstance(required_sources, (list, tuple)) or not all(
        isinstance(item, str) and item for item in required_sources
    ):
        return
    bound_sources = {
        binding.source.source_node_id
        for binding in workflow.bindings
        if binding.target_node_id == target_node_id and binding.source.kind == "node_output"
    }
    missing = tuple(source_id for source_id in required_sources if source_id not in bound_sources)
    if missing:
        raise V2PersistenceError(
            "agent_document_binding_required",
            "A required Agent document source has no persisted Canvas Binding.",
            stage="agent_canvas_resolved_input_compiler",
            details={"missing_source_node_ids": list(missing)},
        )


def _node_index(workflow: AgentCanvasWorkflowV2, node_id: str) -> int:
    return next(index for index, node in enumerate(workflow.nodes) if node.node_id == node_id)
