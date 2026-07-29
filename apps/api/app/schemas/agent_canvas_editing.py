"""Strict contracts for Agent Canvas Editing nodes and exports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas import CanvasNodeErrorV2, CanvasNodeStatusV2


class _EditingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditingOutputSettingsV2(_EditingModel):
    resolution: str | None = None
    aspect_ratio: str | None = None
    fps: float | None = Field(default=None, gt=0, le=120)
    video_codec: Literal["h264"] = "h264"
    audio_codec: Literal["aac"] = "aac"
    container: Literal["mp4"] = "mp4"


class EditingManifestV2(_EditingModel):
    ordered_video_binding_ids: tuple[str, ...] = ()
    bgm_audio_binding_id: str | None = None
    bgm_volume: float = Field(default=0.20, ge=0.0, le=1.0)
    output: EditingOutputSettingsV2 = Field(default_factory=EditingOutputSettingsV2)
    manifest_revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_unique_video_bindings(self) -> "EditingManifestV2":
        if len(set(self.ordered_video_binding_ids)) != len(self.ordered_video_binding_ids):
            raise ValueError("Editing video binding IDs must be unique.")
        if self.bgm_audio_binding_id in self.ordered_video_binding_ids:
            raise ValueError("The BGM binding cannot also be a video binding.")
        return self


EditingSkippedReasonV2 = Literal[
    "source_not_ready",
    "source_failed",
    "source_output_unavailable",
    "source_media_invalid",
]


class EditingSkippedInputV2(_EditingModel):
    node_id: str
    reason: EditingSkippedReasonV2


class EditingPreviewClipV2(_EditingModel):
    binding_id: str
    node_id: str
    asset_id: str | None = None
    status: CanvasNodeStatusV2
    display_order: int = Field(ge=0)
    preview_url: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    warning: str | None = None


class EditingPreviewV2(_EditingModel):
    clips: tuple[EditingPreviewClipV2, ...] = ()
    bgm_binding_id: str | None = None
    bgm_node_id: str | None = None
    bgm_asset_id: str | None = None
    estimated_duration_seconds: float = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()


EditingExportStatusV2 = Literal[
    "queued",
    "exporting",
    "completed",
    "failed",
    "cancelled",
]


class EditingExportRuntimeV2(_EditingModel):
    export_id: str
    status: EditingExportStatusV2
    manifest_revision: int = Field(ge=1)
    fingerprint: str
    ready_video_node_ids: tuple[str, ...] = ()
    skipped_inputs: tuple[EditingSkippedInputV2, ...] = ()
    bgm_node_id: str | None = None
    output_asset_id: str | None = None
    error: CanvasNodeErrorV2 | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class EditingNodeContentV2(_EditingModel):
    manifest: EditingManifestV2 = Field(default_factory=EditingManifestV2)
    dirty: bool = True
    preview: EditingPreviewV2 = Field(default_factory=EditingPreviewV2)
    last_successful_export: EditingExportRuntimeV2 | None = None
    active_export: EditingExportRuntimeV2 | None = None


class EditingExportRequestV2(_EditingModel):
    expected_manifest_revision: int = Field(ge=1)
    availability_policy: Literal["use_ready_inputs"] = "use_ready_inputs"


class EditingExportAcceptedV2(_EditingModel):
    workflow_id: str
    node_id: str
    export_id: str
    status: EditingExportStatusV2
    manifest_revision: int
    ready_video_node_ids: tuple[str, ...] = ()
    skipped_inputs: tuple[EditingSkippedInputV2, ...] = ()
    bgm_node_id: str | None = None
    events_cursor: int = Field(ge=0)


class EditingExportCancelResponseV2(_EditingModel):
    workflow_id: str
    node_id: str
    export_id: str
    status: Literal["cancelled"]
    events_cursor: int = Field(ge=0)


def default_editing_content() -> dict[str, object]:
    """Return JSON-compatible default Editing content."""

    return EditingNodeContentV2().model_dump(mode="json")
