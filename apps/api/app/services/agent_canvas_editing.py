"""Manifest, preview, and input resolution for Agent Canvas Editing nodes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    CanvasNodeV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_editing import (
    EditingBgmEntryV2,
    EditingManifestV2,
    EditingNodeContentV2,
    EditingPreviewClipV2,
    EditingPreviewV2,
    EditingSkippedInputV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_editing_timeline import normalize_manifest


AssetResolver = Callable[[str], ProjectAssetSummaryV2]
AssetPathResolver = Callable[[str], Path]


@dataclass(frozen=True, slots=True)
class ResolvedEditingMedia:
    asset: ProjectAssetSummaryV2
    path: Path
    binding_id: str | None = None
    node_id: str | None = None
    video_entry: EditingVideoEntryV2 | None = None
    bgm_entry: EditingBgmEntryV2 | None = None

    @property
    def reference_id(self) -> str:
        return self.binding_id or self.asset.asset_id


@dataclass(frozen=True, slots=True)
class ResolvedEditingInputs:
    videos: tuple[ResolvedEditingMedia, ...]
    bgm: ResolvedEditingMedia | None
    skipped: tuple[EditingSkippedInputV2, ...]
    timeline_duration_seconds: float | None = None


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
        workflow = self._workflows.get_workflow(workflow_id)
        return self.content_from_snapshot(workflow, node_id)

    def content_from_snapshot(
        self,
        workflow: AgentCanvasWorkflowV2,
        node_id: str,
    ) -> EditingNodeContentV2:
        """Build canonical content from an authoring snapshot without persisting it."""

        node = next(
            (item for item in workflow.nodes if item.node_id == node_id),
            None,
        )
        if node is None:
            raise _error("node_not_found", "Node was not found.")
        if node.node_type != "editing":
            raise _error("node_type_mismatch", "Node is not an Editing node.")
        content = EditingNodeContentV2.model_validate(node.structured_content)
        self._validate_manifest_bindings_from_snapshot(
            workflow,
            node_id,
            content.manifest,
        )
        manifest = self._response_manifest(
            workflow,
            node_id,
            content.manifest,
            current_manifest=content.manifest,
        )
        return content.model_copy(
            update={
                "manifest": manifest,
                "preview": self._preview_from_manifest(workflow, manifest),
            }
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
        workflow = self._workflows.get_workflow(workflow_id)
        self._validate_manifest_bindings_from_snapshot(workflow, node_id, manifest)
        current = EditingNodeContentV2.model_validate(node.structured_content)
        updated_manifest = self._canonical_manifest(
            workflow,
            node_id,
            manifest,
            current_manifest=current.manifest,
        ).model_copy(
            update={
                "manifest_revision": current.manifest.manifest_revision + 1,
            }
        )
        updated_content = current.model_copy(
            update={
                "manifest": updated_manifest,
                "dirty": True,
                "preview": self._build_preview(workflow, node_id, updated_manifest),
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
        workflow = self._workflows.get_workflow(workflow_id)
        return self._build_preview(workflow, node_id, manifest)

    def _build_preview(
        self,
        workflow: AgentCanvasWorkflowV2,
        node_id: str,
        manifest: EditingManifestV2 | None = None,
    ) -> EditingPreviewV2:
        node = next(
            (item for item in workflow.nodes if item.node_id == node_id),
            None,
        )
        if node is None:
            raise _error("node_not_found", "Node was not found.")
        if node.node_type != "editing":
            raise _error("node_type_mismatch", "Node is not an Editing node.")
        current_manifest = EditingNodeContentV2.model_validate(node.structured_content).manifest
        selected = self._canonical_manifest(
            workflow,
            node_id,
            manifest or current_manifest,
            current_manifest=current_manifest,
        )
        return self._preview_from_manifest(workflow, selected)

    def _preview_from_manifest(
        self,
        workflow: AgentCanvasWorkflowV2,
        selected: EditingManifestV2,
    ) -> EditingPreviewV2:
        bindings = {binding.binding_id: binding for binding in workflow.bindings}
        nodes = {item.node_id: item for item in workflow.nodes}
        clips: list[EditingPreviewClipV2] = []
        warnings: list[str] = []
        ordered_entries = sorted(
            enumerate(selected.video_entries),
            key=lambda item: (
                item[1].timeline_start_seconds
                if item[1].timeline_start_seconds is not None
                else 0.0,
                item[1].source_key,
                item[0],
            ),
        )
        for order, (_, entry) in enumerate(ordered_entries):
            binding = bindings.get(entry.binding_id) if entry.binding_id else None
            source = _source_node(binding, nodes)
            asset = _entry_asset(
                entry,
                source=source,
                resolver=self._asset_resolver,
            )
            warning = _entry_warning(entry, source=source, asset=asset)
            clips.append(
                EditingPreviewClipV2(
                    reference_id=entry.binding_id or entry.asset_id or "",
                    binding_id=entry.binding_id,
                    node_id=source.node_id if source else None,
                    asset_id=asset.asset_id if asset else None,
                    status=_entry_status(source=source, asset=asset),
                    display_order=order,
                    preview_url=(
                        asset.preview_url or asset.media_url if asset is not None else None
                    ),
                    duration_seconds=_entry_duration(entry, asset),
                    warning=warning,
                )
            )
            if warning:
                warnings.append(f"{entry.binding_id or entry.asset_id}:{warning}")
        bgm_binding = (
            bindings.get(selected.bgm.binding_id)
            if selected.bgm is not None and selected.bgm.binding_id is not None
            else None
        )
        bgm_source = _source_node(bgm_binding, nodes)
        bgm_asset = (
            _entry_asset(
                selected.bgm,
                source=bgm_source,
                resolver=self._asset_resolver,
            )
            if selected.bgm is not None
            else None
        )
        if selected.bgm is not None:
            warning = _entry_warning(selected.bgm, source=bgm_source, asset=bgm_asset)
            if warning:
                warnings.append(f"{selected.bgm.binding_id or selected.bgm.asset_id}:{warning}")
        return EditingPreviewV2(
            clips=tuple(clips),
            bgm_binding_id=selected.bgm.binding_id if selected.bgm else None,
            bgm_node_id=bgm_source.node_id if bgm_source else None,
            bgm_asset_id=bgm_asset.asset_id if bgm_asset else None,
            estimated_duration_seconds=(
                selected.timeline_duration_seconds
                if selected.timeline_duration_seconds is not None
                else sum(clip.duration_seconds or 0 for clip in clips if clip.warning is None)
            ),
            warnings=tuple(warnings),
        )

    def _response_manifest(
        self,
        workflow: AgentCanvasWorkflowV2,
        node_id: str,
        manifest: EditingManifestV2,
        *,
        current_manifest: EditingManifestV2 | None = None,
    ) -> EditingManifestV2:
        try:
            return self._canonical_manifest(
                workflow,
                node_id,
                manifest,
                current_manifest=current_manifest,
            )
        except V2PersistenceError as error:
            if (
                error.code != "editing_timeline_duration_invalid"
                or manifest.timeline_duration_seconds is not None
            ):
                raise
            return manifest

    def _canonical_manifest(
        self,
        workflow: AgentCanvasWorkflowV2,
        node_id: str,
        manifest: EditingManifestV2,
        *,
        current_manifest: EditingManifestV2 | None = None,
    ) -> EditingManifestV2:
        return normalize_manifest(
            manifest,
            current_manifest=current_manifest,
            source_durations=self._source_durations(workflow, node_id, manifest),
        )

    def _source_durations(
        self,
        workflow: AgentCanvasWorkflowV2,
        node_id: str,
        manifest: EditingManifestV2,
    ) -> dict[tuple[str, str], float]:
        bindings = {binding.binding_id: binding for binding in workflow.bindings}
        nodes = {node.node_id: node for node in workflow.nodes}
        durations: dict[tuple[str, str], float] = {}
        for entry in manifest.video_entries:
            source = (
                _source_node(bindings.get(entry.binding_id), nodes)
                if entry.binding_id is not None
                else None
            )
            asset = _entry_asset(entry, source=source, resolver=self._asset_resolver)
            if asset is not None and asset.duration_seconds is not None:
                durations[entry.source_key] = asset.duration_seconds
        return durations

    def _validate_manifest_bindings_from_snapshot(
        self,
        workflow: AgentCanvasWorkflowV2,
        node_id: str,
        manifest: EditingManifestV2,
    ) -> None:
        nodes = {node.node_id: node for node in workflow.nodes}
        bindings = {binding.binding_id: binding for binding in workflow.bindings}
        for entry in manifest.video_entries:
            if entry.binding_id is not None:
                binding = bindings.get(entry.binding_id)
                source = _manifest_binding_source(
                    binding,
                    nodes,
                    target_node_id=node_id,
                    input_role="video_reference",
                )
                if source.node_type != "video":
                    raise _error(
                        "editing_manifest_invalid",
                        "Editing video bindings must reference Video nodes.",
                    )
                continue
            asset = _required_asset(self._asset_resolver, entry.asset_id)
            _validate_project_asset(workflow.workflow_id, workflow.project_id, asset, "video")
        if manifest.bgm is None:
            return
        if manifest.bgm.binding_id is not None:
            binding = bindings.get(manifest.bgm.binding_id)
            source = _manifest_binding_source(
                binding,
                nodes,
                target_node_id=node_id,
                input_role="audio_reference",
            )
            if source.node_type != "audio" or source.creative_role != "bgm":
                raise _error(
                    "editing_audio_role_invalid",
                    "Editing audio input must use the bgm creative role.",
                )
            return
        asset = _required_asset(self._asset_resolver, manifest.bgm.asset_id)
        _validate_project_asset(workflow.workflow_id, workflow.project_id, asset, "audio")

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
        manifest = normalize_manifest(
            manifest,
            source_durations=_manifest_source_durations(
                manifest,
                bindings=bindings,
                nodes=nodes,
                resolver=self._asset_resolver,
            ),
        )
        videos: list[ResolvedEditingMedia] = []
        skipped: list[EditingSkippedInputV2] = []
        for entry in manifest.video_entries:
            if not entry.enabled:
                continue
            source = (
                _source_node(bindings.get(entry.binding_id), nodes)
                if entry.binding_id is not None
                else None
            )
            reference_id = entry.binding_id or entry.asset_id or ""
            reason = _entry_skip_reason(entry, source=source)
            if reason is not None:
                skipped.append(
                    EditingSkippedInputV2(
                        reference_id=reference_id,
                        node_id=source.node_id if source else None,
                        asset_id=entry.asset_id,
                        reason=reason,
                    )
                )
                continue
            try:
                asset = _required_asset(
                    self._asset_resolver,
                    source.output_asset_id if source is not None else entry.asset_id,
                )
                _validate_project_asset(
                    workflow_id,
                    workflow.project_id,
                    asset,
                    "video",
                )
                if asset.status != "ready" or not _entry_trim_is_valid(entry, asset):
                    raise ValueError("Editing video input is not available.")
                path = self._path_resolver(asset.asset_id)
                if not path.is_file():
                    raise OSError("Editing video file is unavailable.")
            except (LookupError, OSError, ValueError, V2PersistenceError):
                skipped.append(
                    EditingSkippedInputV2(
                        reference_id=reference_id,
                        node_id=source.node_id if source else None,
                        asset_id=entry.asset_id,
                        reason="source_media_invalid",
                    )
                )
                continue
            videos.append(
                ResolvedEditingMedia(
                    asset=asset,
                    path=path,
                    binding_id=entry.binding_id,
                    node_id=source.node_id if source else None,
                    video_entry=entry,
                )
            )
        if not videos:
            raise _error(
                "no_exportable_media",
                "Editing Export has no usable media input.",
            )
        bgm = None
        if manifest.bgm is not None and manifest.bgm.enabled:
            bgm_entry = manifest.bgm
            source = (
                _source_node(bindings.get(bgm_entry.binding_id), nodes)
                if bgm_entry.binding_id is not None
                else None
            )
            if _entry_skip_reason(bgm_entry, source=source) is None:
                try:
                    asset = _required_asset(
                        self._asset_resolver,
                        source.output_asset_id if source is not None else bgm_entry.asset_id,
                    )
                    _validate_project_asset(
                        workflow_id,
                        workflow.project_id,
                        asset,
                        "audio",
                    )
                    if asset.status != "ready" or not _entry_trim_is_valid(bgm_entry, asset):
                        raise ValueError("Editing BGM input is not available.")
                    path = self._path_resolver(asset.asset_id)
                    if not path.is_file():
                        raise OSError("Editing BGM file is unavailable.")
                    bgm = ResolvedEditingMedia(
                        asset=asset,
                        path=path,
                        binding_id=bgm_entry.binding_id,
                        node_id=source.node_id if source else None,
                        bgm_entry=bgm_entry,
                    )
                except (LookupError, OSError, ValueError, V2PersistenceError):
                    bgm = None
        return ResolvedEditingInputs(
            videos=tuple(videos),
            bgm=bgm,
            skipped=tuple(skipped),
            timeline_duration_seconds=manifest.timeline_duration_seconds,
        )


def _source_node(
    binding: CanvasBindingV2 | None,
    nodes: dict[str, CanvasNodeV2],
) -> CanvasNodeV2 | None:
    if binding is None or not isinstance(binding.source, CanvasBindingSourceNodeV2):
        return None
    return nodes.get(binding.source.source_node_id)


def _entry_asset(
    entry: EditingVideoEntryV2 | EditingBgmEntryV2,
    *,
    source: CanvasNodeV2 | None,
    resolver: AssetResolver,
) -> ProjectAssetSummaryV2 | None:
    return _safe_asset(
        resolver,
        source.output_asset_id if source is not None else entry.asset_id,
    )


def _manifest_source_durations(
    manifest: EditingManifestV2,
    *,
    bindings: dict[str, CanvasBindingV2],
    nodes: dict[str, CanvasNodeV2],
    resolver: AssetResolver,
) -> dict[tuple[str, str], float]:
    durations: dict[tuple[str, str], float] = {}
    for entry in manifest.video_entries:
        source = (
            _source_node(bindings.get(entry.binding_id), nodes)
            if entry.binding_id is not None
            else None
        )
        asset = _entry_asset(entry, source=source, resolver=resolver)
        if asset is not None and asset.duration_seconds is not None:
            durations[entry.source_key] = asset.duration_seconds
    return durations


def _entry_warning(
    entry: EditingVideoEntryV2 | EditingBgmEntryV2,
    *,
    source: CanvasNodeV2 | None,
    asset: ProjectAssetSummaryV2 | None,
) -> str | None:
    if not entry.enabled:
        return "disabled"
    reason = _entry_skip_reason(entry, source=source)
    if reason is not None:
        return reason
    if asset is None:
        return "source_output_unavailable"
    if asset.status != "ready":
        return "source_not_ready"
    if not _entry_trim_is_valid(entry, asset):
        return "source_media_invalid"
    return None


def _entry_status(
    *,
    source: CanvasNodeV2 | None,
    asset: ProjectAssetSummaryV2 | None,
) -> str:
    if source is not None:
        return source.status
    return "ready" if asset is not None and asset.status == "ready" else "failed"


def _entry_duration(
    entry: EditingVideoEntryV2,
    asset: ProjectAssetSummaryV2 | None,
) -> float | None:
    if entry.trim_end_seconds is not None:
        return entry.trim_end_seconds - entry.trim_start_seconds
    if asset is None or asset.duration_seconds is None:
        return None
    return max(asset.duration_seconds - entry.trim_start_seconds, 0.0)


def _entry_skip_reason(
    entry: EditingVideoEntryV2 | EditingBgmEntryV2,
    *,
    source: CanvasNodeV2 | None,
) -> str | None:
    if entry.binding_id is None:
        return None
    if source is None:
        return "source_output_unavailable"
    return _skip_reason(source)


def _entry_trim_is_valid(
    entry: EditingVideoEntryV2 | EditingBgmEntryV2,
    asset: ProjectAssetSummaryV2,
) -> bool:
    duration = asset.duration_seconds
    if duration is None:
        return True
    if entry.trim_start_seconds >= duration:
        return False
    return entry.trim_end_seconds is None or entry.trim_end_seconds <= duration


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


def _required_asset(
    resolver: AssetResolver,
    asset_id: str | None,
) -> ProjectAssetSummaryV2:
    asset = _safe_asset(resolver, asset_id)
    if asset is None:
        raise _error(
            "editing_manifest_invalid",
            "An Editing manifest Asset reference was not found.",
        )
    return asset


def _validate_project_asset(
    workflow_id: str,
    project_id: str,
    asset: ProjectAssetSummaryV2,
    media_type: str,
) -> None:
    if asset.media_type != media_type:
        raise _error(
            "editing_manifest_invalid",
            f"Editing {media_type} entries must reference {media_type} Assets.",
        )
    if asset.workflow_id not in {None, workflow_id} and asset.project_id != project_id:
        raise _error(
            "editing_manifest_invalid",
            "Editing Asset references must belong to the current Project.",
        )


def _manifest_binding_source(
    binding: CanvasBindingV2 | None,
    nodes: dict[str, CanvasNodeV2],
    *,
    target_node_id: str,
    input_role: str,
) -> CanvasNodeV2:
    if (
        binding is None
        or binding.target_node_id != target_node_id
        or binding.input_role != input_role
    ):
        raise _error(
            "editing_manifest_invalid",
            "Editing Binding references must be connected to the Editing node.",
        )
    source = _source_node(binding, nodes)
    if source is None:
        raise _error(
            "editing_manifest_invalid",
            "Editing Binding source was not found.",
        )
    return source


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing")
