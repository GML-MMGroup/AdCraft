from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class VideoClip(BaseModel):
    asset_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    timeline_start: float = Field(ge=0)
    timeline_end: float = Field(gt=0)
    order: int = Field(ge=1)
    volume: float = Field(default=1.0, ge=0, le=2)
    muted: bool = False

    @model_validator(mode="after")
    def validate_clip_times(self) -> "VideoClip":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        if self.timeline_end <= self.timeline_start:
            raise ValueError("timeline_end must be greater than timeline_start")
        return self


class VideoTrack(BaseModel):
    type: Literal["video"] = "video"
    clips: list[VideoClip] = Field(default_factory=list)


class SubtitleItem(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    position: Literal["top", "center", "bottom"] = "bottom"
    font_size: int = Field(default=32, ge=8, le=120)
    color: str = "#FFFFFF"
    background: str | None = None
    alignment: Literal["left", "center", "right"] = "center"

    @model_validator(mode="after")
    def validate_subtitle_times(self) -> "SubtitleItem":
        if self.end_time <= self.start_time:
            raise ValueError("subtitle end_time must be greater than start_time")
        return self


class SubtitleTrack(BaseModel):
    type: Literal["subtitle"] = "subtitle"
    subtitles: list[SubtitleItem] = Field(default_factory=list)


class Watermark(BaseModel):
    image_path: str = Field(min_length=1)
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"] = (
        "top-right"
    )
    opacity: float = Field(default=1.0, ge=0, le=1)
    scale: float = Field(default=0.2, gt=0, le=1)
    start_time: float = Field(default=0, ge=0)
    end_time: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_watermark_times(self) -> "Watermark":
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("watermark end_time must be greater than start_time")
        return self


TimelineTrack = VideoTrack | SubtitleTrack


class EditingTimeline(BaseModel):
    workflow_id: str = Field(min_length=1)
    resolution: str = "480p"
    aspect_ratio: str = "16:9"
    fps: int = Field(default=30, ge=1, le=120)
    tracks: list[TimelineTrack] = Field(default_factory=list)
    watermarks: list[Watermark] = Field(default_factory=list)

    @field_validator("aspect_ratio")
    @classmethod
    def normalize_aspect_ratio(cls, value: str) -> str:
        return value.strip().replace("：", ":")


class ExportSettings(BaseModel):
    resolution: str = "480p"
    aspect_ratio: str = "16:9"
    fps: int = Field(default=30, ge=1, le=120)
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    bitrate: str = "2500k"
    output_format: Literal["mp4"] = "mp4"

    @field_validator("aspect_ratio")
    @classmethod
    def normalize_export_aspect_ratio(cls, value: str) -> str:
        return value.strip().replace("：", ":")


class VideoEditingExportRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    timeline: EditingTimeline | None = None
    export_settings: ExportSettings = Field(default_factory=ExportSettings)


class FfmpegCommandRecord(BaseModel):
    stage: str
    command: list[str]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


class VideoEditingExportResult(BaseModel):
    workflow_id: str
    export_id: str
    status: Literal["planned", "ready", "failed"]
    local_path: str | None = None
    intended_local_path: str | None = None
    public_url: str | None = None
    duration_seconds: float
    resolution: str
    aspect_ratio: str
    video_codec: str | None = None
    source_clips: list[str]
    subtitle_tracks: list[str] = Field(default_factory=list)
    watermark: str | None = None
    ffmpeg_commands: list[FfmpegCommandRecord]
    metadata_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
