from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.workflow_revisions import WorkflowRevisionState


class FinalCompositionTimelineClip(BaseModel):
    clip_id: str = Field(min_length=1)
    clip_type: Literal["video", "image", "audio", "subtitle"]
    source_asset_id: str | None = None
    source_node_id: str = Field(min_length=1)
    source_item_id: str | None = None
    start_time: float = Field(ge=0)
    duration: float = Field(gt=0)
    trim_start: float = Field(default=0, ge=0)
    trim_end: float | None = Field(default=None, gt=0)
    enabled: bool = True
    stale: bool = False
    stale_reason: str | None = None
    transform: dict[str, Any] = Field(default_factory=lambda: {"scale": 1.0, "x": 0, "y": 0})
    text: str | None = None
    style: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_and_text(self) -> "FinalCompositionTimelineClip":
        if self.clip_type in {"video", "image", "audio"} and not self.source_asset_id:
            raise ValueError("source_asset_id is required for media clips")
        if self.clip_type == "subtitle" and self.enabled and not self.text:
            raise ValueError("text is required for enabled subtitle clips")
        return self


class FinalCompositionTimelineTrack(BaseModel):
    track_id: str = Field(min_length=1)
    track_type: Literal["video", "image", "audio", "subtitle"]
    enabled: bool = True
    order: int = Field(ge=1)
    clips: list[FinalCompositionTimelineClip] = Field(default_factory=list)


class FinalCompositionTimeline(BaseModel):
    timeline_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    node_id: Literal["final-composition"] = "final-composition"
    version: int = Field(ge=1)
    source_graph_version: int | None = None
    duration_seconds: float = Field(ge=0)
    fps: int = Field(default=30, ge=1, le=120)
    resolution: str = "480p"
    aspect_ratio: str = "16:9"
    manual_timeline_dirty: bool = False
    tracks: list[FinalCompositionTimelineTrack] = Field(default_factory=list)
    updated_at: str | None = None
    updated_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalCompositionTimelineResponse(BaseModel):
    workflow_id: str
    node_id: Literal["final-composition"] = "final-composition"
    timeline: FinalCompositionTimeline
    available_sources: list[dict[str, Any]] = Field(default_factory=list)
    stale_clip_ids: list[str] = Field(default_factory=list)
    missing_source_clip_ids: list[str] = Field(default_factory=list)


class FinalCompositionTimelineSaveRequest(BaseModel):
    timeline: FinalCompositionTimeline
    expected_version: int = Field(ge=1)


class FinalCompositionRenderRequest(BaseModel):
    timeline_id: str
    timeline_version: int = Field(ge=1)
    acceptance_policy: Literal["manual_candidate"] = "manual_candidate"


class FinalCompositionRenderResponse(BaseModel):
    workflow_id: str
    node_id: Literal["final-composition"] = "final-composition"
    timeline_id: str
    timeline_version: int
    revision: WorkflowRevisionState
