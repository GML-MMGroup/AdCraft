from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


StoryboardDetailMaterializerMode = Literal["real", "mock", "fallback"]
StoryboardCellRole = Literal["establishing", "action", "detail", "payoff"]
StoryboardCellSlotType = Literal["shot_cell_1", "shot_cell_2", "shot_cell_3", "shot_cell_4"]


class V2StoryboardDetailInput(BaseModel):
    workflow_id: str
    shot_id: str
    shot_index: int = Field(ge=1)
    shot_summary_prompt: str
    script_shot: dict[str, Any] = Field(default_factory=dict)
    workflow_aspect_ratio: str
    desired_duration_seconds: int = Field(ge=1)
    provider_duration_seconds: Literal[5, 10]
    product_brief_summaries: list[dict[str, Any]] = Field(default_factory=list)
    character_brief_summaries: list[dict[str, Any]] = Field(default_factory=list)
    scene_brief_summaries: list[dict[str, Any]] = Field(default_factory=list)
    selected_reference_summaries: list[dict[str, Any]] = Field(default_factory=list)
    skill_context: dict[str, Any] = Field(default_factory=dict)
    prompt_profile_id: str | None = None
    previous_transition_summary: str | None = None
    previous_product_state: str | None = None
    previous_story_state: str | None = None

    @field_validator(
        "workflow_id",
        "shot_id",
        "shot_summary_prompt",
        "workflow_aspect_ratio",
        mode="after",
    )
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2StoryboardCellPromptPlan(BaseModel):
    slot_type: StoryboardCellSlotType
    cell_index: Literal[1, 2, 3, 4]
    cell_role: StoryboardCellRole
    provider_prompt: str
    negative_prompt: str | None = None
    negative_constraints: list[str] = Field(default_factory=list)
    continuity_notes: str
    required_reference_asset_ids: list[str] = Field(default_factory=list)

    @field_validator("cell_role", mode="before")
    @classmethod
    def normalize_cell_role(cls, value: Any) -> Any:
        return {
            "opening": "establishing",
            "action_buildup": "action",
            "action_peak": "detail",
        }.get(value, value)

    @field_validator("provider_prompt", "continuity_notes", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("negative_prompt", mode="after")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("negative_constraints", "required_reference_asset_ids", mode="after")
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return [item for item in [str(item).strip() for item in value] if item]


class V2StoryboardVideoTimeSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    content: str

    @field_validator("content", mode="after")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be empty")
        return value


class V2StoryboardVideoDetailPlan(BaseModel):
    provider_prompt: str
    storyboard_content: str
    dialogue: str
    audio_description: str
    voice_style: str
    video_negative_constraints: str
    time_segments: list[V2StoryboardVideoTimeSegment] = Field(min_length=1)
    desired_duration_seconds: int = Field(ge=1)
    provider_duration_seconds: Literal[5, 10]
    required_shot_cell_slot_ids: list[str] = Field(default_factory=list)
    required_shot_cell_asset_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "provider_prompt",
        "storyboard_content",
        "dialogue",
        "audio_description",
        "voice_style",
        "video_negative_constraints",
        mode="after",
    )
    @classmethod
    def strip_video_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("required_shot_cell_slot_ids", "required_shot_cell_asset_ids", mode="after")
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return [item for item in [str(item).strip() for item in value] if item]


class V2StoryboardDetailPlan(BaseModel):
    shot_id: str
    shot_index: int = Field(ge=1)
    shot_summary_prompt: str
    provider_duration_seconds: Literal[5, 10]
    desired_duration_seconds: int = Field(ge=1)
    cell_prompts: list[V2StoryboardCellPromptPlan] = Field(min_length=4, max_length=4)
    video_detail: V2StoryboardVideoDetailPlan
    reference_item_ids: list[str] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)
    materializer_mode: StoryboardDetailMaterializerMode
    model_id: str | None = None
    materializer_version: str
    quality_notes: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("shot_id", "shot_summary_prompt", "materializer_version", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value

    @field_validator("reference_item_ids", "reference_asset_ids", "quality_notes", mode="after")
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return [item for item in [str(item).strip() for item in value] if item]

    @model_validator(mode="after")
    def require_four_ordered_cells(self) -> "V2StoryboardDetailPlan":
        expected = [
            ("shot_cell_1", 1, "establishing"),
            ("shot_cell_2", 2, "action"),
            ("shot_cell_3", 3, "detail"),
            ("shot_cell_4", 4, "payoff"),
        ]
        actual = [(cell.slot_type, cell.cell_index, cell.cell_role) for cell in self.cell_prompts]
        if actual != expected:
            raise ValueError("cell_prompts must contain ordered shot_cell_1..4 roles")
        if self.video_detail.provider_duration_seconds != self.provider_duration_seconds:
            raise ValueError("video_detail provider duration must match plan provider duration")
        if self.video_detail.desired_duration_seconds != self.desired_duration_seconds:
            raise ValueError("video_detail desired duration must match plan desired duration")
        return self


class V2StoryboardDetailMaterializationRecord(BaseModel):
    """Fingerprint and lineage for the last durable shot detail preparation."""

    model_config = ConfigDict(frozen=True)

    input_fingerprint: str
    script_version_id: str
    materializer_version: str
    prompt_lineage: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["llm", "repair", "deterministic_fallback", "reused"]
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class V2StoryboardDetailQualityResult(BaseModel):
    status: Literal["passed", "failed"]
    failure_codes: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class V2StoryboardDetailRepairContext(BaseModel):
    validation_error_paths: list[str] = Field(default_factory=list)
    quality_error_code: str | None = None
    quality_error_message: str | None = None
    invalid_output: Any | None = None
