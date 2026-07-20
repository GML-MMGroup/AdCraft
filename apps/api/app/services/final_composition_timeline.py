import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.final_composition import (
    FinalCompositionRenderRequest,
    FinalCompositionRenderResponse,
    FinalCompositionTimeline,
    FinalCompositionTimelineClip,
    FinalCompositionTimelineResponse,
    FinalCompositionTimelineSaveRequest,
    FinalCompositionTimelineTrack,
)
from app.schemas.video_editing import (
    EditingTimeline,
    ExportSettings,
    SubtitleItem,
    SubtitleTrack,
    VideoClip,
    VideoEditingExportRequest,
    VideoTrack,
)
from app.schemas.workflow_revisions import WorkflowRevisionState
from app.services.agent_trace import utc_now
from app.services.canvas_runtime_events import CanvasRuntimeEventService
from app.services.media_paths import public_url_for_path, with_public_urls
from app.services.video_editing import VideoEditingError, VideoEditingService
from app.services.workflow_asset_contract import legacy_output_assets_from_payload
from app.services.workflow_asset_history import prepare_generated_revision_candidates
from app.services.workflow_graph import load_graph, save_graph
from app.services.workflow_media_segments import (
    load_workflow_segments,
    segment_asset,
    segment_is_ready,
)
from app.services.workflow_state import persist_node_run, resolve_active_result

FINAL_NODE_ID = "final-composition"
FINAL_VIDEO_ENTITY_ID = "final-ad-video"
FINAL_VIDEO_SEMANTIC_TYPE = "final_video"


class FinalCompositionTimelineError(ValueError):
    def __init__(self, *, status_code: int, detail: dict[str, Any]) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail.get("message") or detail.get("code") or "timeline error"))


class FinalCompositionTimelineService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._events = CanvasRuntimeEventService(settings.media_data_dir)

    def get_timeline(self, workflow_id: str) -> FinalCompositionTimelineResponse:
        timeline = self._load_timeline(workflow_id)
        if timeline is None:
            timeline = self._build_default_timeline(workflow_id)
            self._write_timeline(timeline)
            self._emit_timeline_updated(timeline, stale_clip_ids=[])
        else:
            timeline = self._refresh_timeline(workflow_id, timeline)
        return self._response(workflow_id, timeline)

    def save_timeline(
        self,
        workflow_id: str,
        request: FinalCompositionTimelineSaveRequest,
    ) -> FinalCompositionTimelineResponse:
        current = self._load_timeline(workflow_id) or self._build_default_timeline(workflow_id)
        if request.expected_version != current.version:
            raise FinalCompositionTimelineError(
                status_code=409,
                detail={
                    "code": "timeline_version_conflict",
                    "message": "Timeline version does not match expected_version.",
                    "workflow_id": workflow_id,
                    "expected_version": request.expected_version,
                    "current_version": current.version,
                },
            )
        incoming = request.timeline.model_copy(deep=True)
        incoming.workflow_id = workflow_id
        incoming.node_id = FINAL_NODE_ID
        self._validate_timeline_sources(workflow_id, incoming)
        if _timeline_content(current) == _timeline_content(incoming):
            return self._response(workflow_id, current)
        incoming.version = current.version + 1
        incoming.manual_timeline_dirty = True
        incoming.updated_at = utc_now().isoformat()
        incoming.updated_by = "user"
        incoming.source_graph_version = self._graph_version(workflow_id)
        self._write_timeline(incoming)
        self._emit_timeline_updated(incoming, stale_clip_ids=_stale_clip_ids(incoming))
        return self._response(workflow_id, incoming)

    def render_timeline(
        self,
        workflow_id: str,
        request: FinalCompositionRenderRequest,
    ) -> FinalCompositionRenderResponse:
        timeline = self._load_timeline(workflow_id)
        if timeline is None:
            raise FinalCompositionTimelineError(
                status_code=404,
                detail={
                    "code": "timeline_not_found",
                    "message": "Final composition timeline not found.",
                    "workflow_id": workflow_id,
                },
            )
        if (
            timeline.timeline_id != request.timeline_id
            or timeline.version != request.timeline_version
        ):
            raise FinalCompositionTimelineError(
                status_code=409,
                detail={
                    "code": "timeline_version_conflict",
                    "message": "Render request does not match the saved timeline version.",
                    "workflow_id": workflow_id,
                    "timeline_id": request.timeline_id,
                    "timeline_version": request.timeline_version,
                    "current_version": timeline.version,
                },
            )
        self._validate_renderable(workflow_id, timeline)
        revision_id = f"rev_{uuid4().hex[:12]}"
        self._emit_final_render_started(timeline, revision_id)
        self._events.append_node_status_changed(
            workflow_id,
            execution_id=None,
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            status="running",
            previous_status=None,
        )
        try:
            export = VideoEditingService(self._settings).export(
                VideoEditingExportRequest(
                    workflow_id=workflow_id,
                    timeline=self._editing_timeline(workflow_id, timeline),
                    export_settings=ExportSettings(
                        resolution=timeline.resolution,
                        aspect_ratio=timeline.aspect_ratio,
                        fps=timeline.fps,
                    ),
                )
            )
            if export.status != "ready":
                raise VideoEditingError(export.error or "timeline render failed")
            if (
                not export.local_path
                or not (self._settings.media_data_dir / export.local_path).exists()
            ):
                raise VideoEditingError(
                    "timeline render did not produce a playable final video file"
                )
            state = self._create_final_candidate(workflow_id, timeline, revision_id, export)
        except Exception as exc:
            self._emit_final_render_failed(timeline, revision_id, str(exc))
            self._events.append_node_status_changed(
                workflow_id,
                execution_id=None,
                node_id=FINAL_NODE_ID,
                node_type=FINAL_NODE_ID,
                status="failed",
                previous_status="running",
                error=str(exc),
                error_code="timeline_render_failed",
            )
            raise FinalCompositionTimelineError(
                status_code=400,
                detail={
                    "code": "timeline_render_failed",
                    "message": str(exc),
                    "workflow_id": workflow_id,
                },
            ) from exc
        self._emit_final_render_completed(timeline, state)
        self._events.append_node_status_changed(
            workflow_id,
            execution_id=None,
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            status="completed",
            previous_status="running",
            output_status="candidate_pending",
            has_active_output=bool(self._active_final_assets(workflow_id)),
        )
        return FinalCompositionRenderResponse(
            workflow_id=workflow_id,
            timeline_id=timeline.timeline_id,
            timeline_version=timeline.version,
            revision=state,
        )

    def render_for_node_run(self, workflow_id: str) -> dict[str, Any]:
        timeline_response = self.get_timeline(workflow_id)
        response = self.render_timeline(
            workflow_id,
            FinalCompositionRenderRequest(
                timeline_id=timeline_response.timeline.timeline_id,
                timeline_version=timeline_response.timeline.version,
            ),
        )
        return {
            "workflow_id": workflow_id,
            "asset_id": FINAL_VIDEO_ENTITY_ID,
            "status": "candidate_pending",
            "composition_status": "candidate_pending",
            "timeline_id": response.timeline_id,
            "timeline_version": response.timeline_version,
            "revision_id": response.revision.revision_id,
            "candidate_asset_ids": [
                str(asset.get("asset_id") or "")
                for asset in response.revision.candidate_assets
                if asset.get("asset_id")
            ],
            "local_path": None,
            "public_url": None,
            "output_assets": [],
            "assets": [],
            "uses_llm_generation": False,
        }

    def _response(
        self,
        workflow_id: str,
        timeline: FinalCompositionTimeline,
    ) -> FinalCompositionTimelineResponse:
        sources = self._accepted_sources(workflow_id)
        source_by_id = {str(source.get("asset_id") or ""): source for source in sources}
        missing_clip_ids = []
        for clip in _timeline_clips(timeline):
            if not clip.enabled or clip.clip_type == "subtitle" or not clip.source_asset_id:
                continue
            source = source_by_id.get(clip.source_asset_id)
            if source is None or _source_file_missing(self._settings.media_data_dir, source):
                missing_clip_ids.append(clip.clip_id)
        return FinalCompositionTimelineResponse(
            workflow_id=workflow_id,
            timeline=timeline,
            available_sources=with_public_urls(sources),
            stale_clip_ids=_stale_clip_ids(timeline),
            missing_source_clip_ids=missing_clip_ids,
        )

    def _build_default_timeline(self, workflow_id: str) -> FinalCompositionTimeline:
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        ad_request = graph.ad_request if graph is not None else {}
        fps = 30
        resolution = str(ad_request.get("output_resolution") or "480p")
        aspect_ratio = str(ad_request.get("aspect_ratio") or "16:9")
        video_sources = [
            source
            for source in self._accepted_sources(workflow_id)
            if source.get("source_node_id") == "storyboard-video-generation"
        ]
        clips: list[FinalCompositionTimelineClip] = []
        cursor = 0.0
        for index, source in enumerate(video_sources, start=1):
            duration = float(source.get("duration_seconds") or 0) or 3.0
            source_item_id = str(
                source.get("entity_id") or source.get("segment_id") or f"segment-{index}"
            )
            clips.append(
                FinalCompositionTimelineClip(
                    clip_id=f"clip_{_slug(str(source.get('asset_id') or source_item_id))}",
                    clip_type="video",
                    source_asset_id=str(source.get("asset_id")),
                    source_node_id="storyboard-video-generation",
                    source_item_id=source_item_id,
                    start_time=cursor,
                    duration=duration,
                    trim_start=0,
                    trim_end=duration,
                    enabled=True,
                    stale=False,
                    metadata={"order": source.get("order")},
                )
            )
            cursor += duration
        duration_seconds = cursor or float(ad_request.get("duration_seconds") or 0)
        tracks = [
            FinalCompositionTimelineTrack(
                track_id="video_main",
                track_type="video",
                order=1,
                clips=clips,
            ),
            FinalCompositionTimelineTrack(
                track_id="image_overlay",
                track_type="image",
                order=2,
                clips=[],
            ),
            FinalCompositionTimelineTrack(
                track_id="subtitle",
                track_type="subtitle",
                order=3,
                clips=self._subtitle_clips(workflow_id),
            ),
            FinalCompositionTimelineTrack(
                track_id="audio_bgm",
                track_type="audio",
                order=4,
                clips=self._bgm_clips(workflow_id, duration_seconds),
            ),
        ]
        return FinalCompositionTimeline(
            timeline_id=f"timeline_{workflow_id}",
            workflow_id=workflow_id,
            version=1,
            source_graph_version=graph.version if graph is not None else None,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            manual_timeline_dirty=False,
            tracks=tracks,
            updated_at=utc_now().isoformat(),
            updated_by="system",
        )

    def _refresh_timeline(
        self,
        workflow_id: str,
        timeline: FinalCompositionTimeline,
    ) -> FinalCompositionTimeline:
        sources = self._accepted_sources(workflow_id)
        source_ids = {str(source.get("asset_id") or "") for source in sources}
        stale_clip_ids = []
        changed = False
        for track in timeline.tracks:
            for clip in track.clips:
                if clip.clip_type == "subtitle" or not clip.source_asset_id:
                    continue
                if clip.source_asset_id in source_ids:
                    continue
                if not clip.stale:
                    clip.stale = True
                    clip.stale_reason = f"source asset no longer active: {clip.source_asset_id}"
                    stale_clip_ids.append(clip.clip_id)
                    changed = True
        if changed:
            timeline.version += 1
            timeline.updated_at = utc_now().isoformat()
            self._write_timeline(timeline)
            self._mark_final_node_stale(workflow_id, "timeline source asset changed")
            self._emit_timeline_clip_stale(timeline, stale_clip_ids)
        return timeline

    def _validate_timeline_sources(
        self,
        workflow_id: str,
        timeline: FinalCompositionTimeline,
    ) -> None:
        source_by_id = {
            str(source.get("asset_id") or ""): source
            for source in self._accepted_sources(workflow_id)
        }
        invalid_clip_ids = []
        for clip in _timeline_clips(timeline):
            if clip.clip_type == "subtitle" or not clip.source_asset_id or clip.stale:
                continue
            source = source_by_id.get(clip.source_asset_id)
            if source is None:
                invalid_clip_ids.append(clip.clip_id)
        if invalid_clip_ids:
            raise FinalCompositionTimelineError(
                status_code=400,
                detail={
                    "code": "timeline_invalid_source",
                    "message": "Timeline contains source assets that are missing or not accepted.",
                    "workflow_id": workflow_id,
                    "clip_ids": invalid_clip_ids,
                },
            )

    def _validate_renderable(
        self,
        workflow_id: str,
        timeline: FinalCompositionTimeline,
    ) -> None:
        enabled_clips = [clip for clip in _timeline_clips(timeline) if clip.enabled]
        stale = [clip.clip_id for clip in enabled_clips if clip.stale]
        if stale:
            raise FinalCompositionTimelineError(
                status_code=400,
                detail={
                    "code": "timeline_has_stale_enabled_clips",
                    "message": "Timeline has stale enabled clips.",
                    "workflow_id": workflow_id,
                    "clip_ids": stale,
                },
            )
        source_by_id = {
            str(source.get("asset_id") or ""): source
            for source in self._accepted_sources(workflow_id)
        }
        missing = []
        for clip in enabled_clips:
            if clip.clip_type == "subtitle" or not clip.source_asset_id:
                continue
            source = source_by_id.get(clip.source_asset_id)
            if source is None or _source_file_missing(self._settings.media_data_dir, source):
                missing.append(clip.clip_id)
        if missing:
            raise FinalCompositionTimelineError(
                status_code=400,
                detail={
                    "code": "timeline_missing_source_asset",
                    "message": "Timeline has enabled clips with missing source assets.",
                    "workflow_id": workflow_id,
                    "clip_ids": missing,
                },
            )
        if not [clip for clip in enabled_clips if clip.clip_type == "video"]:
            raise FinalCompositionTimelineError(
                status_code=400,
                detail={
                    "code": "timeline_no_enabled_video_clips",
                    "message": "Timeline must contain at least one enabled video clip.",
                    "workflow_id": workflow_id,
                },
            )

    def _editing_timeline(
        self,
        workflow_id: str,
        timeline: FinalCompositionTimeline,
    ) -> EditingTimeline:
        source_by_id = {
            str(source.get("asset_id") or ""): source
            for source in self._accepted_sources(workflow_id)
        }
        video_clips: list[VideoClip] = []
        subtitle_items: list[SubtitleItem] = []
        order = 1
        for track in sorted(timeline.tracks, key=lambda item: item.order):
            for clip in sorted(track.clips, key=lambda item: item.start_time):
                if not clip.enabled:
                    continue
                if clip.clip_type == "video" and clip.source_asset_id:
                    source = source_by_id[clip.source_asset_id]
                    duration = float(clip.duration)
                    trim_end = float(clip.trim_end or duration)
                    video_clips.append(
                        VideoClip(
                            asset_id=clip.source_asset_id,
                            source_path=str(source.get("local_path") or source.get("uri")),
                            start_time=float(clip.trim_start),
                            end_time=trim_end,
                            timeline_start=float(clip.start_time),
                            timeline_end=float(clip.start_time + duration),
                            order=order,
                        )
                    )
                    order += 1
                elif clip.clip_type == "subtitle" and clip.text:
                    subtitle_items.append(
                        SubtitleItem(
                            text=clip.text,
                            start_time=float(clip.start_time),
                            end_time=float(clip.start_time + clip.duration),
                        )
                    )
        tracks: list[VideoTrack | SubtitleTrack] = [VideoTrack(clips=video_clips)]
        if subtitle_items:
            tracks.append(SubtitleTrack(subtitles=subtitle_items))
        return EditingTimeline(
            workflow_id=workflow_id,
            resolution=timeline.resolution,
            aspect_ratio=timeline.aspect_ratio,
            fps=timeline.fps,
            tracks=tracks,
        )

    def _create_final_candidate(
        self,
        workflow_id: str,
        timeline: FinalCompositionTimeline,
        revision_id: str,
        export: Any,
    ) -> WorkflowRevisionState:
        active = resolve_active_result(
            self._settings.media_data_dir, workflow_id, FINAL_NODE_ID, FINAL_NODE_ID
        )
        if active is None:
            active = self._persist_empty_final_active(workflow_id)
        source_clip_ids = [clip.clip_id for clip in _timeline_clips(timeline) if clip.enabled]
        source_asset_ids = [
            str(clip.source_asset_id)
            for clip in _timeline_clips(timeline)
            if clip.enabled and clip.source_asset_id
        ]
        local_path = export.local_path
        candidate_asset = {
            "asset_id": f"final-video-{revision_id}",
            "asset_type": "video",
            "type": "video",
            "media_type": "video",
            "kind": "video",
            "semantic_type": FINAL_VIDEO_SEMANTIC_TYPE,
            "role": FINAL_VIDEO_SEMANTIC_TYPE,
            "entity_id": FINAL_VIDEO_ENTITY_ID,
            "source_node_id": FINAL_NODE_ID,
            "local_path": local_path,
            "uri": local_path,
            "public_url": public_url_for_path(local_path) if local_path else None,
            "download_status": "ready" if local_path else None,
            "status": "ready",
            "is_active": False,
            "is_archived": False,
            "metadata": {
                "timeline_id": timeline.timeline_id,
                "timeline_version": timeline.version,
                "source_clip_ids": source_clip_ids,
                "source_asset_ids": source_asset_ids,
                "export_id": export.export_id,
                "render_status": export.status,
                "video_codec": export.video_codec,
                "ffmpeg_commands": [
                    command.model_dump(mode="json") for command in export.ffmpeg_commands
                ],
            },
        }
        candidate = prepare_generated_revision_candidates(
            data_dir=self._settings.media_data_dir,
            workflow_id=workflow_id,
            node_id=FINAL_NODE_ID,
            active_result=active,
            revision={
                "target_entity_id": FINAL_VIDEO_ENTITY_ID,
                "semantic_type": FINAL_VIDEO_SEMANTIC_TYPE,
                "target_field": "finalVideoUri",
                "instruction": "Render final composition timeline.",
            },
            generated_assets=[candidate_asset],
            state_change_run_id=revision_id,
            persist=True,
        )
        now = utc_now().isoformat()
        state = WorkflowRevisionState(
            workflow_id=workflow_id,
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            revision_id=revision_id,
            status="completed",
            generation_status="completed",
            acceptance_status="pending",
            visibility_status="visible",
            mode="regenerate_asset",
            target_entity_id=FINAL_VIDEO_ENTITY_ID,
            semantic_type=FINAL_VIDEO_SEMANTIC_TYPE,
            target_field="finalVideoUri",
            instruction="Render final composition timeline.",
            previous_active_asset_id=candidate.get("previous_active_asset_id") or None,
            previous_active_asset_ids=candidate.get("previous_active_asset_ids") or [],
            new_asset_id=str(candidate["candidate_assets"][0].get("asset_id") or "") or None,
            candidate_assets=candidate["candidate_assets"],
            candidate_output={
                "status": "candidate_pending",
                "assets": candidate["candidate_assets"],
                "output_assets": candidate["candidate_assets"],
            },
            started_at=now,
            finished_at=now,
            events_path=_relative_revision_events_path(workflow_id, revision_id),
            trace_path=_relative_revision_state_path(workflow_id, revision_id),
            metadata={
                "timeline_id": timeline.timeline_id,
                "timeline_version": timeline.version,
                "candidate_asset_ids": [
                    str(asset.get("asset_id") or "")
                    for asset in candidate["candidate_assets"]
                    if asset.get("asset_id")
                ],
                "source_clip_ids": source_clip_ids,
                "source_asset_ids": source_asset_ids,
                "acceptance_policy": "manual_candidate",
            },
        )
        self._write_revision_state(state)
        self._append_revision_event(state, "revision_candidate_created")
        self._emit_revision_status_changed(state)
        self._emit_candidate_created(state)
        self._emit_asset_history_updated(state)
        self._emit_node_candidate_summary_updated(state)
        return state

    def _persist_empty_final_active(self, workflow_id: str) -> dict[str, Any]:
        return persist_node_run(
            workflow_id=workflow_id,
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            status="completed",
            output={
                "status": "candidate_pending",
                "composition_status": "candidate_pending",
                "local_path": None,
                "structured_output": {"finalVideoUri": ""},
                "assets": [],
                "output_assets": [],
            },
            input_assets=[],
            output_assets=[],
            input_context={},
            error=None,
            source="final-composition-timeline-render",
            data_dir=self._settings.media_data_dir,
        )

    def _accepted_sources(self, workflow_id: str) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for segment in load_workflow_segments(self._settings.media_data_dir, workflow_id):
            if segment_is_ready(self._settings.media_data_dir, segment) and _asset_is_accepted(
                segment
            ):
                sources.append(segment_asset(self._settings.media_data_dir, segment))
        for node_id in ("bgm", "product-generation"):
            active = resolve_active_result(
                self._settings.media_data_dir, workflow_id, node_id, node_id
            )
            for asset in _active_output_assets(active or {}):
                if not _asset_is_accepted(asset):
                    continue
                semantic_type = str(asset.get("semantic_type") or "")
                if node_id == "bgm" and semantic_type not in {"bgm", "audio"}:
                    continue
                if node_id == "product-generation" and semantic_type != "product_image":
                    continue
                sources.append(
                    {
                        **asset,
                        "source_node_id": node_id,
                        "source_item_id": asset.get("entity_id"),
                        "public_url": public_url_for_path(asset.get("local_path"))
                        if asset.get("local_path")
                        else asset.get("public_url"),
                    }
                )
        return with_public_urls(sources)

    def _subtitle_clips(self, workflow_id: str) -> list[FinalCompositionTimelineClip]:
        active = resolve_active_result(
            self._settings.media_data_dir, workflow_id, "script", "script"
        )
        output = active.get("output") if isinstance(active, dict) else {}
        structured = output.get("structured_output") if isinstance(output, dict) else {}
        lines = structured.get("subtitleLines") if isinstance(structured, dict) else []
        clips: list[FinalCompositionTimelineClip] = []
        for index, line in enumerate(lines if isinstance(lines, list) else [], start=1):
            if not isinstance(line, dict) or not line.get("text"):
                continue
            start = float(line.get("start_time") or line.get("startTime") or 0)
            duration = float(line.get("duration") or line.get("durationSeconds") or 0)
            end_time = line.get("end_time") or line.get("endTime")
            if duration <= 0 and end_time not in (None, ""):
                duration = max(float(end_time) - start, 0)
            if duration <= 0:
                continue
            line_id = str(line.get("lineId") or line.get("line_id") or f"subtitle-{index}")
            clips.append(
                FinalCompositionTimelineClip(
                    clip_id=f"clip_{_slug(line_id)}",
                    clip_type="subtitle",
                    source_node_id="script",
                    source_item_id=line_id,
                    start_time=start,
                    duration=duration,
                    enabled=True,
                    text=str(line["text"]),
                )
            )
        return clips

    def _bgm_clips(
        self, workflow_id: str, duration_seconds: float
    ) -> list[FinalCompositionTimelineClip]:
        sources = [
            source
            for source in self._accepted_sources(workflow_id)
            if source.get("source_node_id") == "bgm"
        ]
        if not sources:
            return []
        source = sources[0]
        duration = float(source.get("duration_seconds") or duration_seconds or 1)
        return [
            FinalCompositionTimelineClip(
                clip_id=f"clip_{_slug(str(source.get('asset_id') or 'bgm'))}",
                clip_type="audio",
                source_asset_id=str(source.get("asset_id")),
                source_node_id="bgm",
                source_item_id=str(source.get("entity_id") or "bgm"),
                start_time=0,
                duration=duration,
                trim_start=0,
                trim_end=duration,
                enabled=True,
            )
        ]

    def _active_final_assets(self, workflow_id: str) -> list[dict[str, Any]]:
        active = resolve_active_result(
            self._settings.media_data_dir, workflow_id, FINAL_NODE_ID, FINAL_NODE_ID
        )
        return _active_output_assets(active or {})

    def _load_timeline(self, workflow_id: str) -> FinalCompositionTimeline | None:
        path = self._timeline_path(workflow_id)
        if not path.exists():
            return None
        try:
            return FinalCompositionTimeline.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as exc:
            raise FinalCompositionTimelineError(
                status_code=400,
                detail={
                    "code": "timeline_invalid_source",
                    "message": f"Stored timeline is invalid: {exc}",
                    "workflow_id": workflow_id,
                },
            ) from exc

    def _write_timeline(self, timeline: FinalCompositionTimeline) -> None:
        _write_json_atomic(
            self._timeline_path(timeline.workflow_id),
            timeline.model_dump(mode="json"),
        )

    def _timeline_path(self, workflow_id: str) -> Path:
        return (
            self._settings.media_data_dir
            / "workflows"
            / workflow_id
            / "final_composition"
            / "timeline.json"
        )

    def _write_revision_state(self, state: WorkflowRevisionState) -> None:
        path = self._settings.media_data_dir / state.trace_path
        _write_json_atomic(path, state.model_dump(mode="json"))

    def _append_revision_event(self, state: WorkflowRevisionState, event_type: str) -> None:
        path = self._settings.media_data_dir / state.events_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event_type": event_type,
                        "workflow_id": state.workflow_id,
                        "node_id": state.node_id,
                        "revision_id": state.revision_id,
                        "created_at": utc_now().isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def _mark_final_node_stale(self, workflow_id: str, reason: str) -> None:
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        if graph is None:
            return
        for node in graph.nodes:
            if node.id != FINAL_NODE_ID or node.locked:
                continue
            node.stale = True
            node.status = "stale"
            node.stale_reason = reason
            graph.version += 1
            saved = save_graph(self._settings.media_data_dir, graph)
            self._events.append_event(
                workflow_id,
                "graph_updated",
                node_id=FINAL_NODE_ID,
                node_type=FINAL_NODE_ID,
                resource_type="graph",
                resource_id=workflow_id,
                version=saved.version,
                payload={"node_id": FINAL_NODE_ID, "refresh": ["workflow_graph"]},
            )
            return

    def _graph_version(self, workflow_id: str) -> int | None:
        graph = load_graph(self._settings.media_data_dir, workflow_id)
        return graph.version if graph is not None else None

    def _emit_timeline_updated(
        self,
        timeline: FinalCompositionTimeline,
        *,
        stale_clip_ids: list[str],
    ) -> None:
        self._events.append_event(
            timeline.workflow_id,
            "timeline_updated",
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            resource_type="timeline",
            resource_id=timeline.timeline_id,
            version=timeline.version,
            payload={
                "timeline_id": timeline.timeline_id,
                "timeline_version": timeline.version,
                "stale_clip_ids": stale_clip_ids,
                "refresh": ["timeline", "workflow_graph"],
            },
        )

    def _emit_timeline_clip_stale(
        self,
        timeline: FinalCompositionTimeline,
        stale_clip_ids: list[str],
    ) -> None:
        first_stale = next(
            (clip for clip in _timeline_clips(timeline) if clip.clip_id in stale_clip_ids),
            None,
        )
        self._events.append_event(
            timeline.workflow_id,
            "timeline_clip_stale",
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            resource_type="timeline",
            resource_id=timeline.timeline_id,
            version=timeline.version,
            payload={
                "timeline_id": timeline.timeline_id,
                "stale_clip_ids": stale_clip_ids,
                "source_node_id": first_stale.source_node_id if first_stale else None,
                "source_item_id": first_stale.source_item_id if first_stale else None,
                "refresh": ["timeline", "workflow_graph"],
            },
        )

    def _emit_final_render_started(
        self,
        timeline: FinalCompositionTimeline,
        revision_id: str,
    ) -> None:
        self._emit_final_render_event(timeline, "final_render_started", revision_id, [], None, None)

    def _emit_final_render_completed(
        self,
        timeline: FinalCompositionTimeline,
        state: WorkflowRevisionState,
    ) -> None:
        self._emit_final_render_event(
            timeline,
            "final_render_completed",
            state.revision_id,
            [
                str(asset.get("asset_id") or "")
                for asset in state.candidate_assets
                if asset.get("asset_id")
            ],
            None,
            None,
        )

    def _emit_final_render_failed(
        self,
        timeline: FinalCompositionTimeline,
        revision_id: str,
        error: str,
    ) -> None:
        self._emit_final_render_event(
            timeline,
            "final_render_failed",
            revision_id,
            [],
            error,
            "timeline_render_failed",
        )

    def _emit_final_render_event(
        self,
        timeline: FinalCompositionTimeline,
        event_type: str,
        revision_id: str,
        candidate_asset_ids: list[str],
        error: str | None,
        error_code: str | None,
    ) -> None:
        self._events.append_event(
            timeline.workflow_id,
            event_type,
            node_id=FINAL_NODE_ID,
            node_type=FINAL_NODE_ID,
            resource_type="timeline",
            resource_id=timeline.timeline_id,
            version=timeline.version,
            payload={
                "timeline_id": timeline.timeline_id,
                "timeline_version": timeline.version,
                "revision_id": revision_id,
                "candidate_asset_ids": candidate_asset_ids,
                "error": error,
                "error_code": error_code,
                "refresh": ["timeline", "revision", "asset_history", "workflow_graph"],
            },
        )

    def _emit_revision_status_changed(self, state: WorkflowRevisionState) -> None:
        self._append_revision_canvas_event(
            state,
            "revision_status_changed",
            {
                "generation_status": state.generation_status or state.status,
                "acceptance_status": state.acceptance_status,
                "visibility_status": state.visibility_status,
                "waiting_reason": None,
                "error": state.error,
                "error_code": None,
                "refresh": ["revision"],
            },
        )

    def _emit_candidate_created(self, state: WorkflowRevisionState) -> None:
        self._append_revision_canvas_event(
            state,
            "candidate_created",
            {
                "candidate_asset_ids": state.metadata.get("candidate_asset_ids") or [],
                "candidate_count": 1 if state.candidate_assets else 0,
                "candidate_warning_count": 0,
                "refresh": ["revision", "asset_history", "candidate_summary"],
            },
            resource_type="candidate",
        )

    def _emit_asset_history_updated(self, state: WorkflowRevisionState) -> None:
        self._append_revision_canvas_event(
            state,
            "asset_history_updated",
            {
                "active_asset_ids": [],
                "refresh": ["asset_history"],
            },
            resource_type="asset_history",
            resource_id=f"{state.node_id}:{state.target_entity_id}:{state.semantic_type}",
        )

    def _emit_node_candidate_summary_updated(self, state: WorkflowRevisionState) -> None:
        revisions_root = (
            self._settings.media_data_dir
            / "runs"
            / state.workflow_id
            / "nodes"
            / state.node_id
            / "revisions"
        )
        pending_visible = 0
        for state_path in revisions_root.glob("rev_*/state.json"):
            try:
                candidate = WorkflowRevisionState.model_validate_json(
                    state_path.read_text(encoding="utf-8")
                )
            except ValueError:
                continue
            if (
                candidate.acceptance_status == "pending"
                and candidate.visibility_status == "visible"
            ):
                pending_visible += 1
        self._events.append_event(
            state.workflow_id,
            "node_candidate_summary_updated",
            node_id=state.node_id,
            node_type=state.node_type,
            resource_type="node",
            resource_id=state.node_id,
            payload={
                "node_id": state.node_id,
                "node_type": state.node_type,
                "candidate_count": pending_visible,
                "candidate_warning_count": 0,
                "pending_visible_candidate_count": pending_visible,
                "refresh": ["candidate_summary"],
            },
        )

    def _append_revision_canvas_event(
        self,
        state: WorkflowRevisionState,
        event_type: str,
        payload: dict[str, Any],
        *,
        resource_type: str = "revision",
        resource_id: str | None = None,
    ) -> None:
        self._events.append_event(
            state.workflow_id,
            event_type,
            node_id=state.node_id,
            node_type=state.node_type,
            resource_type=resource_type,
            resource_id=resource_id or state.revision_id,
            payload={
                "revision_id": state.revision_id,
                "node_id": state.node_id,
                "node_type": state.node_type,
                "entity_id": state.target_entity_id,
                "target_entity_id": state.target_entity_id,
                "semantic_type": state.semantic_type,
                "target_asset_id": state.target_asset_id,
                **payload,
            },
        )


def _timeline_clips(
    timeline: FinalCompositionTimeline,
) -> list[FinalCompositionTimelineClip]:
    return [clip for track in timeline.tracks for clip in track.clips]


def _stale_clip_ids(timeline: FinalCompositionTimeline) -> list[str]:
    return [clip.clip_id for clip in _timeline_clips(timeline) if clip.stale]


def _timeline_content(timeline: FinalCompositionTimeline) -> dict[str, Any]:
    payload = timeline.model_dump(mode="json")
    for key in ("version", "updated_at", "updated_by", "source_graph_version"):
        payload.pop(key, None)
    return payload


def _active_output_assets(active: dict[str, Any]) -> list[dict[str, Any]]:
    assets = legacy_output_assets_from_payload(active)
    seen: set[str] = set()
    deduped = []
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        deduped.append(asset)
    return deduped


def _asset_is_accepted(asset: dict[str, Any]) -> bool:
    if asset.get("is_active") is False or asset.get("is_archived") is True:
        return False
    if str(asset.get("acceptance_status") or "") in {"pending", "rejected", "superseded"}:
        return False
    if str(asset.get("candidate_status") or "") in {"pending", "rejected", "superseded"}:
        return False
    return True


def _source_file_missing(data_dir: Path, source: dict[str, Any]) -> bool:
    local_path = source.get("local_path") or source.get("uri")
    return isinstance(local_path, str) and bool(local_path) and not (data_dir / local_path).exists()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "item"


def _relative_revision_state_path(workflow_id: str, revision_id: str) -> str:
    return (
        Path("runs")
        / workflow_id
        / "nodes"
        / FINAL_NODE_ID
        / "revisions"
        / revision_id
        / "state.json"
    ).as_posix()


def _relative_revision_events_path(workflow_id: str, revision_id: str) -> str:
    return (
        Path("runs")
        / workflow_id
        / "nodes"
        / FINAL_NODE_ID
        / "revisions"
        / revision_id
        / "events.ndjson"
    ).as_posix()
