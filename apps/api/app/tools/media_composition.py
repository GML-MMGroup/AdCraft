from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.schemas.video_editing import (
    EditingTimeline,
    ExportSettings,
    VideoClip,
    VideoEditingExportRequest,
    VideoTrack,
)
from app.services.video_editing import VideoEditingService
from app.tools.media_artifact_io import _save_artifact, _write_json_metadata
from app.tools.seedance_adapter import DEFAULT_VIDEO_RATIO, _final_video_segments


def _segments_are_downloaded(segments: list[dict[str, Any]]) -> bool:
    return bool(segments) and all(
        segment.get("local_path") and segment.get("download_status") in {"downloaded", "ready"}
        for segment in segments
    )


def _composed_video_url(segments: list[dict[str, Any]]) -> str | None:
    segment_urls = [
        segment.get("url") for segment in segments if isinstance(segment.get("url"), str)
    ]
    if len(segment_urls) == len(segments) and segment_urls:
        return segment_urls[-1]
    return None


def generate_final_video_from_multimodal_prompt(
    final_video_prompt: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    source_assets = [
        asset["asset_id"]
        for asset in final_video_prompt.get("input_assets", [])
        if asset.get("asset_id")
    ]
    segments = [
        _save_artifact(
            data_dir,
            "final",
            workflow_id,
            f"segment-{segment['order']}.json",
            {
                "provider": "mock-final-video-segment-generator",
                **segment,
                "mime_type": "application/json",
                "status": "ready",
            },
        )
        for segment in _final_video_segments(final_video_prompt)
    ]
    return _save_artifact(
        data_dir,
        "final",
        workflow_id,
        "final-video-generation.json",
        {
            "provider": "mock-final-video-generator",
            "asset_id": "final-video-generation",
            "source_assets": source_assets,
            "duration_seconds": final_video_prompt.get("duration_seconds"),
            "mime_type": "application/json",
            "segments": segments,
            "generation_prompt": final_video_prompt,
            "composition_status": "ready",
            "status": "ready",
        },
    )


def synchronize_audio_video(
    video_asset: dict[str, Any],
    audio_asset: dict[str, Any],
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    return _save_artifact(
        data_dir,
        "videos",
        workflow_id,
        "synchronized-preview-video.json",
        {
            "provider": "mock-timeline-engine",
            "asset_id": "synchronized-preview-video",
            "video_asset": video_asset["asset_id"],
            "audio_asset": audio_asset["asset_id"],
            "status": "ready",
        },
    )


def compose_final_video(
    synchronized_asset: dict[str, Any],
    duration_seconds: int,
    workflow_id: str,
    data_dir: Path,
) -> dict[str, Any]:
    segments = synchronized_asset.get("segments")
    source_segments: list[str] = []
    if isinstance(segments, list):
        ordered_segments = sorted(
            [segment for segment in segments if isinstance(segment, dict)],
            key=lambda segment: int(segment.get("order") or 0),
        )
        source_segments = [
            str(segment["asset_id"]) for segment in ordered_segments if segment.get("asset_id")
        ]
        if ordered_segments and not _segments_are_downloaded(ordered_segments):
            final_asset = {
                "workflow_id": workflow_id,
                "provider": "mock-compositor",
                "asset_id": "final-ad-video",
                "source_asset": synchronized_asset["asset_id"],
                "source_segments": source_segments,
                "duration_seconds": duration_seconds,
                "operation": "wait for generated video segments before composition",
                "uses_llm_generation": False,
                "mime_type": "application/json",
                "status": "waiting_for_segments",
                "local_path": None,
                "metadata_path": f"final/{workflow_id}/final-ad-video.json",
            }
            _write_json_metadata(data_dir, final_asset["metadata_path"], final_asset)
            return final_asset
    return _save_artifact(
        data_dir,
        "final",
        workflow_id,
        "final-ad-video.json",
        {
            "provider": "mock-compositor",
            "asset_id": "final-ad-video",
            "source_asset": synchronized_asset["asset_id"],
            "source_segments": source_segments,
            "duration_seconds": duration_seconds,
            "operation": "assemble generated assets on a deterministic editing timeline",
            "uses_llm_generation": False,
            "mime_type": "application/json",
            "status": "ready",
        },
    )


def compose_downloaded_video_segments(
    *,
    settings: Settings,
    synchronized_asset: dict[str, Any],
    duration_seconds: int,
    workflow_id: str,
) -> dict[str, Any]:
    segments = sorted(
        [
            segment
            for segment in synchronized_asset.get("segments", [])
            if isinstance(segment, dict)
        ],
        key=lambda segment: int(segment.get("order") or 0),
    )
    source_segments = [segment.get("asset_id") for segment in segments if segment.get("asset_id")]
    missing_segments = [
        segment
        for segment in segments
        if not segment.get("local_path")
        or segment.get("download_status") not in {"downloaded", "ready"}
        or not (settings.media_data_dir / str(segment.get("local_path"))).exists()
    ]
    final_json_path = Path("final") / workflow_id / "final-ad-video.json"
    if missing_segments:
        asset = {
            "workflow_id": workflow_id,
            "provider": settings.composition_provider,
            "asset_id": "final-ad-video",
            "source_asset": synchronized_asset["asset_id"],
            "source_segments": source_segments,
            "duration_seconds": duration_seconds,
            "mime_type": "video/mp4",
            "operation": "wait for all generated video segments before composition",
            "uses_llm_generation": False,
            "status": "waiting_for_segments",
            "local_path": None,
            "metadata_path": final_json_path.as_posix(),
        }
        _write_json_metadata(settings.media_data_dir, final_json_path, asset)
        return asset

    timeline_cursor = 0.0
    clips = []
    for segment in segments:
        segment_duration = float(segment.get("duration_seconds") or 0)
        clips.append(
            VideoClip(
                asset_id=str(segment.get("asset_id") or f"segment-{segment['order']}"),
                source_path=str(segment["local_path"]),
                start_time=0,
                end_time=segment_duration,
                timeline_start=timeline_cursor,
                timeline_end=timeline_cursor + segment_duration,
                order=int(segment.get("order") or 0),
            )
        )
        timeline_cursor += segment_duration
    export_settings = ExportSettings(
        resolution=str(segments[0].get("resolution") or settings.video_generation_resolution),
        aspect_ratio=str(segments[0].get("ratio") or DEFAULT_VIDEO_RATIO),
    )
    export_result = VideoEditingService(settings).export(
        VideoEditingExportRequest(
            workflow_id=workflow_id,
            timeline=EditingTimeline(
                workflow_id=workflow_id,
                resolution=export_settings.resolution,
                aspect_ratio=export_settings.aspect_ratio,
                fps=export_settings.fps,
                tracks=[VideoTrack(clips=clips)],
            ),
            export_settings=export_settings,
        )
    )
    export_payload = export_result.model_dump(mode="json")
    asset = {
        **export_payload,
        "workflow_id": workflow_id,
        "provider": settings.composition_provider,
        "asset_id": "final-ad-video",
        "source_asset": synchronized_asset["asset_id"],
        "source_segments": source_segments,
        "local_path": export_result.local_path,
        "metadata_path": final_json_path.as_posix(),
        "duration_seconds": duration_seconds,
        "resolution": segments[0].get("resolution"),
        "ratio": segments[0].get("ratio"),
        "mime_type": "video/mp4",
        "operation": "ffmpeg concat ordered storyboard video segments",
        "uses_llm_generation": False,
        "status": export_result.status,
        "ffmpeg_commands": export_payload["ffmpeg_commands"],
        "error": export_result.error,
    }
    _write_json_metadata(settings.media_data_dir, final_json_path, asset)
    return asset
