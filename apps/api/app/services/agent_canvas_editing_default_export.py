"""Wait for bound upstream media, export the default cut once, and publish it on Canvas."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from app.persistence.agent_canvas_editing_default_export_repository import (
    DEFAULT_EXPORT_INTENT,
    DefaultEditingExport,
    EditingDefaultExportRepository,
)
from app.persistence.agent_canvas_editing_repository import AgentCanvasEditingExportRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import (
    AgentCanvasWorkflowV2,
    CanvasBindingSourceNodeV2,
    CanvasBindingV2,
    ProjectAssetSummaryV2,
)
from app.schemas.agent_canvas_editing import EditingExportRequestV2, EditingNodeContentV2
from app.schemas.agent_canvas_editing_output_reuse import EditingExportOutputReuseRequestV2
from app.services.agent_canvas_editing import EditingNodeService
from app.services.agent_canvas_editing_export import EditingExportService
from app.services.agent_canvas_editing_output_reuse import EditingExportOutputReuseService
from app.services.agent_canvas_editing_timeline import normalize_manifest
from app.services.v2_final_composition_renderer import V2MediaProbe, MediaProbe, V2MediaProbeResult

logger = logging.getLogger(__name__)


def ready_upstream_outputs(
    workflow: AgentCanvasWorkflowV2,
    editing_node_id: str,
    *,
    asset: Callable[[str], ProjectAssetSummaryV2],
    path: Callable[[str], Path],
    version_path: Callable[[str, str], Path],
) -> dict[str, str] | None:
    """Follow enabled Canvas bindings only; unrelated nodes never block a cut."""
    nodes = {node.node_id: node for node in workflow.nodes}
    incoming: dict[str, list[CanvasBindingV2]] = {}
    outputs: dict[str, str] = {}
    for binding in workflow.bindings:
        if binding.enabled:
            incoming.setdefault(binding.target_node_id, []).append(binding)
    visited = {editing_node_id}
    pending = [editing_node_id]
    found_video = False

    def ready_asset(asset_id: str | None, media_type: str | None = None) -> bool:
        if not asset_id:
            return False
        try:
            item = asset(asset_id)
            return (
                item.status == "ready"
                and (media_type is None or item.media_type == media_type)
                and path(asset_id).is_file()
            )
        except (V2PersistenceError, OSError, LookupError):
            return False

    while pending:
        target = pending.pop()
        for binding in incoming.get(target, ()):
            if not isinstance(binding.source, CanvasBindingSourceNodeV2):
                reference = binding.source
                if reference.source_asset_version_id:
                    try:
                        if not version_path(
                            reference.asset_id, reference.source_asset_version_id
                        ).is_file():
                            return None
                    except (V2PersistenceError, OSError, LookupError):
                        return None
                elif not ready_asset(reference.asset_id, "image"):
                    return None
                continue
            source = nodes.get(binding.source.source_node_id)
            if source is None:
                return None
            if source.node_id in visited:
                continue
            visited.add(source.node_id)
            pending.append(source.node_id)
            if source.node_type in {"image", "video", "audio", "editing"}:
                kind = "video" if source.node_type == "editing" else source.node_type
                if source.status != "ready" or not ready_asset(source.output_asset_id, kind):
                    return None
                outputs[source.node_id] = source.output_asset_id
                if target == editing_node_id and kind == "video":
                    found_video = True
    content = EditingNodeContentV2.model_validate(nodes[editing_node_id].structured_content)
    for entry in content.manifest.video_entries:
        if entry.enabled and entry.asset_id:
            if not ready_asset(entry.asset_id, "video"):
                return None
            found_video = True
    bgm = content.manifest.bgm
    if bgm and bgm.enabled and bgm.asset_id and not ready_asset(bgm.asset_id, "audio"):
        return None
    return outputs if found_video else None


class EditingDefaultExportCoordinator:
    def __init__(
        self,
        *,
        repository: EditingDefaultExportRepository,
        workflows: AgentCanvasWorkflowRepository,
        nodes: EditingNodeService,
        exports: EditingExportService,
        export_records: AgentCanvasEditingExportRepository,
        output_reuse: EditingExportOutputReuseService,
        asset_resolver: Callable[[str], ProjectAssetSummaryV2],
        asset_path: Callable[[str], Path],
        asset_version_path: Callable[[str, str], Path],
        probe: MediaProbe | None = None,
    ) -> None:
        self.repository = repository
        self._workflows = workflows
        self._nodes = nodes
        self._exports = exports
        self._export_records = export_records
        self._output_reuse = output_reuse
        self._asset = asset_resolver
        self._path = asset_path
        self._version_path = asset_version_path
        self._probe = probe or V2MediaProbe()

    def run_once(self) -> None:
        self.repository.discover()
        for job in self.repository.pending():
            try:
                self._advance(job)
            except V2PersistenceError as error:
                # Revision races and transient publication failures keep the same durable identity.
                self.repository.record(job, status=job.status, error_code=error.code)
            except Exception:
                logger.exception(
                    "Automatic default Editing delivery failed for node %s", job.node_id
                )

    def _advance(self, job: DefaultEditingExport) -> None:
        export_id = job.export_id or self.repository.accepted_export(job)
        workflow = self._workflows.get_workflow(job.workflow_id)
        node = next((node for node in workflow.nodes if node.node_id == job.node_id), None)
        if node is None:
            return
        if export_id is None:
            if node.metadata.get(DEFAULT_EXPORT_INTENT) is not True:
                self.repository.record(job, status="skipped")
                return
            outputs = ready_upstream_outputs(
                workflow,
                job.node_id,
                asset=self._asset,
                path=self._path,
                version_path=self._version_path,
            )
            if outputs is None:
                self.repository.record(job, status="waiting")
                return
            if self._prepare_timeline(workflow, job.node_id):
                # Recheck readiness against the new authoring revision on the next poll.
                return
            manifest = self._nodes.content_from_snapshot(workflow, job.node_id).manifest
            accepted = self._exports.start(
                job.workflow_id,
                job.node_id,
                EditingExportRequestV2(expected_manifest_revision=manifest.manifest_revision),
                idempotency_key=job.idempotency_key,
                required_ready_outputs=outputs,
                expected_workflow_revision=workflow.revision,
            )
            export_id = accepted.export_id
            self.repository.record(job, status="exporting", export_id=export_id)
        self._exports.resume(export_id)
        runtime = self._export_records.get(export_id)
        if runtime.status in {"failed", "cancelled"}:
            self.repository.record(
                job,
                status="failed" if runtime.status == "failed" else "skipped",
                export_id=export_id,
                error_code=runtime.error.code if runtime.error else None,
            )
            return
        if runtime.status != "completed":
            self.repository.record(job, status="exporting", export_id=export_id)
            return
        # An exact export version is imported; later manual exports never alter this node.
        latest = self._workflows.get_workflow(job.workflow_id)
        imported = self._output_reuse.import_export(
            job.workflow_id,
            job.node_id,
            EditingExportOutputReuseRequestV2(
                export_id=export_id, title="Final video", position=job.position
            ),
            expected_revision=latest.revision,
            idempotency_key=job.idempotency_key + ":canvas",
        )
        self.repository.record(
            job, status="completed", export_id=export_id, output_node_id=imported.node.node_id
        )

    def _prepare_timeline(self, workflow: AgentCanvasWorkflowV2, node_id: str) -> bool:
        node = next(node for node in workflow.nodes if node.node_id == node_id)
        manifest = EditingNodeContentV2.model_validate(node.structured_content).manifest
        nodes = {item.node_id: item for item in workflow.nodes}
        bindings = {item.binding_id: item for item in workflow.bindings}
        enabled_entries = tuple(
            entry
            for entry in manifest.video_entries
            if entry.enabled and (entry.binding_id is None or bindings[entry.binding_id].enabled)
        )
        bgm = manifest.bgm
        if bgm and (not bgm.enabled or (bgm.binding_id and not bindings[bgm.binding_id].enabled)):
            bgm = None
        original = manifest
        manifest = manifest.model_copy(
            update={
                "video_entries": tuple(
                    entry.model_copy(update={"timeline_start_seconds": None})
                    for entry in enabled_entries
                ),
                "bgm": bgm,
                "timeline_duration_seconds": None,
            }
        )
        durations: dict[tuple[str, str], float] = {}
        for entry in manifest.video_entries:
            asset_id = entry.asset_id
            if entry.binding_id:
                binding = bindings[entry.binding_id]
                if isinstance(binding.source, CanvasBindingSourceNodeV2):
                    asset_id = nodes[binding.source.source_node_id].output_asset_id
            if not asset_id:
                raise V2PersistenceError(
                    "editing_inputs_pending", "A timeline source is not ready."
                )
            duration = self._asset(asset_id).duration_seconds
            if duration is None:
                path = self._path(asset_id)
                probe = V2MediaProbeResult.from_payload(
                    self._probe(path, "video"), path=path, media_type="video"
                )
                duration = probe.duration_seconds if not probe.error else None
            if duration is None or duration <= 0:
                raise V2PersistenceError(
                    "editing_source_duration_unavailable",
                    "A video source has no readable duration.",
                )
            durations[entry.source_key] = duration
        prepared = normalize_manifest(manifest, source_durations=durations)
        if prepared == original:
            return False
        self._nodes.update_manifest(
            workflow.workflow_id,
            node_id,
            prepared,
            expected_revision=workflow.revision,
            automatic_default=True,
        )
        return True
