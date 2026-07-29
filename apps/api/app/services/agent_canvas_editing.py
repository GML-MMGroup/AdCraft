"""Manifest, preview, and input resolution for Agent Canvas Editing nodes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_editing import (
    EditingManifestV2,
    EditingNodeContentV2,
    EditingPreviewClipV2,
    EditingPreviewV2,
    EditingSkippedInputV2,
)


AssetResolver = Callable[[str], ProjectAssetSummaryV2]
AssetPathResolver = Callable[[str], Path]


@dataclass(frozen=True, slots=True)
class ResolvedEditingMedia:
    binding_id: str
    node_id: str
    asset: ProjectAssetSummaryV2
    path: Path


@dataclass(frozen=True, slots=True)
class ResolvedEditingInputs:
    videos: tuple[ResolvedEditingMedia, ...]
    bgm: ResolvedEditingMedia | None
    skipped: tuple[EditingSkippedInputV2, ...]


class EditingNodeService:
    """Validate and persist one typed Editing manifest."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        asset_resolver: AssetResolver,
    ) -> None:
        self._workflows = workflows
        self._asset_resolver = asset_resolver

    def content(self, workflow_id: str, node_id: str) -> EditingNodeContentV2:
        node = self._require_editing_node(workflow_id, node_id)
        content = EditingNodeContentV2.model_validate(node.structured_content)
        return content.model_copy(
            update={"preview": self.build_preview(workflow_id, node_id, content.manifest)}
        )

    def update_manifest(
        self,
        workflow_id: str,
        node_id: str,
        manifest: EditingManifestV2,
        *,
        expected_revision: int,
    ) -> CanvasNodeV2:
        node = self._require_editing_node(workflow_id, node_id)
        self._validate_manifest_bindings(workflow_id, node_id, manifest)
        current = EditingNodeContentV2.model_validate(node.structured_content)
        updated_manifest = manifest.model_copy(
            update={"manifest_revision": current.manifest.manifest_revision + 1}
        )
        updated_content = current.model_copy(
            update={
                "manifest": updated_manifest,
                "dirty": True,
                "preview": self.build_preview(workflow_id, node_id, updated_manifest),
                "active_export": None,
            }
        )
        updated = node.model_copy(
            update={
                "structured_content": updated_content.model_dump(mode="json"),
                "revision": node.revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._workflows.update_node(updated, expected_revision=expected_revision)
        return updated

    def build_preview(
        self,
        workflow_id: str,
        node_id: str,
        manifest: EditingManifestV2 | None = None,
    ) -> EditingPreviewV2:
        node = self._require_editing_node(workflow_id, node_id)
        selected = manifest or EditingNodeContentV2.model_validate(node.structured_content).manifest
        workflow = self._workflows.get_workflow(workflow_id)
        bindings = {binding.binding_id: binding for binding in workflow.bindings}
        nodes = {item.node_id: item for item in workflow.nodes}
        clips: list[EditingPreviewClipV2] = []
        warnings: list[str] = []
        for order, binding_id in enumerate(selected.ordered_video_binding_ids):
            binding = bindings.get(binding_id)
            source = _source_node(binding, nodes)
            warning = _source_warning(source)
            asset = _safe_asset(self._asset_resolver, source.output_asset_id if source else None)
            clips.append(
                EditingPreviewClipV2(
                    binding_id=binding_id,
                    node_id=source.node_id if source else "",
                    asset_id=asset.asset_id if asset else None,
                    status=source.status if source else "failed",
                    display_order=order,
                    preview_url=(
                        asset.preview_url or asset.media_url if asset is not None else None
                    ),
                    duration_seconds=asset.duration_seconds if asset else None,
                    warning=warning,
                )
            )
            if warning:
                warnings.append(f"{binding_id}:{warning}")
        bgm_binding = (
            bindings.get(selected.bgm_audio_binding_id) if selected.bgm_audio_binding_id else None
        )
        bgm_source = _source_node(bgm_binding, nodes)
        bgm_asset = _safe_asset(
            self._asset_resolver,
            bgm_source.output_asset_id if bgm_source else None,
        )
        if selected.bgm_audio_binding_id and _source_warning(bgm_source):
            warnings.append(f"{selected.bgm_audio_binding_id}:source_not_ready")
        return EditingPreviewV2(
            clips=tuple(clips),
            bgm_binding_id=selected.bgm_audio_binding_id,
            bgm_node_id=bgm_source.node_id if bgm_source else None,
            bgm_asset_id=bgm_asset.asset_id if bgm_asset else None,
            estimated_duration_seconds=sum(
                clip.duration_seconds or 0 for clip in clips if clip.warning is None
            ),
            warnings=tuple(warnings),
        )

    def _validate_manifest_bindings(
        self,
        workflow_id: str,
        node_id: str,
        manifest: EditingManifestV2,
    ) -> None:
        workflow = self._workflows.get_workflow(workflow_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        incoming = tuple(
            binding for binding in workflow.bindings if binding.target_node_id == node_id
        )
        videos = tuple(binding for binding in incoming if binding.binding_kind == "video_reference")
        audio = tuple(binding for binding in incoming if binding.binding_kind == "audio_reference")
        if set(manifest.ordered_video_binding_ids) != {binding.binding_id for binding in videos}:
            raise _error(
                "editing_manifest_invalid",
                "The Editing manifest must order every connected video binding exactly once.",
            )
        for binding in videos:
            source = _source_node(binding, nodes)
            if source is None or source.node_type != "video":
                raise _error(
                    "editing_manifest_invalid",
                    "Editing video bindings must reference Video nodes.",
                )
        if len(audio) > 1:
            raise _error(
                "editing_duplicate_bgm",
                "Editing accepts at most one BGM audio binding.",
            )
        expected_bgm = audio[0].binding_id if audio else None
        if manifest.bgm_audio_binding_id != expected_bgm:
            raise _error(
                "editing_manifest_invalid",
                "The Editing manifest BGM binding does not match its connected input.",
            )
        if audio:
            source = _source_node(audio[0], nodes)
            if source is None or source.node_type != "audio" or source.semantic_role != "bgm":
                raise _error(
                    "editing_audio_role_invalid",
                    "Editing audio input must use the bgm semantic role.",
                )

    def _require_editing_node(self, workflow_id: str, node_id: str) -> CanvasNodeV2:
        node = self._workflows.get_node(workflow_id, node_id)
        if node.node_type != "editing":
            raise _error("node_type_mismatch", "Node is not an Editing node.")
        return node


class EditingInputResolver:
    """Resolve only manifest-selected Ready inputs without waiting."""

    def __init__(
        self,
        workflows: AgentCanvasWorkflowRepository,
        asset_resolver: AssetResolver,
        path_resolver: AssetPathResolver,
    ) -> None:
        self._workflows = workflows
        self._asset_resolver = asset_resolver
        self._path_resolver = path_resolver

    def resolve(
        self,
        workflow_id: str,
        node_id: str,
        manifest: EditingManifestV2,
    ) -> ResolvedEditingInputs:
        workflow = self._workflows.get_workflow(workflow_id)
        bindings = {binding.binding_id: binding for binding in workflow.bindings}
        nodes = {node.node_id: node for node in workflow.nodes}
        videos: list[ResolvedEditingMedia] = []
        skipped: list[EditingSkippedInputV2] = []
        for binding_id in manifest.ordered_video_binding_ids:
            source = _source_node(bindings.get(binding_id), nodes)
            if source is None:
                continue
            reason = _skip_reason(source)
            if reason is not None:
                skipped.append(EditingSkippedInputV2(node_id=source.node_id, reason=reason))
                continue
            try:
                asset = self._asset_resolver(source.output_asset_id or "")
                path = self._path_resolver(asset.asset_id)
            except (OSError, V2PersistenceError):
                skipped.append(
                    EditingSkippedInputV2(
                        node_id=source.node_id,
                        reason="source_media_invalid",
                    )
                )
                continue
            videos.append(
                ResolvedEditingMedia(
                    binding_id=binding_id,
                    node_id=source.node_id,
                    asset=asset,
                    path=path,
                )
            )
        if not videos:
            raise _error(
                "editing_no_ready_video",
                "Editing Export requires at least one Ready video input.",
            )
        bgm = None
        if manifest.bgm_audio_binding_id is not None:
            source = _source_node(bindings.get(manifest.bgm_audio_binding_id), nodes)
            if source is not None and _skip_reason(source) is None:
                try:
                    asset = self._asset_resolver(source.output_asset_id or "")
                    bgm = ResolvedEditingMedia(
                        binding_id=manifest.bgm_audio_binding_id,
                        node_id=source.node_id,
                        asset=asset,
                        path=self._path_resolver(asset.asset_id),
                    )
                except (OSError, V2PersistenceError):
                    bgm = None
        return ResolvedEditingInputs(
            videos=tuple(videos),
            bgm=bgm,
            skipped=tuple(skipped),
        )


def _source_node(
    binding: CanvasBindingV2 | None,
    nodes: dict[str, CanvasNodeV2],
) -> CanvasNodeV2 | None:
    if binding is None or not isinstance(binding.source, CanvasBindingSourceNodeV2):
        return None
    return nodes.get(binding.source.node_id)


def _source_warning(node: CanvasNodeV2 | None) -> str | None:
    if node is None:
        return "source_output_unavailable"
    return _skip_reason(node)


def _skip_reason(node: CanvasNodeV2) -> str | None:
    if node.status == "failed":
        return "source_failed"
    if node.status != "ready":
        return "source_not_ready"
    if node.output_asset_id is None:
        return "source_output_unavailable"
    return None


def _safe_asset(
    resolver: AssetResolver,
    asset_id: str | None,
) -> ProjectAssetSummaryV2 | None:
    if asset_id is None:
        return None
    try:
        return resolver(asset_id)
    except (LookupError, V2PersistenceError):
        return None


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing")
