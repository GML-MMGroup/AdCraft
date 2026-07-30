"""Public Agent Canvas Video Skill catalog contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _VideoSkillPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoSkillPreviewV2(_VideoSkillPublicModel):
    kind: Literal["none", "image", "video"]
    summary: str | None = Field(default=None, max_length=1_024)
    media_url: str | None = Field(default=None, max_length=2_048)


class VideoSkillPublicDetailV2(_VideoSkillPublicModel):
    skill_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=2_048)
    category: str = Field(min_length=1, max_length=80)
    tags: tuple[str, ...] = Field(default=(), max_length=32)
    supported_use_cases: tuple[str, ...] = Field(default=(), max_length=32)
    preview: VideoSkillPreviewV2 | None = None


class VideoSkillSummaryListV2(_VideoSkillPublicModel):
    items: tuple[VideoSkillPublicDetailV2, ...]
    next_cursor: str | None = None
