"""Strict Quick Media Pi prompt contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class V2QuickMediaPromptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_media_type: Literal["image", "video", "audio"]
    summary_prompt: str = Field(min_length=1, max_length=4_096)
    provider_prompt: str = Field(min_length=1, max_length=16_384)
    negative_prompt: str | None = Field(default=None, max_length=8_192)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=128)
    quality_notes: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[dict[str, str]] = Field(default_factory=list, max_length=64)
    agent_name: Literal["video_agent"] = "video_agent"
    operation: Literal["free_image", "free_video", "free_audio"]

    @field_validator("summary_prompt", "provider_prompt")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("negative_prompt")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("reference_asset_ids", "quality_notes")
    @classmethod
    def clean_text_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @model_validator(mode="after")
    def operation_matches_media_type(self) -> "V2QuickMediaPromptPlan":
        if self.operation != f"free_{self.output_media_type}":
            raise ValueError("Quick Media operation must match output_media_type")
        return self
