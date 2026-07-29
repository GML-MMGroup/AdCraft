"""Durable explicit Export lifecycle for Agent Canvas Editing nodes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app.persistence.agent_canvas_editing_repository import (
    AgentCanvasEditingExportRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_editing import (
    EditingExportAcceptedV2,
    EditingExportCancelResponseV2,
    EditingExportRequestV2,
    EditingExportRuntimeV2,
)
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_composition_renderer import (
    AgentCanvasCompositionRenderer,
)
from app.services.agent_canvas_editing import EditingInputResolver, EditingNodeService


Clock = Callable[[], datetime]


class EditingExportService:
    """Snapshot, render, and publish one explicit Editing export."""

    def __init__(
        self,
        *,
        data_dir: Path,
        workflows: AgentCanvasWorkflowRepository,
        nodes: EditingNodeService,
        inputs: EditingInputResolver,
        assets: AgentCanvasAssetService,
        exports: AgentCanvasEditingExportRepository,
        events: EventRepository,
        renderer: AgentCanvasCompositionRenderer,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._data_dir = data_dir
        self._workflows = workflows
        self._nodes = nodes
        self._inputs = inputs
        self._assets = assets
        self._exports = exports
        self._events = events
        self._renderer = renderer
        self._clock = clock

    def start(
        self,
        workflow_id: str,
        node_id: str,
        request: EditingExportRequestV2,
        *,
        idempotency_key: str,
    ) -> EditingExportAcceptedV2:
        content = self._nodes.content(workflow_id, node_id)
        manifest = content.manifest
        if request.expected_manifest_revision != manifest.manifest_revision:
            raise _error(
                "editing_manifest_revision_conflict",
                "Editing manifest revision does not match.",
            )
        if self._exports.find_active(workflow_id, node_id) is not None:
            raise _error(
                "editing_export_already_active",
                "An Editing export is already active for this node.",
            )
        resolved = self._inputs.resolve(workflow_id, node_id, manifest)
        fingerprint = _fingerprint(
            manifest.model_dump(mode="json"),
            resolved,
            _renderer_fingerprint_payload(self._renderer),
        )
        reusable = self._exports.find_completed(workflow_id, node_id, fingerprint)
        if reusable is not None and reusable.output_asset_id is not None:
            self._assets.resolve_asset_path(reusable.output_asset_id)
            return self._accepted(workflow_id, node_id, reusable)
        runtime = self._exports.create(
            workflow_id=workflow_id,
            node_id=node_id,
            manifest=manifest,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            ready_video_node_ids=tuple(item.node_id for item in resolved.videos),
            skipped_inputs=resolved.skipped,
            bgm_node_id=resolved.bgm.node_id if resolved.bgm else None,
            now=self._clock(),
        )
        updated_content = content.model_copy(update={"active_export": runtime})
        self._workflows.set_editing_runtime_state(
            workflow_id,
            node_id,
            status="working",
            structured_content=updated_content.model_dump(mode="json"),
            updated_at=self._clock(),
            event_type="editing_export_queued",
            export_id=runtime.export_id,
        )
        return self._accepted(workflow_id, node_id, runtime)

    def resume(self, export_id: str) -> None:
        workflow_id, node_id = self._exports.identity(export_id)
        runtime = self._exports.get(export_id)
        if runtime.status not in {"queued", "exporting"}:
            return
        if self._exports.is_cancel_requested(export_id):
            self._finish_cancelled(workflow_id, node_id, runtime)
            return
        now = self._clock()
        runtime = self._exports.update(export_id, status="exporting", now=now)
        content = self._nodes.content(workflow_id, node_id)
        self._workflows.set_editing_runtime_state(
            workflow_id,
            node_id,
            status="working",
            structured_content=content.model_copy(update={"active_export": runtime}).model_dump(
                mode="json"
            ),
            updated_at=now,
            event_type="editing_export_started",
            export_id=export_id,
        )
        try:
            manifest = self._exports.manifest(export_id)
            self._require_current_manifest(workflow_id, node_id, runtime)
            resolved = self._inputs.resolve(workflow_id, node_id, manifest)
            staging = (
                self._data_dir
                / "v2"
                / "runs"
                / workflow_id
                / "editing"
                / export_id
                / "final.mp4.part"
            )
            recover = getattr(self._renderer, "recover", None)
            if staging.is_file() and callable(recover):
                result = recover(
                    resolved,
                    manifest.output,
                    staging_path=staging,
                )
            else:
                result = self._renderer.render(
                    resolved,
                    manifest.output,
                    bgm_volume=manifest.bgm_volume,
                    staging_path=staging,
                    cancelled=lambda: self._exports.is_cancel_requested(export_id),
                )
            try:
                self._require_current_manifest(workflow_id, node_id, runtime)
            except V2PersistenceError:
                result.output_path.unlink(missing_ok=True)
                raise
            asset = self._assets.publish_generated_bytes(
                workflow_id,
                node_id=node_id,
                execution_id=export_id,
                filename="final.mp4",
                mime_type="video/mp4",
                content=result.output_path.read_bytes(),
                fingerprint=runtime.fingerprint,
                source_type="editing_export",
            )
            result.output_path.unlink(missing_ok=True)
            completed = self._exports.update(
                export_id,
                status="completed",
                output_asset_id=asset.asset_id,
                now=self._clock(),
            )
            current = self._nodes.content(workflow_id, node_id)
            final_content = current.model_copy(
                update={
                    "dirty": False,
                    "active_export": None,
                    "last_successful_export": completed,
                }
            )
            self._workflows.set_editing_runtime_state(
                workflow_id,
                node_id,
                status="ready",
                structured_content=final_content.model_dump(mode="json"),
                updated_at=self._clock(),
                event_type="editing_export_completed",
                export_id=export_id,
                output_asset_id=asset.asset_id,
            )
        except Exception as error:
            if getattr(error, "code", "") == "editing_export_cancelled":
                self._finish_cancelled(workflow_id, node_id, runtime)
                return
            self._finish_failed(workflow_id, node_id, runtime, error)

    def cancel(
        self,
        workflow_id: str,
        node_id: str,
        export_id: str,
    ) -> EditingExportCancelResponseV2:
        identity = self._exports.identity(export_id)
        if identity != (workflow_id, node_id):
            raise _error("editing_export_not_found", "Editing export was not found.")
        runtime = self._exports.request_cancel(export_id, now=self._clock())
        self._finish_cancelled(workflow_id, node_id, runtime)
        return EditingExportCancelResponseV2(
            workflow_id=workflow_id,
            node_id=node_id,
            export_id=export_id,
            status="cancelled",
            events_cursor=self._events.max_seq(workflow_id),
        )

    def resume_active(self) -> tuple[str, ...]:
        resumed: list[str] = []
        for runtime in self._exports.list_active():
            self.resume(runtime.export_id)
            resumed.append(runtime.export_id)
        return tuple(resumed)

    def _require_current_manifest(
        self,
        workflow_id: str,
        node_id: str,
        runtime: EditingExportRuntimeV2,
    ) -> None:
        current_revision = self._nodes.content(
            workflow_id,
            node_id,
        ).manifest.manifest_revision
        if current_revision != runtime.manifest_revision:
            raise _error(
                "editing_export_stale",
                "Editing manifest changed after this export was accepted.",
            )

    def _finish_cancelled(
        self,
        workflow_id: str,
        node_id: str,
        runtime: EditingExportRuntimeV2,
    ) -> None:
        cancelled = self._exports.update(
            runtime.export_id,
            status="cancelled",
            now=self._clock(),
        )
        content = self._nodes.content(workflow_id, node_id)
        status = "ready" if content.last_successful_export else "draft"
        self._workflows.set_editing_runtime_state(
            workflow_id,
            node_id,
            status=status,
            structured_content=content.model_copy(update={"active_export": None}).model_dump(
                mode="json"
            ),
            updated_at=self._clock(),
            event_type="editing_export_cancelled",
            export_id=cancelled.export_id,
        )

    def _finish_failed(
        self,
        workflow_id: str,
        node_id: str,
        runtime: EditingExportRuntimeV2,
        error: Exception,
    ) -> None:
        detail = CanvasNodeErrorV2(
            code=getattr(error, "code", "editing_export_failed"),
            message=str(error),
            retryable=False,
        )
        failed = self._exports.update(
            runtime.export_id,
            status="failed",
            error=detail,
            now=self._clock(),
        )
        content = self._nodes.content(workflow_id, node_id)
        has_success = content.last_successful_export is not None
        self._workflows.set_editing_runtime_state(
            workflow_id,
            node_id,
            status="ready" if has_success else "failed",
            structured_content=content.model_copy(update={"active_export": None}).model_dump(
                mode="json"
            ),
            updated_at=self._clock(),
            event_type="editing_export_failed",
            export_id=failed.export_id,
            error=None if has_success else detail,
        )

    def _accepted(
        self,
        workflow_id: str,
        node_id: str,
        runtime: EditingExportRuntimeV2,
    ) -> EditingExportAcceptedV2:
        return EditingExportAcceptedV2(
            workflow_id=workflow_id,
            node_id=node_id,
            export_id=runtime.export_id,
            status=runtime.status,
            manifest_revision=runtime.manifest_revision,
            ready_video_node_ids=runtime.ready_video_node_ids,
            skipped_inputs=runtime.skipped_inputs,
            bgm_node_id=runtime.bgm_node_id,
            events_cursor=self._events.max_seq(workflow_id),
        )


def _fingerprint(
    manifest: dict[str, object],
    resolved,
    renderer: dict[str, object],
) -> str:
    payload = {
        "contract": "agent-canvas-editing-v1",
        "manifest": manifest,
        "renderer": renderer,
        "videos": [
            {
                "binding_id": item.binding_id,
                "asset_id": item.asset.asset_id,
                "checksum": item.asset.checksum,
                "duration_seconds": item.asset.duration_seconds,
            }
            for item in resolved.videos
        ],
        "bgm": (
            {
                "binding_id": resolved.bgm.binding_id,
                "asset_id": resolved.bgm.asset.asset_id,
                "checksum": resolved.bgm.asset.checksum,
            }
            if resolved.bgm
            else None
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _renderer_fingerprint_payload(renderer: object) -> dict[str, object]:
    provider = getattr(renderer, "fingerprint_payload", None)
    if callable(provider):
        payload = provider()
        if isinstance(payload, dict):
            return payload
    return {
        "contract": "agent-canvas-composition-renderer-v1",
        "implementation": f"{type(renderer).__module__}.{type(renderer).__qualname__}",
    }


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_export")
