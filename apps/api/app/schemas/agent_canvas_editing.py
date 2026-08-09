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


class EditingVideoEntryV2(_EditingModel):
    binding_id: str | None = Field(default=None, min_length=1)
    asset_id: str | None = Field(default=None, min_length=1)
    enabled: bool = True
    trim_start_seconds: float = Field(default=0.0, ge=0.0)
    trim_end_seconds: float | None = Field(default=None, gt=0.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    preserve_native_audio: bool = True
    transition: Literal["cut", "fade"] = "cut"
    transition_duration_seconds: float = Field(default=0.0, ge=0.0, le=5.0)
    fit_mode: Literal["fit", "fill"] = "fill"

    @model_validator(mode="after")
    def validate_source_and_timing(self) -> "EditingVideoEntryV2":
        if (self.binding_id is None) == (self.asset_id is None):
            raise ValueError("Editing video entries require one Binding or Asset reference.")
        if self.trim_end_seconds is not None and self.trim_end_seconds <= self.trim_start_seconds:
            raise ValueError("Editing video trim end must be after trim start.")
        if self.transition == "cut" and self.transition_duration_seconds != 0:
            raise ValueError("Cut transitions cannot have a duration.")
        return self

    @property
    def source_key(self) -> tuple[str, str]:
        if self.binding_id is not None:
            return ("binding", self.binding_id)
        return ("asset", self.asset_id or "")


class EditingBgmEntryV2(_EditingModel):
    binding_id: str | None = Field(default=None, min_length=1)
    asset_id: str | None = Field(default=None, min_length=1)
    enabled: bool = True
    trim_start_seconds: float = Field(default=0.0, ge=0.0)
    trim_end_seconds: float | None = Field(default=None, gt=0.0)
    volume: float = Field(default=0.20, ge=0.0, le=1.0)
    fade_in_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    fade_out_seconds: float = Field(default=0.0, ge=0.0, le=30.0)

    @model_validator(mode="after")
    def validate_source_and_timing(self) -> "EditingBgmEntryV2":
        if (self.binding_id is None) == (self.asset_id is None):
            raise ValueError("Editing BGM requires one Binding or Asset reference.")
        if self.trim_end_seconds is not None and self.trim_end_seconds <= self.trim_start_seconds:
            raise ValueError("Editing BGM trim end must be after trim start.")
        return self

    @property
    def source_key(self) -> tuple[str, str]:
        if self.binding_id is not None:
            return ("binding", self.binding_id)
        return ("asset", self.asset_id or "")


class EditingManifestV2(_EditingModel):
    video_entries: tuple[EditingVideoEntryV2, ...] = ()
    bgm: EditingBgmEntryV2 | None = None
    output: EditingOutputSettingsV2 = Field(default_factory=EditingOutputSettingsV2)
    manifest_revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_unique_sources(self) -> "EditingManifestV2":
        source_keys = [entry.source_key for entry in self.video_entries]
        if len(set(source_keys)) != len(source_keys):
            raise ValueError("Editing video input references must be unique.")
        if self.bgm is not None and self.bgm.source_key in source_keys:
            raise ValueError("The BGM input cannot also be a video input.")
        return self


EditingSkippedReasonV2 = Literal[
    "source_not_ready",
    "source_failed",
    "source_output_unavailable",
    "source_media_invalid",
]


class EditingSkippedInputV2(_EditingModel):
    reference_id: str = Field(min_length=1)
    node_id: str | None = None
    asset_id: str | None = None
    reason: EditingSkippedReasonV2


class EditingPreviewClipV2(_EditingModel):
    reference_id: str = Field(min_length=1)
    binding_id: str | None = None
    node_id: str | None = None
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


class EditingPreparationResultV2(_EditingModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    plan_document_id: str = Field(min_length=1, max_length=160)
    editing_node_id: str = Field(min_length=1, max_length=160)
    bound_video_node_ids: tuple[str, ...] = ()
    bound_audio_node_ids: tuple[str, ...] = ()
    omitted_node_ids: tuple[str, ...] = ()
    manifest_revision: int = Field(ge=1)
    replayed: bool = False


def default_editing_content() -> dict[str, object]:
    """Return JSON-compatible default Editing content."""

    return EditingNodeContentV2().model_dump(mode="json")
