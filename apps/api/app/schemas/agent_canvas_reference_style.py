"""Strict internal policy and provenance contracts for selected references."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _ReferenceStyleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ReferenceStyleControlLevelV1 = Literal["native", "provider_instruction"]


class ReferencePromptProvenanceV1(_ReferenceStyleModel):
    binding_id: str = Field(min_length=1, max_length=160)
    binding_revision: int = Field(ge=1)
    asset_id: str = Field(min_length=1, max_length=160)
    asset_version_id: str = Field(min_length=1, max_length=160)
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)


class ReferenceStyleAuthorityPolicyV1(_ReferenceStyleModel):
    policy_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=64)
    reference_kind: Literal["character_main", "scene_main"]
    semantic_reference_role: Literal["character_reference", "scene_reference"]
    reference_purpose: Literal["identity_guidance", "environment_guidance"]
    protected_dimensions: tuple[str, ...] = Field(min_length=1, max_length=16)
    explicit_override_dimensions: tuple[str, ...] = Field(default=(), max_length=16)
    reference_control_level: ReferenceStyleControlLevelV1
    policy_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    provenance: ReferencePromptProvenanceV1
