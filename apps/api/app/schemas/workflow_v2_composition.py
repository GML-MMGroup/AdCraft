from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


V2FinalCompositionRenderMode = Literal["simple_sequence", "timeline_editor"]
V2BgmSettlementStatus = Literal[
    "not_requested",
    "pending",
    "available",
    "unavailable",
]


class WorkflowV2CompositionCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    render_mode: V2FinalCompositionRenderMode
    supports_timeline_controls: bool
    supports_shot_reorder: bool
    supports_bgm_volume_edit: bool


class V2FinalCompositionInputSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settled: bool
    usable_video_slot_ids: list[str] = Field(default_factory=list)
    unavailable_video_slot_ids: list[str] = Field(default_factory=list)
    pending_slot_ids: list[str] = Field(default_factory=list)
    permanently_blocked_slot_ids: list[str] = Field(default_factory=list)
    bgm_status: V2BgmSettlementStatus = "not_requested"
    bgm_slot_id: str | None = None


class V2SimpleCompositionVideoSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str
    item_id: str
    slot_id: str
    shot_index: int
    asset_id: str
    version_id: str
    reused_previous_selection: bool = False


class V2SimpleCompositionBgmSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    asset_id: str
    version_id: str
    reused_previous_selection: bool = False


class V2SimpleCompositionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    render_mode: Literal["simple_sequence"] = "simple_sequence"
    workflow_id: str
    videos: list[V2SimpleCompositionVideoSource]
    bgm: V2SimpleCompositionBgmSource | None = None
    missing_shot_ids: list[str] = Field(default_factory=list)
    unavailable_video_slot_ids: list[str] = Field(default_factory=list)
    bgm_status: V2BgmSettlementStatus
    created_from_execution_id: str | None = None
