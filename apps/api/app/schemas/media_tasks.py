from typing import Any

from pydantic import BaseModel, Field


class MediaPollRequest(BaseModel):
    download_media: bool = True
    compose_when_ready: bool = True
    wait_until_ready: bool = False
    interval_seconds: int = Field(default=5, ge=0, le=30)
    max_attempts: int = Field(default=60, ge=1, le=120)


class MediaSegmentStatus(BaseModel):
    segment_id: str | None = None
    order: int | None = None
    status: str
    task_id: str | None = None
    task_query_url: str | None = None
    remote_url: str | None = None
    local_path: str | None = None
    public_url: str | None = None
    metadata_path: str | None = None
    duration_seconds: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    error: str | None = None
    download_status: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MediaStatusResponse(BaseModel):
    workflow_id: str
    storyboard_video_status: str
    segments: list[MediaSegmentStatus] = Field(default_factory=list)
    all_segments_ready: bool = False
    final_composition_status: str
    final_video: dict[str, Any] = Field(default_factory=dict)
    timed_out: bool = False
    attempts: int | None = None
    message: str | None = None
