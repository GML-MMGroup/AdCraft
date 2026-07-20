from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any

from app.core.config import Settings
from app.schemas.media_tasks import MediaSegmentStatus, MediaStatusResponse
from app.services.media_paths import with_public_urls
from app.services.workflow_media_segments import (
    final_composition_waiting_output,
    load_workflow_segments,
    segment_has_failed,
    segment_is_ready,
    sync_storyboard_video_run_with_segments,
)
from app.tools.media import MediaProvider, build_media_provider


@dataclass(frozen=True)
class MediaTaskPollResult:
    workflow_id: str
    segments: list[dict[str, Any]]
    all_ready: bool
    attempts: int


class MediaTaskService:
    def __init__(
        self,
        settings: Settings,
        media_provider: MediaProvider | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._media_provider = media_provider
        self._sleep = sleep
        from app.services.canvas_runtime_events import CanvasRuntimeEventService

        self._canvas_events = CanvasRuntimeEventService(settings.media_data_dir)

    @property
    def media_provider(self) -> MediaProvider:
        if self._media_provider is None:
            self._media_provider = build_media_provider(self._settings)
        return self._media_provider

    def load_workflow_segments(self, workflow_id: str) -> list[dict[str, Any]]:
        return load_workflow_segments(self._settings.media_data_dir, workflow_id)

    def media_status(
        self,
        workflow_id: str,
        *,
        timed_out: bool = False,
        attempts: int | None = None,
        message: str | None = None,
    ) -> MediaStatusResponse:
        segments = self.load_workflow_segments(workflow_id)
        if segments:
            sync_storyboard_video_run_with_segments(
                self._settings.media_data_dir,
                workflow_id,
                segments,
            )
        segment_statuses = [
            _segment_status(self._settings.media_data_dir, segment) for segment in segments
        ]
        all_segments_ready = bool(segments) and all(
            _segment_is_downloaded(self._settings.media_data_dir, segment) for segment in segments
        )
        final_video = _load_final_video(self._settings.media_data_dir, workflow_id)
        if segments and _final_status_can_refresh_from_segments(final_video):
            final_video = final_composition_waiting_output(
                self._settings.media_data_dir,
                workflow_id,
                segments,
                overwrite_ready=False,
            )
        final_status = str(final_video.get("status") or "not_started")
        return MediaStatusResponse(
            workflow_id=workflow_id,
            storyboard_video_status=_storyboard_video_status(
                segments,
                all_segments_ready=all_segments_ready,
            ),
            segments=segment_statuses,
            all_segments_ready=all_segments_ready,
            final_composition_status=final_status,
            final_video=final_video,
            timed_out=timed_out,
            attempts=attempts,
            message=message,
        )

    def refresh_media_status(self, workflow_id: str) -> MediaStatusResponse:
        self.media_status(workflow_id)
        self._recover_canvas_runtime(workflow_id)
        return self.media_status(workflow_id)

    def poll_media(
        self,
        workflow_id: str,
        *,
        download_media: bool = True,
        compose_when_ready: bool = True,
        wait_until_ready: bool = False,
        interval_seconds: int = 5,
        max_attempts: int = 60,
    ) -> MediaStatusResponse:
        if wait_until_ready:
            poll_result = self.poll_until_all_segments_ready(
                workflow_id,
                interval_seconds=interval_seconds,
                max_attempts=max_attempts,
                download_media=download_media,
            )
            sync_storyboard_video_run_with_segments(
                self._settings.media_data_dir,
                workflow_id,
                poll_result.segments,
            )
            if compose_when_ready:
                self.compose_when_ready(workflow_id)
            status = self.media_status(
                workflow_id,
                timed_out=_poll_timed_out(poll_result),
                attempts=poll_result.attempts,
                message=(
                    "Media polling reached max_attempts before all segments were ready."
                    if _poll_timed_out(poll_result)
                    else None
                ),
            )
            self._recover_canvas_runtime(workflow_id)
            self._emit_media_status_changed(workflow_id, status)
            return status

        if self._settings.media_mode.strip().lower() == "real":
            poll_result = self.poll_until_all_segments_ready(
                workflow_id,
                interval_seconds=0,
                max_attempts=1,
                download_media=download_media,
            )
            sync_storyboard_video_run_with_segments(
                self._settings.media_data_dir,
                workflow_id,
                poll_result.segments,
            )
        if compose_when_ready:
            self.compose_when_ready(workflow_id)
        status = self.media_status(workflow_id)
        self._recover_canvas_runtime(workflow_id)
        self._emit_media_status_changed(workflow_id, status)
        return status

    def _recover_canvas_runtime(self, workflow_id: str) -> None:
        from app.services.canvas_runtime_events import CanvasRuntimeRecoveryService

        CanvasRuntimeRecoveryService(self._settings).recover_workflow_runtime(workflow_id)

    def _emit_media_status_changed(
        self,
        workflow_id: str,
        status: MediaStatusResponse,
    ) -> None:
        payload = status.model_dump(mode="json")
        self._canvas_events.append_event(
            workflow_id,
            "media_status_changed",
            resource_type="media_status",
            resource_id=workflow_id,
            payload=payload,
        )
        storyboard_status = _runtime_status_from_storyboard_video_status(
            status.storyboard_video_status
        )
        if storyboard_status is not None:
            self._canvas_events.append_node_status_changed(
                workflow_id,
                execution_id=None,
                node_id="storyboard-video-generation",
                node_type="storyboard-video-generation",
                status=storyboard_status,
                previous_status=None,
                waiting_reason=("waiting_for_segments" if storyboard_status == "waiting" else None),
                has_active_output=status.all_segments_ready,
                output_status=status.storyboard_video_status,
            )

    def poll_video_task(self, task_id: str) -> dict[str, Any]:
        if not hasattr(self.media_provider, "retrieve_video_generation_task"):
            raise RuntimeError("Current media provider does not support video task polling.")
        return self.media_provider.retrieve_video_generation_task(task_id)  # type: ignore[attr-defined]

    def download_completed_segment(
        self,
        workflow_id: str,
        segment: dict[str, Any],
        *,
        download_media: bool,
    ) -> dict[str, Any]:
        task_id = segment.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return segment
        if not hasattr(self.media_provider, "retrieve_storyboard_video_task"):
            raise RuntimeError("Current media provider does not support storyboard task polling.")

        refreshed_segment = self.media_provider.retrieve_storyboard_video_task(  # type: ignore[attr-defined]
            task_id,
            workflow_id=workflow_id,
            source_assets=[
                asset_id
                for asset_id in segment.get("source_assets", [])
                if isinstance(asset_id, str)
            ],
            duration_seconds=int(segment.get("duration_seconds") or 0),
            segment_order=int(segment.get("order") or 1),
            scene_id=str(segment.get("scene_id") or f"scene-{segment.get('order') or 1}"),
            prompt=str(segment.get("prompt") or ""),
            resolution=str(segment.get("resolution") or ""),
            ratio=str(segment.get("ratio") or ""),
            download_media=download_media,
        )
        return with_public_urls({**segment, **refreshed_segment})

    def poll_until_all_segments_ready(
        self,
        workflow_id: str,
        *,
        interval_seconds: int = 10,
        max_attempts: int = 60,
        download_media: bool = False,
        on_segment_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> MediaTaskPollResult:
        attempts_completed = 0
        segments = self.load_workflow_segments(workflow_id)
        if not segments:
            return MediaTaskPollResult(
                workflow_id=workflow_id,
                segments=[],
                all_ready=False,
                attempts=0,
            )

        for attempt in range(1, max_attempts + 1):
            attempts_completed = attempt
            refreshed_segments = []
            for segment in segments:
                refreshed_segment = self._poll_segment(
                    workflow_id,
                    segment,
                    download_media=download_media,
                )
                refreshed_segments.append(refreshed_segment)
                if on_segment_update is not None:
                    on_segment_update(refreshed_segment)
            segments = sorted(refreshed_segments, key=lambda item: int(item.get("order") or 0))
            if self._segments_poll_completed(segments, download_media=download_media):
                break
            if any(segment_has_failed(segment) for segment in segments):
                break
            if attempt < max_attempts:
                self._sleep(interval_seconds)

        return MediaTaskPollResult(
            workflow_id=workflow_id,
            segments=segments,
            all_ready=all(
                _segment_is_downloaded(self._settings.media_data_dir, s) for s in segments
            ),
            attempts=attempts_completed,
        )

    def _poll_segment(
        self,
        workflow_id: str,
        segment: dict[str, Any],
        *,
        download_media: bool,
    ) -> dict[str, Any]:
        if _segment_is_downloaded(self._settings.media_data_dir, segment):
            return segment
        if segment_has_failed(segment):
            return segment
        if not _provider_supports_storyboard_polling(self):
            return segment
        return self.download_completed_segment(
            workflow_id,
            segment,
            download_media=download_media,
        )

    def _segments_poll_completed(
        self,
        segments: list[dict[str, Any]],
        *,
        download_media: bool,
    ) -> bool:
        all_downloaded = all(
            _segment_is_downloaded(self._settings.media_data_dir, segment) for segment in segments
        )
        all_tasks_finished = all(_segment_task_is_finished(segment) for segment in segments)
        return all_downloaded or (not download_media and all_tasks_finished)

    def compose_when_ready(self, workflow_id: str) -> dict[str, Any]:
        segments = self.load_workflow_segments(workflow_id)
        duration_seconds = sum(int(segment.get("duration_seconds") or 0) for segment in segments)
        if not segments or not all(
            _segment_is_downloaded(self._settings.media_data_dir, segment) for segment in segments
        ):
            return final_composition_waiting_output(
                self._settings.media_data_dir,
                workflow_id,
                segments,
                overwrite_ready=False,
            )

        return with_public_urls(
            self.media_provider.compose_final_video(  # type: ignore[attr-defined]
                {
                    "asset_id": "storyboard-video-generation",
                    "segments": segments,
                    "composition_status": "ready",
                },
                duration_seconds,
                workflow_id,
            )
        )


def _provider_supports_storyboard_polling(service: MediaTaskService) -> bool:
    return hasattr(service.media_provider, "retrieve_storyboard_video_task")


def _poll_timed_out(result: MediaTaskPollResult) -> bool:
    if result.all_ready:
        return False
    if any(str(segment.get("status") or "").lower() == "failed" for segment in result.segments):
        return False
    return bool(result.segments) and result.attempts > 0


def _final_status_can_refresh_from_segments(final_video: dict[str, Any]) -> bool:
    return str(final_video.get("status") or "not_started").lower() in {
        "not_started",
        "waiting_for_segments",
        "submitted",
        "running",
        "planned",
        "processing",
    }


def _segment_status(data_dir: Path, segment: dict[str, Any]) -> MediaSegmentStatus:
    enriched = with_public_urls(segment)
    status = str(enriched.get("status") or "submitted")
    if _segment_is_downloaded(data_dir, enriched):
        status = "downloaded"
    return MediaSegmentStatus(
        segment_id=enriched.get("asset_id"),
        order=int(enriched["order"]) if enriched.get("order") is not None else None,
        status=status,
        task_id=enriched.get("task_id"),
        task_query_url=enriched.get("task_query_url"),
        remote_url=enriched.get("remote_url") or enriched.get("url"),
        local_path=enriched.get("local_path"),
        public_url=enriched.get("public_url"),
        metadata_path=enriched.get("metadata_path"),
        duration_seconds=int(enriched["duration_seconds"])
        if enriched.get("duration_seconds") is not None
        else None,
        resolution=enriched.get("resolution"),
        aspect_ratio=enriched.get("aspect_ratio") or enriched.get("ratio"),
        error=enriched.get("error") or enriched.get("download_error"),
        download_status=enriched.get("download_status"),
        raw=enriched,
    )


def _storyboard_video_status(
    segments: list[dict[str, Any]],
    *,
    all_segments_ready: bool,
) -> str:
    if not segments:
        return "not_started"
    if any(segment_has_failed(segment) for segment in segments):
        return "failed"
    if all_segments_ready:
        return "ready"
    if any(str(segment.get("status") or "").lower() == "running" for segment in segments):
        return "running"
    return "submitted"


def _runtime_status_from_storyboard_video_status(status: str) -> str | None:
    normalized = status.strip().lower()
    if normalized in {"ready", "downloaded", "completed"}:
        return "completed"
    if normalized in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    if normalized in {"submitted", "running", "waiting", "processing"}:
        return "waiting"
    return None


def _load_final_video(data_dir: Path, workflow_id: str) -> dict[str, Any]:
    metadata_path = data_dir / "final" / workflow_id / "final-ad-video.json"
    if not metadata_path.exists():
        return {"status": "not_started"}
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload.setdefault("metadata_path", metadata_path.relative_to(data_dir).as_posix())
    if str(payload.get("status") or "").lower() == "ready":
        local_path = payload.get("local_path")
        if (
            not isinstance(local_path, str)
            or not local_path
            or not (data_dir / local_path).exists()
        ):
            payload["status"] = "failed"
            payload["composition_status"] = "failed"
            payload["local_path"] = None
            payload["public_url"] = None
            payload["error"] = (
                "Final video metadata is ready but local file does not exist: "
                f"{local_path or '<missing>'}"
            )
    return with_public_urls(payload)


def _segment_is_downloaded(data_dir: Path, segment: dict[str, Any]) -> bool:
    return segment_is_ready(data_dir, segment)


def _segment_task_is_finished(segment: dict[str, Any]) -> bool:
    return str(segment.get("status") or "").lower() in {
        "succeeded",
        "success",
        "ready",
        "failed",
        "error",
        "cancelled",
        "canceled",
    }


def _write_final_metadata(data_dir: Path, final_asset: dict[str, Any]) -> None:
    metadata_path = data_dir / str(final_asset["metadata_path"])
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(final_asset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
