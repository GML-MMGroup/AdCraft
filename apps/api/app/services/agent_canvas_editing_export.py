"""Durable explicit Export lifecycle for Agent Canvas Editing nodes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from app.persistence.agent_canvas_editing_commit_repository import (
    AgentCanvasEditingExportCommitRepository,
)
from app.persistence.agent_canvas_editing_repository import (
    AgentCanvasEditingExportRepository,
)
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.schemas.agent_canvas import CanvasNodeErrorV2
from app.schemas.agent_canvas_editing import (
    EditingExportAcceptedV2,
    EditingExportCancelResponseV2,
    EditingExportRequestV2,
    EditingExportRuntimeV2,
)
from app.schemas.agent_canvas_editing_authority import (
    EditingExportCommitCommandV2,
    EditingExportStartCommandV2,
    EditingStagingMetadataV2,
    FencedLeaseTokenV2,
    RevisionAssertionV2,
)
from app.schemas.v2_persistence import V2EventInsert
from app.services.agent_canvas_assets import AgentCanvasAssetService
from app.services.agent_canvas_composition_renderer import (
    AgentCanvasCompositionRenderer,
)
from app.services.agent_canvas_editing import EditingInputResolver, EditingNodeService
from app.services.agent_canvas_editing_commit import AgentCanvasEditingExportCommitService


Clock = Callable[[], datetime]


class _EditingLeaseGuard:
    """Renew one Editing lease while a blocking operation is in flight."""

    def __init__(self, *, repository, lease, ttl: timedelta, clock: Clock) -> None:
        self._repository = repository
        self.lease = lease
        self._ttl = ttl
        self._clock = clock
        self._stop = Event()
        self._lock = Lock()
        self._error: BaseException | None = None

    def run(self, operation):
        thread = Thread(target=self._heartbeat, daemon=True)
        thread.start()
        try:
            result = operation()
        finally:
            self._stop.set()
            thread.join()
        if self._error is not None:
            raise self._error
        with self._lock:
            self._repository.assert_current_lease(self.lease, now=self._clock())
        return result

    def _heartbeat(self) -> None:
        interval = max(self._ttl.total_seconds() / 3, 0.01)
        while not self._stop.wait(interval):
            try:
                with self._lock:
                    self.lease = self._repository.renew_lease(
                        self.lease,
                        now=self._clock(),
                        ttl=self._ttl,
                    )
            except BaseException as error:
                self._error = error
                self._stop.set()
                return


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
        lease_ttl: timedelta = timedelta(seconds=60),
        worker_id_factory: Callable[[], str] = lambda: f"editing_worker_{uuid4().hex}",
        commit_service: AgentCanvasEditingExportCommitService | None = None,
        on_completed: Callable[[str, str, str], object] | None = None,
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
        self._lease_ttl = lease_ttl
        self._worker_id_factory = worker_id_factory
        self._on_completed = on_completed
        self._commits = commit_service or AgentCanvasEditingExportCommitService(
            AgentCanvasEditingExportCommitRepository(
                exports.database,
                V2AssetLibraryRepository(exports.database),
                events,
            )
        )

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
        resolved = self._inputs.resolve(workflow_id, node_id, manifest)
        renderer_payload = _renderer_fingerprint_payload(self._renderer)
        fingerprint = _fingerprint(manifest.model_dump(mode="json"), resolved, renderer_payload)
        reusable = self._exports.find_completed(workflow_id, node_id, fingerprint)
        reusable_export_id = None
        if reusable is not None and reusable.output_asset_id is not None:
            self._assets.resolve_asset_path(reusable.output_asset_id)
            reusable_export_id = reusable.export_id
        workflow = self._workflows.get_workflow(workflow_id)
        node = self._workflows.get_node(workflow_id, node_id)
        source_assets = tuple(
            dict.fromkeys(
                [item.asset.asset_id for item in resolved.videos]
                + ([resolved.bgm.asset.asset_id] if resolved.bgm is not None else [])
            )
        )
        source_assertions = tuple(
            RevisionAssertionV2(
                asset_id=asset_id,
                sha256=next(
                    item.asset.checksum
                    for item in (*resolved.videos, *((resolved.bgm,) if resolved.bgm else ()))
                    if item.asset.asset_id == asset_id
                ),
            )
            for asset_id in source_assets
        )
        now = self._clock()
        command = EditingExportStartCommandV2(
            workflow_id=workflow_id,
            expected_workflow_revision=workflow.revision,
            node_id=node_id,
            expected_node_revision=node.revision,
            manifest_revision=manifest.manifest_revision,
            manifest=manifest,
            renderer_digest=_sha256_json(renderer_payload),
            resolved_input_digest=_sha256_json(
                {
                    "videos": [
                        {"asset_id": item.asset.asset_id, "sha256": item.asset.checksum}
                        for item in resolved.videos
                    ],
                    "bgm": (
                        {
                            "asset_id": resolved.bgm.asset.asset_id,
                            "sha256": resolved.bgm.asset.checksum,
                        }
                        if resolved.bgm is not None
                        else None
                    ),
                    "skipped": [item.model_dump(mode="json") for item in resolved.skipped],
                }
            ),
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            request_digest=_sha256_json(request.model_dump(mode="json")),
            ready_video_node_ids=tuple(
                item.node_id for item in resolved.videos if item.node_id is not None
            ),
            source_asset_assertions=source_assertions,
            skipped_inputs=resolved.skipped,
            bgm_node_id=resolved.bgm.node_id if resolved.bgm else None,
            verified_reusable_export_id=reusable_export_id,
            created_at=now,
        )
        result = self._exports.start_or_reuse(command)
        return self._accepted(workflow_id, node_id, result.export)

    def resume(self, export_id: str) -> None:
        workflow_id, node_id = self._exports.identity(export_id)
        runtime = self._exports.get(export_id)
        if runtime.status == "completed":
            self._run_completed_effect(workflow_id, node_id, export_id)
            return
        if runtime.status not in {"queued", "exporting"}:
            return
        try:
            lease = self._exports.claim_lease(
                export_id,
                owner_id=self._worker_id_factory(),
                now=self._clock(),
                ttl=self._lease_ttl,
            )
        except V2PersistenceError as error:
            if error.code == "editing_export_lease_unavailable":
                return
            raise
        try:
            runtime = self._exports.get(export_id)
            if self._exports.is_cancel_requested(export_id):
                self._finish_cancelled(workflow_id, node_id, runtime, lease)
                return
            manifest = self._exports.manifest(export_id)
            self._require_current_manifest(workflow_id, node_id, runtime)
            resolved = self._inputs.resolve(workflow_id, node_id, manifest)
            staging, metadata_path = self._staging_paths(workflow_id, export_id)
            renderer_digest = _sha256_json(_renderer_fingerprint_payload(self._renderer))
            recover = getattr(self._renderer, "recover", None)
            reusable = self._validated_staging(
                staging,
                metadata_path,
                runtime=runtime,
                renderer_digest=renderer_digest,
                lease=lease,
            )
            if reusable and callable(recover):
                result, lease = self._with_heartbeat(
                    lease,
                    lambda: recover(resolved, manifest.output, staging_path=staging),
                )
            else:
                result, lease = self._with_heartbeat(
                    lease,
                    lambda: self._renderer.render(
                        resolved,
                        manifest.output,
                        staging_path=staging,
                        cancelled=lambda: self._exports.is_cancel_requested(export_id),
                    ),
                )
                if self._exports.is_cancel_requested(export_id):
                    self._finish_cancelled(workflow_id, node_id, runtime, lease)
                    return
                self._write_staging_metadata(
                    metadata_path,
                    staging,
                    runtime=runtime,
                    renderer_digest=renderer_digest,
                    lease=lease,
                )
            self._exports.append_progress(
                lease,
                now=self._clock(),
                stage="rendered",
                progress=0.75,
            )
            self._require_current_manifest(workflow_id, node_id, runtime)
            prepared, lease = self._with_heartbeat(
                lease,
                lambda: self._assets.prepare_generated_bytes(
                    workflow_id,
                    node_id=node_id,
                    execution_id=export_id,
                    filename="final.mp4",
                    mime_type="video/mp4",
                    content=result.output_path.read_bytes(),
                    fingerprint=runtime.fingerprint,
                    source_type="editing_export",
                ),
            )
            committed_at = self._clock()
            self._exports.assert_current_lease(lease, now=committed_at)
            self._commits.commit(
                EditingExportCommitCommandV2(
                    export_id=export_id,
                    workflow_id=workflow_id,
                    node_id=node_id,
                    logical_commit_key=f"editing-export:{export_id}",
                    payload_digest=_terminal_digest(
                        export_id,
                        "completed",
                        prepared.payload_digest,
                    ),
                    fingerprint=runtime.fingerprint,
                    lease=lease,
                    outcome="completed",
                    prepared_object=prepared.prepared_object,
                    asset_id=prepared.asset_id,
                    version_id=prepared.version_id,
                    asset_metadata=prepared.asset_metadata,
                    committed_at=committed_at,
                )
            )
            self._cleanup_staging(workflow_id, export_id)
            self._run_completed_effect(workflow_id, node_id, export_id)
        except Exception as error:
            if self._exports.is_cancel_requested(export_id):
                try:
                    self._finish_cancelled(workflow_id, node_id, runtime, lease)
                except V2PersistenceError as cancel_error:
                    if cancel_error.code not in {
                        "editing_export_already_terminal",
                        "stale_editing_export_lease",
                    }:
                        raise
                return
            if getattr(error, "code", "") in {
                "editing_export_cancelled",
                "editing_export_already_terminal",
                "stale_editing_export_lease",
            }:
                return
            self._finish_failed(workflow_id, node_id, runtime, lease, error)

    def _run_completed_effect(
        self,
        workflow_id: str,
        node_id: str,
        export_id: str,
    ) -> None:
        if self._on_completed is None:
            return
        try:
            self._on_completed(workflow_id, node_id, export_id)
        except Exception as error:  # noqa: BLE001 - Export remains terminal and recoverable.
            self._events.append(
                V2EventInsert(
                    workflow_id=workflow_id,
                    execution_id=export_id,
                    node_id=node_id,
                    event_type="guided_completion_failed",
                    transition_key=f"guided-completion:{export_id}:failed",
                    created_at=self._clock().isoformat(),
                    payload={
                        "export_id": export_id,
                        "error_code": getattr(
                            error,
                            "code",
                            "guided_completion_failed",
                        ),
                        "error_message": str(error),
                        "retryable": True,
                        "refresh": ["conversation", "runtime", "events"],
                    },
                )
            )

    def cancel(
        self,
        workflow_id: str,
        node_id: str,
        export_id: str,
    ) -> EditingExportCancelResponseV2:
        identity = self._exports.identity(export_id)
        if identity != (workflow_id, node_id):
            raise _error("editing_export_not_found", "Editing export was not found.")
        runtime = self._exports.get(export_id)
        self._exports.request_cancel(export_id, now=self._clock())
        try:
            lease = self._exports.claim_lease(
                export_id,
                owner_id=self._worker_id_factory(),
                now=self._clock(),
                ttl=self._lease_ttl,
            )
        except V2PersistenceError as error:
            if error.code != "editing_export_lease_unavailable":
                raise
            receipt = self._wait_for_cancel_terminal(export_id)
        else:
            receipt = self._finish_cancelled(workflow_id, node_id, runtime, lease)
        return EditingExportCancelResponseV2(
            workflow_id=workflow_id,
            node_id=node_id,
            export_id=export_id,
            status="cancelled",
            events_cursor=receipt.event_cursor,
        )

    def _wait_for_cancel_terminal(self, export_id: str):
        deadline = monotonic() + min(max(self._lease_ttl.total_seconds(), 1.0), 30.0)
        while monotonic() < deadline:
            runtime = self._exports.get(export_id)
            if runtime.status == "cancelled":
                return self._commits.receipt_for_export(export_id)
            if runtime.status in {"completed", "failed"}:
                raise _error(
                    "editing_export_already_terminal",
                    "Editing export is already terminal.",
                )
            Event().wait(0.01)
        raise _error(
            "editing_export_cancel_pending",
            "Editing export cancellation is still pending with its current worker.",
        )

    def resume_active(self) -> tuple[str, ...]:
        resumed: list[str] = []
        for runtime in self._exports.list_active():
            self.resume(runtime.export_id)
            resumed.append(runtime.export_id)
        if self._on_completed is not None:
            for runtime in self._exports.list_completed_all():
                workflow_id, node_id = self._exports.identity(runtime.export_id)
                self._run_completed_effect(workflow_id, node_id, runtime.export_id)
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
        lease: FencedLeaseTokenV2,
    ):
        now = self._clock()
        detail = CanvasNodeErrorV2(
            code="editing_export_cancelled",
            message="Editing export was cancelled.",
            retryable=False,
        )
        receipt = self._commits.commit(
            self._terminal_command(runtime, workflow_id, node_id, lease, "cancelled", detail, now)
        )
        self._cleanup_staging(workflow_id, runtime.export_id)
        return receipt

    def _finish_failed(
        self,
        workflow_id: str,
        node_id: str,
        runtime: EditingExportRuntimeV2,
        lease: FencedLeaseTokenV2,
        error: Exception,
    ) -> None:
        detail = CanvasNodeErrorV2(
            code=getattr(error, "code", "editing_export_failed"),
            message=str(error),
            retryable=False,
        )
        self._commits.commit(
            self._terminal_command(
                runtime,
                workflow_id,
                node_id,
                lease,
                "failed",
                detail,
                self._clock(),
            )
        )
        self._cleanup_staging(workflow_id, runtime.export_id)

    @staticmethod
    def _terminal_command(runtime, workflow_id, node_id, lease, outcome, error, now):
        return EditingExportCommitCommandV2(
            export_id=runtime.export_id,
            workflow_id=workflow_id,
            node_id=node_id,
            logical_commit_key=f"editing-export:{runtime.export_id}",
            payload_digest=_terminal_digest(runtime.export_id, outcome, error.code),
            fingerprint=runtime.fingerprint,
            lease=lease,
            outcome=outcome,
            error=error,
            committed_at=now,
        )

    def _with_heartbeat(self, lease, operation):
        guard = _EditingLeaseGuard(
            repository=self._exports,
            lease=lease,
            ttl=self._lease_ttl,
            clock=self._clock,
        )
        return guard.run(operation), guard.lease

    def _staging_paths(self, workflow_id: str, export_id: str) -> tuple[Path, Path]:
        work_dir = self._data_dir / "v2" / "runs" / workflow_id / "editing" / export_id
        return work_dir / "final.mp4.part", work_dir / "final.mp4.part.meta.json"

    def _validated_staging(
        self,
        staging: Path,
        metadata_path: Path,
        *,
        runtime: EditingExportRuntimeV2,
        renderer_digest: str,
        lease: FencedLeaseTokenV2,
    ) -> bool:
        self._exports.assert_current_lease(lease, now=self._clock())
        if not staging.is_file() or not metadata_path.is_file():
            self._remove_staging_files(staging, metadata_path)
            return False
        try:
            metadata = EditingStagingMetadataV2.model_validate_json(metadata_path.read_text())
            content = staging.read_bytes()
            valid = (
                metadata.export_id == runtime.export_id
                and metadata.fingerprint == runtime.fingerprint
                and metadata.manifest_revision == runtime.manifest_revision
                and metadata.renderer_digest == renderer_digest
                and metadata.writer_generation <= lease.generation
                and metadata.size_bytes == len(content)
                and metadata.sha256 == hashlib.sha256(content).hexdigest()
            )
        except (OSError, ValueError):
            valid = False
        if not valid:
            self._exports.assert_current_lease(lease, now=self._clock())
            self._remove_staging_files(staging, metadata_path)
            return False
        if metadata.writer_generation < lease.generation:
            self._write_staging_metadata(
                metadata_path,
                staging,
                runtime=runtime,
                renderer_digest=renderer_digest,
                lease=lease,
            )
        return True

    def _write_staging_metadata(
        self,
        metadata_path: Path,
        staging: Path,
        *,
        runtime: EditingExportRuntimeV2,
        renderer_digest: str,
        lease: FencedLeaseTokenV2,
    ) -> None:
        self._exports.assert_current_lease(lease, now=self._clock())
        content = staging.read_bytes()
        metadata = EditingStagingMetadataV2(
            export_id=runtime.export_id,
            fingerprint=runtime.fingerprint,
            manifest_revision=runtime.manifest_revision,
            renderer_digest=renderer_digest,
            writer_generation=lease.generation,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = metadata_path.with_name(f"{metadata_path.name}.{uuid4().hex}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(metadata.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(metadata_path)

    def _cleanup_staging(self, workflow_id: str, export_id: str) -> None:
        work_dir = self._data_dir / "v2" / "runs" / workflow_id / "editing" / export_id
        staging, metadata = self._staging_paths(workflow_id, export_id)
        self._remove_staging_files(staging, metadata)
        try:
            work_dir.rmdir()
        except OSError:
            pass

    @staticmethod
    def _remove_staging_files(staging: Path, metadata: Path) -> None:
        staging.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)

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
        "contract": "agent-canvas-editing-v2",
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
        "contract": "agent-canvas-composition-renderer-v2",
        "implementation": f"{type(renderer).__module__}.{type(renderer).__qualname__}",
    }


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _terminal_digest(export_id: str, outcome: str, detail: str) -> str:
    return _sha256_json({"export_id": export_id, "outcome": outcome, "detail": detail})


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_editing_export")
