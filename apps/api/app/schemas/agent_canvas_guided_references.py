"""Strict contracts for guided reference candidate reads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReferenceCandidateScopeV2 = Literal["project", "mine", "recommended"]
ReferenceCandidateKindV2 = Literal["character_main", "scene_main"]


class _ReferenceCandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceCandidateV2(_ReferenceCandidateModel):
    """One exact, selectable image version with browser-safe projections."""

    entity_id: str | None = Field(default=None, min_length=1, max_length=160)
    member_id: str | None = Field(default=None, min_length=1, max_length=160)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    media_type: Literal["image"] = "image"
    display_name: str = Field(min_length=1, max_length=256)
    preview_url: str = Field(min_length=1, max_length=512)
    content_url: str = Field(min_length=1, max_length=512)
    reference_kind: ReferenceCandidateKindV2
    semantic_reference_role: Literal["character_reference", "scene_reference"]
    reference_purpose: Literal["identity_guidance", "environment_guidance"]
    selectable: bool = True

    @model_validator(mode="after")
    def validate_role(self) -> "ReferenceCandidateV2":
        expected = (
            ("character_reference", "identity_guidance")
            if self.reference_kind == "character_main"
            else ("scene_reference", "environment_guidance")
        )
        if (self.semantic_reference_role, self.reference_purpose) != expected:
            raise ValueError("Reference candidate role and purpose do not match its kind.")
        for field in (self.preview_url, self.content_url):
            if not field.startswith(("/api/", "https://", "http://")):
                raise ValueError("Reference candidate URLs must be browser-safe.")
        return self


class ReferenceCandidateListResponseV2(_ReferenceCandidateModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    reference_kind: ReferenceCandidateKindV2
    scope: ReferenceCandidateScopeV2
    items: tuple[ReferenceCandidateV2, ...] = Field(default=(), max_length=100)
    next_cursor: str | None = Field(default=None, max_length=512)
