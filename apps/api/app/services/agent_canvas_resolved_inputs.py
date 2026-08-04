"""Compile persisted Agent Canvas bindings into immutable run inputs."""

from __future__ import annotations

import hashlib
import json

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
from app.services.agent_canvas_bindings import AgentCanvasBindingService


class AgentCanvasResolvedInputCompiler:
    """Resolve only persisted target bindings in canonical order."""

    def __init__(self, bindings: AgentCanvasBindingService) -> None:
        self._bindings = bindings

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
        text_inputs = tuple(
            ResolvedTextBindingInputV2(
                binding_id=item.binding_id or _missing_binding_id(item.source_node_id),
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                input_role=item.input_role,
                required=item.required,
                display_order=item.display_order,
                snapshot_id=text_snapshot.snapshot_id,
                document_kind=item.document_kind,
                content_digest=item.content_hash,
                content=item.content,
            )
            for item in text_snapshot.inputs
        )
        media_inputs = tuple(
            ResolvedMediaBindingInputV2(
                binding_id=item.binding_id or _missing_binding_id(item.asset_id),
                source_kind=item.source_kind,
                source_node_id=item.source_node_id,
                source_node_revision=item.source_node_revision,
                input_role=item.input_role,
                source_semantic_role=item.source_semantic_role,
                required=item.required,
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
            for item in omitted
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
                required=item.required,
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
                    asset_id=item.asset_id,
                    asset_version_id=item.asset_version_id,
                    media_type=item.media_type,
                    asset_checksum=item.checksum,
                    access_descriptor=StorageAccessDescriptorV2(
                        asset_id=item.asset_id,
                        media_url=asset.media_url or asset.preview_url or "",
                        checksum=item.checksum,
                    ),
                    binding_id=item.binding_id,
                    input_role=item.input_role,
                    required=item.required,
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


def _node_index(workflow: AgentCanvasWorkflowV2, node_id: str) -> int:
    return next(index for index, node in enumerate(workflow.nodes) if node.node_id == node_id)
