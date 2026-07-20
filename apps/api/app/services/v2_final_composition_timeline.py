from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.workflow_v2 import (
    V2ProviderResult,
    WorkflowAssetVersionV2,
    WorkflowItemV2,
    WorkflowSlotV2,
    WorkflowV2,
    WorkflowV2RuntimeSnapshot,
    WorkflowV2Timeline,
    WorkflowV2TimelineClip,
    WorkflowV2TimelineClipCreateRequest,
    WorkflowV2TimelineClipDeleteRequest,
    WorkflowV2TimelineClipMutationResponse,
    V2RegisterLibraryReferenceRequest,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderResponse,
    WorkflowV2TimelineResponse,
    WorkflowV2TimelineSource,
    WorkflowV2TimelineSourceImportRequest,
    WorkflowV2TimelineSourceImportResponse,
    WorkflowV2TimelineTrack,
    WorkflowV2TimelineUpdateRequest,
    WorkflowV2TimelineUpdateResponse,
)
from app.services.agent_trace import utc_now
from app.services.media_paths import public_url_for_path
from app.services.v2_asset_store import V2AssetStoreService
from app.services.v2_data_boundary import validate_v2_data_path
from app.services.v2_final_composition_renderer import (
    MediaProbe,
    V2FinalCompositionRenderer,
    V2MediaProbe,
    V2MediaProbeResult,
)
from app.services.v2_runtime_events import V2RuntimeEventService
from app.services.v2_workflow_assets import V2WorkflowAssetError, V2WorkflowAssetService
from app.services.v2_workflow_store import V2WorkflowStore


FINAL_NODE_ID = "final-composition"
FINAL_SLOT_TYPE = "final_video"


class V2FinalCompositionTimelineError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class V2FinalCompositionTimelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        renderer_factory: Callable[[Path, Settings], V2FinalCompositionRenderer] | None = None,
        media_probe: MediaProbe | None = None,
    ) -> None:
        self._settings = settings
        self._data_dir = settings.media_data_dir
        self._workflow_store = V2WorkflowStore(self._data_dir)
        self._asset_store = V2AssetStoreService(self._data_dir)
        self._events = V2RuntimeEventService(self._data_dir)
        self._media_probe = media_probe or V2MediaProbe(ffprobe_path=settings.ffprobe_path)
        self._renderer_factory = renderer_factory or (
            lambda data_dir, renderer_settings: V2FinalCompositionRenderer(
                data_dir=data_dir,
                settings=renderer_settings,
            )
        )

    def get_timeline(self, workflow_id: str) -> WorkflowV2TimelineResponse:
        workflow, item, _slot, timeline, source = self.load_or_create_and_reconcile(workflow_id)
        return self._timeline_response(workflow, item, timeline, source=source)

    def load_or_create_and_reconcile(
        self,
        workflow_id: str,
    ) -> tuple[WorkflowV2, WorkflowItemV2, WorkflowSlotV2, WorkflowV2Timeline, str]:
        workflow = self._load_workflow(workflow_id)
        item, slot = self._final_item_and_slot(workflow)
        saved = self._load_timeline(workflow_id)
        source_hash = self._source_selection_hash(workflow)
        source = "saved"
        if saved is None:
            timeline = self._build_default_timeline(workflow)
            timeline.metadata["source_selection_hash"] = source_hash
            self._write_timeline(workflow_id, timeline)
            self._emit_timeline_created(
                workflow,
                timeline,
                changed_clip_ids=[clip.clip_id for clip in timeline.clips],
            )
            source = "default"
        elif self._system_default_needs_reconcile(saved, source_hash):
            rebuilt = self._build_default_timeline(workflow)
            preserved_metadata = {
                key: value
                for key, value in saved.metadata.items()
                if not key.startswith("resolution_")
            }
            resolution_metadata = {
                key: value
                for key, value in rebuilt.metadata.items()
                if key.startswith("resolution_")
            }
            timeline = rebuilt.model_copy(
                update={
                    "version": saved.version + 1,
                    "metadata": {
                        **preserved_metadata,
                        **resolution_metadata,
                        "edit_mode": "system_default",
                        "source_selection_hash": source_hash,
                        "updated_at": utc_now().isoformat(),
                        "updated_by": "system",
                    },
                },
                deep=True,
            )
            self._write_timeline(workflow_id, timeline)
            self._emit_timeline_updated(
                workflow,
                timeline,
                changed_clip_ids=[clip.clip_id for clip in timeline.clips],
            )
        else:
            timeline = saved
        if self._project_compatibility_timeline(item, timeline):
            self._workflow_store.save_workflow(workflow)
        return workflow, item, slot, timeline, source

    def project_compatibility_timeline(
        self,
        item: WorkflowItemV2,
        timeline: WorkflowV2Timeline,
    ) -> bool:
        return self._project_compatibility_timeline(item, timeline)

    def save_timeline(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineUpdateRequest,
    ) -> WorkflowV2TimelineUpdateResponse:
        workflow, item, _slot, current, _source = self.load_or_create_and_reconcile(workflow_id)
        expected_version = request.expected_version or current.version
        if expected_version != current.version:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_version_conflict",
                "Timeline version does not match expected_version.",
                status_code=409,
            )
        incoming = request.timeline.model_copy(deep=True)
        self._validate_timeline(workflow_id, incoming)
        changed_clip_ids = _changed_clip_ids(current, incoming)
        updated = incoming.model_copy(
            update={
                "version": current.version + 1,
                "metadata": {
                    **incoming.metadata,
                    "edit_mode": "user_edited",
                    "source_selection_hash": self._source_selection_hash(workflow),
                    "updated_at": utc_now().isoformat(),
                    "updated_by": "user",
                },
            },
            deep=True,
        )
        self._write_timeline(workflow_id, updated)
        self._project_compatibility_timeline(item, updated)
        self._workflow_store.save_workflow(workflow)
        self._emit_timeline_updated(workflow, updated, changed_clip_ids=changed_clip_ids)
        return WorkflowV2TimelineUpdateResponse(
            workflow_id=workflow_id,
            timeline=updated,
            changed_clip_ids=changed_clip_ids,
            runtime=self._runtime_snapshot(workflow).model_dump(mode="json"),
        )

    def render_timeline(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineRenderRequest,
        *,
        render_id: str | None = None,
        emit_lifecycle_events: bool = True,
    ) -> WorkflowV2TimelineRenderResponse:
        workflow, item, slot, timeline, _source = self.load_or_create_and_reconcile(workflow_id)
        if (
            request.timeline_id != timeline.timeline_id
            or request.timeline_version != timeline.version
        ):
            raise V2FinalCompositionTimelineError(
                "v2_timeline_version_conflict",
                "Render request does not match the saved timeline version.",
                status_code=409,
            )
        self._validate_timeline(workflow_id, timeline)
        resolved_render_id = render_id or f"render_{uuid4().hex[:12]}"
        provider_payload = self._provider_payload(
            timeline,
            request.render_settings.model_dump(mode="json"),
        )
        provider_payload["render_id"] = resolved_render_id
        if emit_lifecycle_events:
            self._events.append_event(
                workflow_id,
                "final_composition_render_started",
                node_id=FINAL_NODE_ID,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload={
                    "workflow_id": workflow_id,
                    "render_id": resolved_render_id,
                    "timeline_id": timeline.timeline_id,
                    "timeline_version": timeline.version,
                },
            )
        renderer = self._renderer_factory(self._data_dir, self._settings)
        result = renderer.render(workflow, item, slot, provider_payload)
        if result.status != "completed" or not result.local_file_path:
            if emit_lifecycle_events:
                self._emit_render_failed(workflow, item, slot, timeline, resolved_render_id, result)
            raise V2FinalCompositionTimelineError(
                "v2_timeline_render_failed",
                result.error_message or "Timeline render failed.",
                status_code=400,
            )
        result = self._move_result_to_render_path(workflow.workflow_id, resolved_render_id, result)
        output_path = self._data_dir / result.local_file_path
        if not output_path.exists():
            if emit_lifecycle_events:
                self._emit_render_failed(workflow, item, slot, timeline, resolved_render_id, result)
            raise V2FinalCompositionTimelineError(
                "v2_timeline_render_failed",
                "Timeline render did not create an output file.",
                status_code=400,
            )
        record = self._register_final_asset_version(
            workflow,
            item,
            slot,
            timeline,
            resolved_render_id,
            provider_payload,
            result,
        )
        self._workflow_store.save_workflow(workflow)
        self._emit_render_completed(workflow, item, slot, timeline, resolved_render_id, record)
        return WorkflowV2TimelineRenderResponse(
            workflow_id=workflow_id,
            render_id=resolved_render_id,
            slot_id=slot.slot_id,
            asset_id=record.asset_id,
            version_id=record.version_id,
            status="completed",
            public_url=record.public_url,
            timeline_id=timeline.timeline_id,
            timeline_version=timeline.version,
            runtime=self._runtime_snapshot(workflow).model_dump(mode="json"),
            metadata=record.metadata,
        )

    def _move_result_to_render_path(
        self,
        workflow_id: str,
        render_id: str,
        result: V2ProviderResult,
    ) -> V2ProviderResult:
        if not result.local_file_path:
            return result
        target_relative = (
            Path("v2") / "runs" / workflow_id / "composition" / render_id / "final-ad-video.mp4"
        )
        if result.local_file_path == target_relative.as_posix():
            return result
        source_path = self._data_dir / result.local_file_path
        target_path = self._data_dir / target_relative
        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source_path, target_path)
        return result.model_copy(update={"local_file_path": target_relative.as_posix()}, deep=True)

    def create_compatibility_clip(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineClipCreateRequest,
    ) -> WorkflowV2TimelineClipMutationResponse:
        workflow, item, _slot, current, _source = self.load_or_create_and_reconcile(workflow_id)
        expected_version = request.expected_version or current.version
        if expected_version != current.version:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_version_conflict",
                "Timeline version does not match expected_version.",
                status_code=409,
            )
        track = next(
            (
                candidate
                for candidate in current.tracks
                if candidate.track_type == request.clip_type
                and (request.track_index <= 0 or candidate.order == request.track_index)
            ),
            None,
        )
        if track is None:
            requested_order = request.track_index if request.track_index > 0 else None
            used_orders = {candidate.order for candidate in current.tracks}
            track_order = (
                requested_order
                if requested_order is not None and requested_order not in used_orders
                else max(used_orders, default=0) + 1
            )
            track = WorkflowV2TimelineTrack(
                track_id=f"{request.clip_type}-{len(current.tracks) + 1}",
                track_type=request.clip_type,
                order=track_order,
            )
        source_record = (
            self._asset_store.load_asset_version(
                request.source_asset_id,
                request.source_version_id,
            )
            if request.source_version_id
            else self._asset_store.find_asset_version(asset_id=request.source_asset_id)
        )
        if source_record is None:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_source_asset_missing",
                f"Timeline source asset is missing: {request.source_asset_id}",
                status_code=404,
            )
        if source_record.workflow_id not in {workflow_id, None}:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_source_not_authorized",
                "Timeline source is not authorized for this workflow.",
                status_code=422,
            )
        relation = self._asset_store.create_relation(
            relation_type="selected_for_timeline",
            source_asset_id=request.source_asset_id,
            target_workflow_id=workflow_id,
            target_node_id=FINAL_NODE_ID,
            target_item_id=item.item_id,
            metadata={"version_id": source_record.version_id},
        )
        clip = WorkflowV2TimelineClip(
            clip_id=f"clip_{uuid4().hex[:12]}",
            track_id=track.track_id,
            clip_type=request.clip_type,
            source_asset_id=request.source_asset_id,
            source_version_id=source_record.version_id,
            start_time=request.start_time,
            duration=request.duration,
            trim_in=request.trim_in,
            trim_out=request.trim_out,
            volume=request.volume,
            metadata={**request.metadata, "relation_id": relation.relation_id},
        )
        tracks = list(current.tracks)
        if all(candidate.track_id != track.track_id for candidate in tracks):
            tracks.append(track)
        candidate = current.model_copy(
            update={
                "tracks": tracks,
                "clips": [*current.clips, clip],
                "duration_seconds": max(
                    current.duration_seconds,
                    clip.start_time + clip.duration,
                ),
                "metadata": {
                    **current.metadata,
                    "edit_mode": "user_edited",
                    "source_selection_hash": self._source_selection_hash(workflow),
                    "updated_at": utc_now().isoformat(),
                    "updated_by": "user",
                },
            },
            deep=True,
        )
        self._validate_timeline(workflow_id, candidate)
        self._write_timeline(
            workflow_id,
            candidate.model_copy(update={"version": current.version + 1}, deep=True),
        )
        updated = candidate.model_copy(update={"version": current.version + 1}, deep=True)
        self._project_compatibility_timeline(item, updated)
        self._workflow_store.save_workflow(workflow)
        self._emit_timeline_updated(workflow, updated, changed_clip_ids=[clip.clip_id])
        compatibility_clip = clip.model_dump(mode="json")
        compatibility_clip["relation_id"] = relation.relation_id
        return WorkflowV2TimelineClipMutationResponse(
            workflow=workflow,
            clip=compatibility_clip,
        )

    def delete_compatibility_clip(
        self,
        workflow_id: str,
        clip_id: str,
        request: WorkflowV2TimelineClipDeleteRequest,
    ) -> WorkflowV2TimelineClipMutationResponse:
        workflow, item, _slot, current, _source = self.load_or_create_and_reconcile(workflow_id)
        expected_version = request.expected_version or current.version
        if expected_version != current.version:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_version_conflict",
                "Timeline version does not match expected_version.",
                status_code=409,
            )
        removed = next((clip for clip in current.clips if clip.clip_id == clip_id), None)
        retained = [clip for clip in current.clips if clip.clip_id != clip_id]
        if len(retained) == len(current.clips):
            raise V2FinalCompositionTimelineError(
                "v2_timeline_invalid_clip",
                f"Timeline clip not found: {clip_id}",
                status_code=404,
            )
        updated = current.model_copy(
            update={
                "version": current.version + 1,
                "clips": retained,
                "duration_seconds": max(
                    (clip.start_time + clip.duration for clip in retained if clip.enabled),
                    default=0,
                ),
                "metadata": {
                    **current.metadata,
                    "edit_mode": "user_edited",
                    "updated_at": utc_now().isoformat(),
                    "updated_by": "user",
                },
            },
            deep=True,
        )
        self._validate_timeline(workflow_id, updated)
        self._write_timeline(workflow_id, updated)
        self._project_compatibility_timeline(item, updated)
        self._workflow_store.save_workflow(workflow)
        relation_id = removed.metadata.get("relation_id") if removed is not None else None
        if isinstance(relation_id, str) and relation_id:
            self._asset_store.delete_relation(relation_id)
        self._emit_timeline_updated(workflow, updated, changed_clip_ids=[clip_id])
        return WorkflowV2TimelineClipMutationResponse(
            workflow=workflow,
            removed_clip_id=clip_id,
        )

    def import_library_source(
        self,
        workflow_id: str,
        request: WorkflowV2TimelineSourceImportRequest,
    ) -> WorkflowV2TimelineSourceImportResponse:
        workflow = self._load_workflow(workflow_id)
        item, _slot = self._final_item_and_slot(workflow)
        asset_service = V2WorkflowAssetService(self._data_dir, settings=self._settings)
        library_request = V2RegisterLibraryReferenceRequest(
            library_entity_id=request.library_entity_id,
            library_asset_id=request.library_asset_id,
            target=None,
            use_as_prompt=False,
        )

        try:
            _entity, _library_asset, media_type = asset_service.resolve_library_reference(
                library_request
            )
        except V2WorkflowAssetError as exc:
            status_code = (
                422 if exc.code in {"asset_slot_incompatible", "asset_not_authorized"} else 404
            )
            raise V2FinalCompositionTimelineError(
                exc.code, str(exc), status_code=status_code
            ) from exc
        if media_type != request.expected_media_type:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_unsupported_source_media",
                "Library source media type does not match request.",
                status_code=400,
            )
        try:
            mutation = asset_service.register_library_reference(workflow_id, library_request)
        except V2WorkflowAssetError as exc:
            status_code = (
                422 if exc.code in {"asset_slot_incompatible", "asset_not_authorized"} else 404
            )
            raise V2FinalCompositionTimelineError(
                exc.code, str(exc), status_code=status_code
            ) from exc
        if not mutation.assets:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_source_asset_missing",
                "Library import did not produce a V2 asset version.",
                status_code=404,
            )
        view = mutation.assets[0]
        record = self._asset_store.load_asset_version(view.asset_id, view.version_id)
        if record is None:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_source_version_missing",
                "Library import did not persist the requested V2 asset version.",
                status_code=404,
            )
        if record.media_type != request.expected_media_type:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_unsupported_source_media",
                "Imported source media type does not match request.",
                status_code=400,
            )
        self._asset_store.create_relation(
            relation_type="selected_for_timeline",
            source_asset_id=record.asset_id,
            target_workflow_id=workflow_id,
            target_node_id=FINAL_NODE_ID,
            target_item_id=item.item_id,
            metadata={
                "version_id": record.version_id,
                "library_entity_id": request.library_entity_id,
                "library_asset_id": request.library_asset_id,
            },
        )
        return WorkflowV2TimelineSourceImportResponse(
            workflow_id=workflow_id,
            source=self._timeline_source(record, origin="asset_library", slot_id=None),
        )

    def _load_workflow(self, workflow_id: str) -> WorkflowV2:
        try:
            return self._workflow_store.load_workflow(workflow_id)
        except FileNotFoundError as exc:
            raise V2FinalCompositionTimelineError(
                "workflow_not_found",
                f"Workflow not found: {workflow_id}",
                status_code=404,
            ) from exc

    def _final_item_and_slot(self, workflow: WorkflowV2) -> tuple[WorkflowItemV2, WorkflowSlotV2]:
        for node in workflow.nodes:
            if node.node_id != FINAL_NODE_ID:
                continue
            for item in node.items:
                for slot in item.slots:
                    if slot.slot_type == FINAL_SLOT_TYPE:
                        return item, slot
        raise V2FinalCompositionTimelineError(
            "v2_final_composition_not_ready",
            "Final composition slot is not ready for timeline editing.",
            status_code=404,
        )

    def _build_default_timeline(self, workflow: WorkflowV2) -> WorkflowV2Timeline:
        clips: list[WorkflowV2TimelineClip] = []
        cursor = 0.0
        shot_records = self._selected_shot_video_records(workflow)
        for item, slot, record in shot_records:
            duration = _duration_for_shot(item, record)
            clips.append(
                WorkflowV2TimelineClip(
                    clip_id=f"clip_{_slug(slot.slot_id)}",
                    track_id="video-1",
                    clip_type="video",
                    source_asset_id=record.asset_id,
                    source_version_id=record.version_id,
                    source_slot_id=slot.slot_id,
                    start_time=cursor,
                    duration=duration,
                    trim_in=0,
                    trim_out=duration,
                    volume=1,
                    muted=False,
                    metadata={
                        "shot_id": item.shot_id or item.item_id,
                        "shot_index": item.shot_index,
                    },
                )
            )
            cursor += duration
        duration_seconds = cursor
        tracks = (
            [WorkflowV2TimelineTrack(track_id="video-1", track_type="video", order=1)]
            if clips
            else []
        )
        bgm = self._selected_bgm_record(workflow)
        if bgm is not None:
            if duration_seconds <= 0:
                duration_seconds = _duration_from_record(bgm, default=1.0)
            tracks.append(WorkflowV2TimelineTrack(track_id="audio-1", track_type="audio", order=2))
            clips.append(
                WorkflowV2TimelineClip(
                    clip_id=f"clip_{_slug(bgm.asset_id)}",
                    track_id="audio-1",
                    clip_type="audio",
                    source_asset_id=bgm.asset_id,
                    source_version_id=bgm.version_id,
                    source_slot_id=bgm.slot_id,
                    start_time=0,
                    duration=duration_seconds,
                    trim_in=0,
                    trim_out=duration_seconds,
                    volume=1,
                    muted=False,
                    metadata={"role": "bgm"},
                )
            )
        resolution, resolution_metadata = self._default_timeline_resolution(shot_records)
        return WorkflowV2Timeline(
            timeline_id=f"v2tl_{workflow.workflow_id}",
            version=1,
            duration_seconds=duration_seconds,
            aspect_ratio=workflow.aspect_ratio,
            resolution=resolution,
            tracks=tracks,
            clips=clips,
            metadata={
                "created_at": utc_now().isoformat(),
                "created_by": "system",
                "source": "default_builder",
                "edit_mode": "system_default",
                **resolution_metadata,
            },
        )

    def _system_default_needs_reconcile(
        self,
        timeline: WorkflowV2Timeline,
        source_selection_hash: str,
    ) -> bool:
        if timeline.metadata.get("edit_mode", "system_default") == "user_edited":
            return False
        return (
            timeline.metadata.get("source_selection_hash") != source_selection_hash
            or "resolution_source" not in timeline.metadata
        )

    def _default_timeline_resolution(
        self,
        shot_records: list[tuple[WorkflowItemV2, WorkflowSlotV2, WorkflowAssetVersionV2]],
    ) -> tuple[dict[str, int], dict[str, Any]]:
        fallback = {"width": 1280, "height": 720}
        if not shot_records:
            return fallback, {"resolution_source": "default_fallback"}

        _item, _slot, record = shot_records[0]
        source_metadata = {
            "resolution_source_asset_id": record.asset_id,
            "resolution_source_version_id": record.version_id,
        }
        try:
            source_path = validate_v2_data_path(
                self._data_dir,
                self._data_dir / record.file_path,
                operation="v2-final-composition-resolution-probe",
            )
            probe = V2MediaProbeResult.from_payload(
                self._media_probe(source_path, "video"),
                path=source_path,
                media_type="video",
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            return fallback, {
                "resolution_source": "default_fallback",
                **source_metadata,
            }

        if probe.error or not probe.width or not probe.height:
            return fallback, {
                "resolution_source": "default_fallback",
                **source_metadata,
            }
        return (
            {"width": probe.width, "height": probe.height},
            {
                "resolution_source": "first_source_shot",
                **source_metadata,
            },
        )

    def _selected_shot_video_records(
        self,
        workflow: WorkflowV2,
    ) -> list[tuple[WorkflowItemV2, WorkflowSlotV2, WorkflowAssetVersionV2]]:
        records: list[tuple[WorkflowItemV2, WorkflowSlotV2, WorkflowAssetVersionV2]] = []
        for node in workflow.nodes:
            if node.node_id != "storyboard":
                continue
            for item in node.items:
                if item.item_type != "shot":
                    continue
                slot = next(
                    (slot for slot in item.slots if slot.slot_type == "shot_video_segment"),
                    None,
                )
                record = self._selected_record(slot, workflow.workflow_id) if slot else None
                if slot is not None and record is not None:
                    records.append((item, slot, record))
        return sorted(records, key=lambda row: (row[0].shot_index or 0, row[0].item_id))

    def _selected_bgm_record(self, workflow: WorkflowV2) -> WorkflowAssetVersionV2 | None:
        for node in workflow.nodes:
            if node.node_id != "bgm":
                continue
            for item in node.items:
                for slot in item.slots:
                    if slot.slot_type == "bgm_audio":
                        return self._selected_record(slot, workflow.workflow_id)
        return None

    def _selected_record(
        self,
        slot: WorkflowSlotV2 | None,
        workflow_id: str,
    ) -> WorkflowAssetVersionV2 | None:
        if slot is None or not slot.selected_asset_id:
            return None
        version_id = slot.selected_version_id
        record = (
            self._asset_store.load_asset_version(slot.selected_asset_id, version_id)
            if version_id
            else self._asset_store.find_asset_version(asset_id=slot.selected_asset_id)
        )
        if record is None or record.workflow_id not in {workflow_id, None}:
            return None
        return record

    def _validate_timeline(self, workflow_id: str, timeline: WorkflowV2Timeline) -> None:
        try:
            validated = WorkflowV2Timeline.model_validate(timeline.model_dump(mode="json"))
        except ValidationError as exc:
            message = str(exc)
            code = (
                "v2_timeline_track_overlap"
                if "cannot overlap" in message
                else "v2_timeline_invalid_clip"
            )
            raise V2FinalCompositionTimelineError(code, message, status_code=400) from exc
        for clip in validated.clips:
            if clip.clip_type in {"video", "audio", "image"}:
                self._validate_clip_source(workflow_id, clip)

    def _validate_clip_source(self, workflow_id: str, clip: WorkflowV2TimelineClip) -> None:
        asset_id = clip.source_asset_id or ""
        version_id = clip.source_version_id or ""
        record = self._asset_store.load_asset_version(asset_id, version_id)
        if record is not None and record.workflow_id in {workflow_id, None}:
            if record.media_type != clip.clip_type:
                raise V2FinalCompositionTimelineError(
                    "v2_timeline_unsupported_source_media",
                    "Timeline source media type does not match clip type.",
                    status_code=400,
                )
            return
        any_version = self._asset_store.find_asset_version(asset_id=asset_id)
        if any_version is None or any_version.workflow_id not in {workflow_id, None}:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_source_asset_missing",
                f"Timeline source asset is missing: {asset_id}",
                status_code=404,
            )
        raise V2FinalCompositionTimelineError(
            "v2_timeline_source_version_missing",
            f"Timeline source version is missing: {version_id}",
            status_code=404,
        )

    def _provider_payload(
        self,
        timeline: WorkflowV2Timeline,
        render_settings: dict[str, Any],
    ) -> dict[str, Any]:
        track_order = {track.track_id: track.order for track in timeline.tracks}
        timeline_clips: list[dict[str, Any]] = []
        for index, clip in enumerate(
            sorted(timeline.clips, key=lambda item: (track_order[item.track_id], item.start_time)),
            start=1,
        ):
            payload = clip.model_dump(mode="json")
            payload["track_index"] = track_order.get(clip.track_id, 0)
            payload["order"] = index
            payload["trim_start"] = clip.trim_in
            payload["trim_end"] = clip.trim_out
            timeline_clips.append(payload)
        bgm_asset_id = next(
            (
                clip.source_asset_id
                for clip in timeline.clips
                if clip.clip_type == "audio" and not clip.muted and clip.source_asset_id
            ),
            None,
        )
        source_asset_ids = [
            str(clip.source_asset_id) for clip in timeline.clips if clip.source_asset_id
        ]
        source_version_ids = [
            str(clip.source_version_id) for clip in timeline.clips if clip.source_version_id
        ]
        return {
            "composition_tool": "local_composition_ffmpeg",
            "canonical_timeline": timeline.model_dump(mode="json"),
            "timeline_clips": timeline_clips,
            "timeline_plan": {
                "timeline_id": timeline.timeline_id,
                "version": timeline.version,
                "duration_seconds": timeline.duration_seconds,
                "aspect_ratio": timeline.aspect_ratio,
                "resolution": timeline.resolution,
                "fps": timeline.fps,
                "render_settings": dict(render_settings),
                "source_asset_ids": source_asset_ids,
                "source_version_ids": source_version_ids,
            },
            "bgm_asset_id": bgm_asset_id,
        }

    def _register_final_asset_version(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        timeline: WorkflowV2Timeline,
        render_id: str,
        provider_payload: dict[str, Any],
        result: V2ProviderResult,
    ) -> WorkflowAssetVersionV2:
        previous_asset_id = slot.selected_asset_id
        previous_version_id = slot.selected_version_id
        asset_id = previous_asset_id or "asset_final_composition_1_final_video"
        version_id = f"ver_{render_id}"
        source_clip_ids = [clip.clip_id for clip in timeline.clips if clip.clip_type == "video"]
        source_asset_ids = [
            str(clip.source_asset_id) for clip in timeline.clips if clip.source_asset_id
        ]
        source_version_ids = [
            str(clip.source_version_id) for clip in timeline.clips if clip.source_version_id
        ]
        metadata = {
            **result.metadata,
            "timeline_id": timeline.timeline_id,
            "timeline_version": timeline.version,
            "render_id": render_id,
            "source_clip_ids": source_clip_ids,
            "source_asset_ids": source_asset_ids,
            "source_version_ids": source_version_ids,
            "duration_seconds": timeline.duration_seconds,
            "resolution": timeline.resolution,
            "fps": timeline.fps,
            "audio_mix_strategy": result.metadata.get("audio_mix_strategy"),
            "render_output_path": result.local_file_path,
            "renderer_render_mode": result.metadata.get("render_mode"),
            "render_mode": "timeline_render",
        }
        record = self._asset_store.save_asset_version(
            WorkflowAssetVersionV2(
                asset_id=asset_id,
                version_id=version_id,
                media_type="video",
                source_type="derived",
                file_path=str(result.local_file_path),
                public_url=public_url_for_path(result.local_file_path),
                workflow_id=workflow.workflow_id,
                node_id=FINAL_NODE_ID,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                semantic_type=FINAL_SLOT_TYPE,
                provider_payload_snapshot=provider_payload,
                reference_asset_ids=result.reference_asset_ids,
                created_at=utc_now().isoformat(),
                created_by="v2-final-composition-timeline",
                metadata=metadata,
            )
        )
        if previous_asset_id and previous_version_id:
            slot.history_version_ids = list(
                dict.fromkeys([*slot.history_version_ids, previous_version_id])
            )
            self._asset_store.create_relation(
                relation_type="history_version_for_slot",
                source_asset_id=previous_asset_id,
                target_workflow_id=workflow.workflow_id,
                target_node_id=slot.node_id,
                target_item_id=slot.item_id,
                target_slot_id=slot.slot_id,
                metadata={"version_id": previous_version_id, "source_action": "timeline_render"},
            )
        self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="working_version_for_slot",
        )
        self._asset_store.delete_slot_relations(
            target_workflow_id=workflow.workflow_id,
            target_slot_id=slot.slot_id,
            relation_type="selected_for_slot",
        )
        self._asset_store.create_relation(
            relation_type="working_version_for_slot",
            source_asset_id=record.asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata={"version_id": record.version_id, "source_action": "timeline_render"},
        )
        self._asset_store.create_relation(
            relation_type="selected_for_slot",
            source_asset_id=record.asset_id,
            target_workflow_id=workflow.workflow_id,
            target_node_id=slot.node_id,
            target_item_id=slot.item_id,
            target_slot_id=slot.slot_id,
            metadata={"version_id": record.version_id, "source_action": "timeline_render"},
        )
        slot.current_working_asset_id = record.asset_id
        slot.current_working_version_id = record.version_id
        slot.selected_asset_id = record.asset_id
        slot.selected_version_id = record.version_id
        slot.status = "completed"
        return record

    def _emit_timeline_updated(
        self,
        workflow: WorkflowV2,
        timeline: WorkflowV2Timeline,
        *,
        changed_clip_ids: list[str],
    ) -> None:
        self._events.append_event(
            workflow.workflow_id,
            "final_timeline_updated",
            node_id=FINAL_NODE_ID,
            payload={
                "timeline_id": timeline.timeline_id,
                "timeline_version": timeline.version,
                "changed_clip_ids": changed_clip_ids,
            },
        )
        self._events.append_event(
            workflow.workflow_id,
            "runtime_snapshot_updated",
            node_id=FINAL_NODE_ID,
            payload={"timeline_id": timeline.timeline_id, "timeline_version": timeline.version},
        )

    def _emit_timeline_created(
        self,
        workflow: WorkflowV2,
        timeline: WorkflowV2Timeline,
        *,
        changed_clip_ids: list[str],
    ) -> None:
        self._events.append_event(
            workflow.workflow_id,
            "final_timeline_created",
            node_id=FINAL_NODE_ID,
            payload={"timeline_id": timeline.timeline_id, "timeline_version": timeline.version},
        )
        self._emit_timeline_updated(
            workflow,
            timeline,
            changed_clip_ids=changed_clip_ids,
        )

    def _emit_render_completed(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        timeline: WorkflowV2Timeline,
        render_id: str,
        record: WorkflowAssetVersionV2,
    ) -> None:
        event_payload = {
            "workflow_id": workflow.workflow_id,
            "render_id": render_id,
            "timeline_id": timeline.timeline_id,
            "timeline_version": timeline.version,
            "semantic_type": FINAL_SLOT_TYPE,
        }
        for event_type in (
            "asset_version_created",
            "slot_working_version_updated",
            "slot_selected_version_updated",
            "final_composition_render_completed",
        ):
            self._events.append_event(
                workflow.workflow_id,
                event_type,
                node_id=FINAL_NODE_ID,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                asset_id=record.asset_id,
                version_id=record.version_id,
                payload=event_payload,
            )
        self._events.append_event(
            workflow.workflow_id,
            "runtime_snapshot_updated",
            node_id=FINAL_NODE_ID,
            item_id=item.item_id,
            slot_id=slot.slot_id,
            asset_id=record.asset_id,
            version_id=record.version_id,
            payload={"status": slot.status},
        )

    def _emit_render_failed(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        slot: WorkflowSlotV2,
        timeline: WorkflowV2Timeline,
        render_id: str,
        result: V2ProviderResult,
    ) -> None:
        payload = {
            "workflow_id": workflow.workflow_id,
            "render_id": render_id,
            "timeline_id": timeline.timeline_id,
            "timeline_version": timeline.version,
            "error_code": result.error_code or "v2_timeline_render_failed",
            "error_message": result.error_message,
        }
        for event_type in ("final_composition_render_failed", "slot_generation_failed"):
            self._events.append_event(
                workflow.workflow_id,
                event_type,
                node_id=FINAL_NODE_ID,
                item_id=item.item_id,
                slot_id=slot.slot_id,
                payload=payload,
            )

    def _timeline_response(
        self,
        workflow: WorkflowV2,
        item: WorkflowItemV2,
        timeline: WorkflowV2Timeline,
        *,
        source: str,
    ) -> WorkflowV2TimelineResponse:
        return WorkflowV2TimelineResponse(
            workflow_id=workflow.workflow_id,
            item_id=item.item_id,
            timeline=timeline,
            source=source,  # type: ignore[arg-type]
            runtime=self._runtime_snapshot(workflow).model_dump(mode="json"),
            available_sources=self._available_sources(workflow),
            stale_clip_ids=self._stale_clip_ids(workflow, timeline),
            missing_source_clip_ids=self._missing_source_clip_ids(workflow.workflow_id, timeline),
        )

    def _runtime_snapshot(self, workflow: WorkflowV2) -> WorkflowV2RuntimeSnapshot:
        return self._events.runtime_snapshot(workflow)

    def _load_timeline(self, workflow_id: str) -> WorkflowV2Timeline | None:
        path = self._timeline_path(workflow_id)
        if not path.exists():
            return None
        try:
            return WorkflowV2Timeline.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as exc:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_invalid_clip",
                f"Stored timeline is invalid: {exc}",
                status_code=400,
            ) from exc

    def _write_timeline(self, workflow_id: str, timeline: WorkflowV2Timeline) -> None:
        path = self._timeline_path(workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f".tmp-{uuid4().hex}")
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, indent=2)
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    def _project_compatibility_timeline(
        self,
        item: WorkflowItemV2,
        timeline: WorkflowV2Timeline,
    ) -> bool:
        track_order = {track.track_id: track.order for track in timeline.tracks}
        projected_clips: list[dict[str, Any]] = []
        for index, clip in enumerate(
            sorted(
                timeline.clips,
                key=lambda candidate: (
                    track_order.get(candidate.track_id, 0),
                    candidate.start_time,
                    candidate.clip_id,
                ),
            ),
            start=1,
        ):
            projected_clip = clip.model_dump(mode="json")
            projected_clip["track_index"] = track_order.get(clip.track_id, 0)
            projected_clip["order"] = index
            projected_clip["trim_start"] = clip.trim_in
            projected_clip["trim_end"] = clip.trim_out
            projected_clips.append(projected_clip)
        projected_plan = {
            "timeline_id": timeline.timeline_id,
            "version": timeline.version,
            "canonical_timeline_id": timeline.timeline_id,
            "canonical_timeline_version": timeline.version,
            "duration_seconds": timeline.duration_seconds,
            "aspect_ratio": timeline.aspect_ratio,
            "resolution": dict(timeline.resolution),
            "fps": timeline.fps,
            "render_settings": {"provider": "local_composition_ffmpeg"},
            "source_asset_ids": [
                clip.source_asset_id for clip in timeline.clips if clip.source_asset_id
            ],
            "source_version_ids": [
                clip.source_version_id for clip in timeline.clips if clip.source_version_id
            ],
        }
        changed = item.timeline_plan != projected_plan or item.timeline_clips != projected_clips
        item.timeline_plan = projected_plan
        item.timeline_clips = projected_clips
        return changed

    def _source_selection_hash(self, workflow: WorkflowV2) -> str:
        selected = [
            {
                "slot_id": slot.slot_id,
                "asset_id": record.asset_id,
                "version_id": record.version_id,
            }
            for _item, slot, record in self._selected_shot_video_records(workflow)
        ]
        bgm = self._selected_bgm_record(workflow)
        if bgm is not None:
            selected.append(
                {
                    "slot_id": bgm.slot_id or "",
                    "asset_id": bgm.asset_id,
                    "version_id": bgm.version_id,
                }
            )
        encoded = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode("utf-8")
        import hashlib

        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def _available_sources(self, workflow: WorkflowV2) -> list[WorkflowV2TimelineSource]:
        records: list[WorkflowV2TimelineSource] = []
        for item, slot, record in self._selected_shot_video_records(workflow):
            records.append(
                self._timeline_source(record, origin="selected_slot", slot_id=slot.slot_id)
            )
        bgm = self._selected_bgm_record(workflow)
        if bgm is not None:
            records.append(
                self._timeline_source(
                    bgm,
                    origin="selected_slot",
                    slot_id=bgm.slot_id,
                )
            )
        seen = {(source.asset_id, source.version_id) for source in records}
        for relation in self._asset_store.list_relations(
            target_workflow_id=workflow.workflow_id,
            relation_type="selected_for_timeline",
        ):
            if relation.target_node_id != FINAL_NODE_ID:
                continue
            version_id = relation.metadata.get("version_id")
            if not isinstance(version_id, str) or not version_id:
                continue
            record = self._asset_store.load_asset_version(relation.source_asset_id, version_id)
            if record is None or (record.asset_id, record.version_id) in seen:
                continue
            origin = "asset_library" if record.source_type == "imported" else "workflow_asset"
            records.append(self._timeline_source(record, origin=origin, slot_id=None))
            seen.add((record.asset_id, record.version_id))
        return records

    def _timeline_source(
        self,
        record: WorkflowAssetVersionV2,
        *,
        origin: str,
        slot_id: str | None,
    ) -> WorkflowV2TimelineSource:
        media_type = record.media_type
        if media_type not in {"video", "audio", "image"}:
            raise V2FinalCompositionTimelineError(
                "v2_timeline_unsupported_source_media",
                f"Unsupported timeline media type: {media_type}",
                status_code=400,
            )
        return WorkflowV2TimelineSource(
            asset_id=record.asset_id,
            version_id=record.version_id,
            media_type=media_type,
            display_name=str(record.metadata.get("display_name") or record.asset_id),
            public_url=record.public_url,
            duration_seconds=_duration_from_record(record, default=0) or None,
            origin=origin,  # type: ignore[arg-type]
            slot_id=slot_id,
        )

    def _stale_clip_ids(
        self,
        workflow: WorkflowV2,
        timeline: WorkflowV2Timeline,
    ) -> list[str]:
        selected_versions = {
            record.asset_id: record.version_id
            for _item, _slot, record in self._selected_shot_video_records(workflow)
        }
        bgm = self._selected_bgm_record(workflow)
        if bgm is not None:
            selected_versions[bgm.asset_id] = bgm.version_id
        return [
            clip.clip_id
            for clip in timeline.clips
            if clip.source_asset_id
            and clip.source_asset_id in selected_versions
            and clip.source_version_id != selected_versions[clip.source_asset_id]
        ]

    def _missing_source_clip_ids(
        self,
        workflow_id: str,
        timeline: WorkflowV2Timeline,
    ) -> list[str]:
        missing: list[str] = []
        for clip in timeline.clips:
            if clip.clip_type not in {"video", "audio", "image"}:
                continue
            if not clip.source_asset_id or not clip.source_version_id:
                missing.append(clip.clip_id)
                continue
            record = self._asset_store.load_asset_version(
                clip.source_asset_id,
                clip.source_version_id,
            )
            if record is None or record.workflow_id not in {workflow_id, None}:
                missing.append(clip.clip_id)
        return missing

    def _timeline_path(self, workflow_id: str) -> Path:
        return validate_v2_data_path(
            self._data_dir,
            Path("v2") / "workflows" / workflow_id / "final-composition" / "timeline.json",
            operation="v2-final-composition-timeline",
        )


def _duration_for_shot(item: WorkflowItemV2, record: WorkflowAssetVersionV2) -> float:
    return float(item.duration_seconds or _duration_from_record(record, default=5.0) or 5.0)


def _duration_from_record(record: WorkflowAssetVersionV2, *, default: float) -> float:
    value = record.metadata.get("duration_seconds") or record.metadata.get("duration")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _changed_clip_ids(
    current: WorkflowV2Timeline,
    incoming: WorkflowV2Timeline,
) -> list[str]:
    current_by_id = {clip.clip_id: clip.model_dump(mode="json") for clip in current.clips}
    return [
        clip.clip_id
        for clip in incoming.clips
        if current_by_id.get(clip.clip_id) != clip.model_dump(mode="json")
    ]


def _slug(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")
