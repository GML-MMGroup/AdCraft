import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.services.media_paths import public_url_for_path
from app.schemas.video_editing import (
    EditingTimeline,
    ExportSettings,
    FfmpegCommandRecord,
    SubtitleItem,
    SubtitleTrack,
    VideoClip,
    VideoEditingExportRequest,
    VideoEditingExportResult,
    VideoTrack,
    Watermark,
)
from app.tools.ffmpeg import FfmpegResult, FfmpegTool


class VideoEditingError(RuntimeError):
    """Raised when an editing timeline cannot be exported."""


class VideoEditingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def export(self, request: VideoEditingExportRequest) -> VideoEditingExportResult:
        workflow_id = request.workflow_id
        export_id = f"exp_{uuid4().hex[:12]}"
        ffmpeg = FfmpegTool(
            ffmpeg_path=self._settings.ffmpeg_path,
            dry_run=self._settings.media_mode.strip().lower() == "mock",
        )
        export_settings = request.export_settings.model_copy(
            update={
                "video_codec": ffmpeg.resolve_video_codec(
                    self._settings.ffmpeg_video_codec or request.export_settings.video_codec
                )
            }
        )
        timeline = request.timeline or self._default_timeline(workflow_id, export_settings)
        clips = _video_clips(timeline)
        if not clips:
            raise VideoEditingError("Editing timeline must contain at least one video clip.")
        self._validate_clip_sources(clips)
        watermarks = timeline.watermarks
        self._validate_watermarks(watermarks)

        final_dir = self._settings.media_data_dir / "final" / workflow_id
        work_dir = final_dir / "editing" / export_id
        final_relative_path = Path("final") / workflow_id / "final-ad-video.mp4"
        final_output_path = self._settings.media_data_dir / final_relative_path
        metadata_relative_path = Path("final") / workflow_id / "final-ad-video.json"
        command_records: list[FfmpegCommandRecord] = []
        source_clips = [clip.asset_id for clip in sorted(clips, key=lambda clip: clip.order)]
        subtitle_paths: list[str] = []
        duration_seconds = max(clip.timeline_end for clip in clips)
        current_video_path: Path | None = None
        error: str | None = None

        try:
            current_video_path = self._trim_and_concat_clips(
                clips=clips,
                work_dir=work_dir,
                ffmpeg=ffmpeg,
                export_settings=export_settings,
                command_records=command_records,
                force_trim=request.timeline is not None,
            )
            subtitle_items = _subtitle_items(timeline)
            if subtitle_items:
                subtitle_relative_path = Path("final") / workflow_id / "subtitles.srt"
                subtitle_path = self._settings.media_data_dir / subtitle_relative_path
                _write_srt(subtitle_path, subtitle_items)
                subtitle_paths.append(subtitle_relative_path.as_posix())
                subtitled_path = work_dir / "subtitled.mp4"
                result = ffmpeg.burn_subtitles(
                    current_video_path,
                    subtitle_path,
                    subtitled_path,
                    export_settings,
                )
                command_records.append(_command_record("burn_subtitles", result))
                if not result.ok:
                    raise VideoEditingError(_ffmpeg_error(result))
                current_video_path = subtitled_path

            for index, watermark in enumerate(watermarks, start=1):
                watermarked_path = work_dir / f"watermarked-{index}.mp4"
                result = ffmpeg.add_watermark(
                    current_video_path,
                    self._resolve_media_path(watermark.image_path),
                    watermarked_path,
                    watermark,
                    export_settings,
                )
                command_records.append(_command_record("add_watermark", result))
                if not result.ok:
                    raise VideoEditingError(_ffmpeg_error(result))
                current_video_path = watermarked_path

            result = ffmpeg.transcode_video(
                current_video_path,
                final_output_path,
                export_settings,
            )
            command_records.append(_command_record("transcode", result))
            if not result.ok:
                copy_result = _copy_existing_video_to_final(current_video_path, final_output_path)
                command_records.append(_command_record("copy_concat_fallback", copy_result))
                if not copy_result.ok:
                    raise VideoEditingError(_ffmpeg_error(result) or _ffmpeg_error(copy_result))
                export_settings = export_settings.model_copy(update={"video_codec": "copy"})
            elif (
                self._settings.media_mode.strip().lower() != "mock"
                and not final_output_path.exists()
            ):
                raise VideoEditingError(
                    "FFmpeg transcode reported success but final video file does not exist."
                )

            status = "planned" if self._settings.media_mode.strip().lower() == "mock" else "ready"
            local_path = None if status == "planned" else final_relative_path.as_posix()
        except VideoEditingError as exc:
            status = "failed"
            local_path = None
            error = str(exc)

        export_result = VideoEditingExportResult(
            workflow_id=workflow_id,
            export_id=export_id,
            status=status,  # type: ignore[arg-type]
            local_path=local_path,
            intended_local_path=final_relative_path.as_posix(),
            public_url=None,
            duration_seconds=duration_seconds,
            resolution=export_settings.resolution,
            aspect_ratio=export_settings.aspect_ratio,
            video_codec=export_settings.video_codec,
            source_clips=source_clips,
            subtitle_tracks=subtitle_paths,
            watermark=watermarks[0].image_path if watermarks else None,
            ffmpeg_commands=command_records,
            metadata_path=metadata_relative_path.as_posix(),
            error=error,
        )
        _attach_export_public_url(export_result)
        self._write_metadata(export_result)
        self._cleanup_work_dir(work_dir, export_result.status)
        return export_result

    def get_export(self, export_id: str) -> VideoEditingExportResult:
        for metadata_path in (self._settings.media_data_dir / "final").glob(
            "*/final-ad-video.json"
        ):
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            if payload.get("export_id") == export_id:
                return VideoEditingExportResult.model_validate(payload)
        raise VideoEditingError(f"Video export not found: {export_id}.")

    def _trim_and_concat_clips(
        self,
        *,
        clips: list[VideoClip],
        work_dir: Path,
        ffmpeg: FfmpegTool,
        export_settings: ExportSettings,
        command_records: list[FfmpegCommandRecord],
        force_trim: bool,
    ) -> Path:
        ordered_clips = sorted(clips, key=lambda clip: clip.order)
        concat_inputs: list[Path] = []
        for clip in ordered_clips:
            source_path = self._resolve_media_path(clip.source_path)
            if force_trim:
                trim_path = work_dir / f"trimmed-{clip.order}.mp4"
                result = ffmpeg.trim_video(
                    source_path,
                    trim_path,
                    clip.start_time,
                    clip.end_time,
                )
                command_records.append(_command_record("trim", result))
                if not result.ok:
                    raise VideoEditingError(_ffmpeg_error(result))
                concat_inputs.append(trim_path)
            else:
                concat_inputs.append(source_path)

        concat_path = work_dir / "concat.mp4"
        concat_list_path = work_dir / "concat-list.txt"
        concat_result = ffmpeg.concat_videos(
            concat_inputs,
            concat_path,
            concat_list_path,
            export_settings,
        )
        command_records.append(_command_record("concat", concat_result))
        if concat_result.ok:
            return concat_path

        fallback_result = ffmpeg.concat_videos(
            concat_inputs,
            concat_path,
            concat_list_path,
            export_settings,
            reencode=True,
        )
        command_records.append(_command_record("concat_reencode", fallback_result))
        if not fallback_result.ok:
            raise VideoEditingError(_ffmpeg_error(concat_result) or _ffmpeg_error(fallback_result))
        return concat_path

    def _default_timeline(
        self,
        workflow_id: str,
        export_settings: ExportSettings,
    ) -> EditingTimeline:
        segment_metadata = _load_segment_metadata(self._settings.media_data_dir, workflow_id)
        if not segment_metadata:
            raise VideoEditingError(
                f"No downloaded video segments found for workflow_id={workflow_id}."
            )

        clips = []
        timeline_cursor = 0.0
        for segment in segment_metadata:
            duration = float(segment.get("duration_seconds") or 0)
            if duration <= 0:
                raise VideoEditingError(
                    f"Segment {segment.get('asset_id')} has invalid duration_seconds."
                )
            clip = VideoClip(
                asset_id=str(segment.get("asset_id") or f"segment-{segment['order']}"),
                source_path=str(segment["local_path"]),
                start_time=0,
                end_time=duration,
                timeline_start=timeline_cursor,
                timeline_end=timeline_cursor + duration,
                order=int(segment["order"]),
            )
            clips.append(clip)
            timeline_cursor += duration

        return EditingTimeline(
            workflow_id=workflow_id,
            resolution=export_settings.resolution,
            aspect_ratio=export_settings.aspect_ratio,
            fps=export_settings.fps,
            tracks=[VideoTrack(clips=clips)],
        )

    def _validate_clip_sources(self, clips: list[VideoClip]) -> None:
        missing_paths = [
            clip.source_path
            for clip in clips
            if not self._resolve_media_path(clip.source_path).exists()
        ]
        if missing_paths:
            raise VideoEditingError(
                "Video clip source file does not exist: " + ", ".join(missing_paths)
            )

    def _validate_watermarks(self, watermarks: list[Watermark]) -> None:
        missing_paths = [
            watermark.image_path
            for watermark in watermarks
            if not self._resolve_media_path(watermark.image_path).exists()
        ]
        if missing_paths:
            raise VideoEditingError(
                "Watermark image file does not exist: " + ", ".join(missing_paths)
            )

    def _resolve_media_path(self, path: str) -> Path:
        source_path = Path(path)
        return source_path if source_path.is_absolute() else self._settings.media_data_dir / path

    def _write_metadata(self, result: VideoEditingExportResult) -> None:
        metadata_path = self._settings.media_data_dir / result.metadata_path
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _cleanup_work_dir(self, work_dir: Path, status: str) -> None:
        if status == "ready" and not self._settings.keep_intermediate_files:
            shutil.rmtree(work_dir, ignore_errors=True)
            return
        if status == "failed" and not self._settings.keep_failed_intermediate_files:
            shutil.rmtree(work_dir, ignore_errors=True)


def _video_clips(timeline: EditingTimeline) -> list[VideoClip]:
    clips: list[VideoClip] = []
    for track in timeline.tracks:
        if isinstance(track, VideoTrack):
            clips.extend(track.clips)
    return clips


def _subtitle_items(timeline: EditingTimeline) -> list[SubtitleItem]:
    subtitles: list[SubtitleItem] = []
    for track in timeline.tracks:
        if isinstance(track, SubtitleTrack):
            subtitles.extend(track.subtitles)
    return sorted(subtitles, key=lambda subtitle: subtitle.start_time)


def _load_segment_metadata(data_dir: Path, workflow_id: str) -> list[dict[str, Any]]:
    segment_dir = data_dir / "videos" / workflow_id / "segments"
    metadata_items = []
    for metadata_path in segment_dir.glob("segment-*.json"):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        local_path = payload.get("local_path")
        if (
            isinstance(local_path, str)
            and payload.get("download_status") in {"downloaded", "ready"}
            and (data_dir / local_path).exists()
        ):
            metadata_items.append(payload)
    metadata_items.sort(key=lambda segment: int(segment.get("order") or 0))
    return metadata_items


def _write_srt(output_path: Path, subtitles: list[SubtitleItem]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, subtitle in enumerate(subtitles, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_srt_time(subtitle.start_time)} --> {_srt_time(subtitle.end_time)}",
                    subtitle.text,
                    "",
                ]
            )
        )
    output_path.write_text("\n".join(blocks), encoding="utf-8")


def _srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def _command_record(stage: str, result: FfmpegResult) -> FfmpegCommandRecord:
    return FfmpegCommandRecord(
        stage=stage,
        command=result.command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _attach_export_public_url(export_result: VideoEditingExportResult) -> None:
    if export_result.local_path:
        export_result.public_url = public_url_for_path(export_result.local_path)


def _ffmpeg_error(result: FfmpegResult) -> str:
    return result.stderr or result.stdout or "ffmpeg failed"


def _copy_existing_video_to_final(source_path: Path | None, output_path: Path) -> FfmpegResult:
    command = [
        "copy",
        source_path.as_posix() if source_path is not None else "",
        output_path.as_posix(),
    ]
    if source_path is None or not source_path.exists():
        return FfmpegResult(command=command, returncode=1, stderr="No intermediate video to copy.")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, output_path)
    except OSError as exc:
        return FfmpegResult(command=command, returncode=1, stderr=str(exc))
    return FfmpegResult(command=command, returncode=0)
