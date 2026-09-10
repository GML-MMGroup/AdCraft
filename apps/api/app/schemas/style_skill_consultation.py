"""Bounded public facts for read-only Style Skill consultation."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SkillId = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]*$")]


class _ConsultationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StyleSkillConsultationQueryV1(_ConsultationModel):
    scope: Literal["catalog", "current", "recommend", "compare"]
    skill_ids: tuple[SkillId, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def validate_scope(self) -> "StyleSkillConsultationQueryV1":
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("Style Skill focus IDs must be unique.")
        if self.scope == "compare":
            if not 2 <= len(self.skill_ids) <= 4:
                raise ValueError("Comparison requires two to four Style Skill IDs.")
        elif len(self.skill_ids) > 1:
            raise ValueError("This consultation scope accepts at most one focus ID.")
        return self


class StyleSkillPublicFactV1(_ConsultationModel):
    skill_id: SkillId
    version: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=2_048)
    category: str = Field(min_length=1, max_length=80)
    tags: tuple[str, ...] = Field(default=(), max_length=32)
    supported_use_cases: tuple[str, ...] = Field(default=(), max_length=32)


class StyleSkillConsultationContextV1(_ConsultationModel):
    catalog_version: str = Field(min_length=1, max_length=32)
    selected_skill_id: SkillId | None
    selected_skill_version: str | None = Field(max_length=80)
    query: StyleSkillConsultationQueryV1
    entries: tuple[StyleSkillPublicFactV1, ...] = Field(max_length=24)
    omitted_entry_count: int = Field(ge=0)
    unavailable_skill_ids: tuple[SkillId, ...] = Field(default=(), max_length=5)
    requirement_summary: str = Field(default="", max_length=4_096)

    @model_validator(mode="after")
    def validate_facts(self) -> "StyleSkillConsultationContextV1":
        if (self.selected_skill_id is None) != (self.selected_skill_version is None):
            raise ValueError("Selected Style Skill identity requires both ID and version.")
        if len({entry.skill_id for entry in self.entries}) != len(self.entries):
            raise ValueError("Public Style Skill facts must have unique IDs.")
        if len(catalog_fact_bytes(self.entries)) > 16_384:
            raise ValueError("Style Skill catalog facts exceed the byte budget.")
        return self


def catalog_fact_bytes(entries: tuple[StyleSkillPublicFactV1, ...]) -> bytes:
    return json.dumps(
        [entry.model_dump(mode="json") for entry in entries],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class StyleSkillConsultationAuditV1(_ConsultationModel):
    source_turn_id: str = Field(min_length=1, max_length=160)
    scope: Literal["catalog", "current", "recommend", "compare"]
    catalog_version: str = Field(min_length=1, max_length=32)
    selected_skill_id: SkillId | None
    selected_skill_version: str | None = Field(max_length=80)
    focused_skill_ids: tuple[SkillId, ...] = Field(default=(), max_length=4)
    omitted_entry_count: int = Field(ge=0)
