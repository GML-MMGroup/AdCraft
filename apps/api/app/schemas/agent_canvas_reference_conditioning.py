"""Frozen, bounded conditioning metadata derived from reference-style authority."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_canvas_reference_style import ReferencePromptProvenanceV1


class _ReferenceConditioningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ReferenceConditioningRoleV1 = Literal["character_main", "scene_board"]
ReferenceConditioningControlLevelV1 = Literal["native", "provider_instruction"]


class ReferenceConditioningPlanV1(_ReferenceConditioningModel):
    """A per-attempt projection of one existing reference-style policy."""

    plan_version: Literal["reference_conditioning_v1"] = "reference_conditioning_v1"
    target_role: ReferenceConditioningRoleV1
    source_policy_id: str = Field(min_length=1, max_length=160)
    source_policy_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    reference_kind: Literal["character_main", "scene_main"]
    semantic_reference_role: Literal["character_reference", "scene_reference"]
    reference_purpose: Literal["identity_guidance", "environment_guidance"]
    reference_label: Literal["Image 1"] = "Image 1"
    reference_position: Literal[1] = 1
    protected_dimensions: tuple[str, ...] = Field(min_length=1, max_length=16)
    allowed_change_dimensions: tuple[str, ...] = Field(min_length=1, max_length=8)
    explicit_override_dimensions: tuple[str, ...] = Field(default=(), max_length=16)
    reference_control_level: ReferenceConditioningControlLevelV1
    provenance: ReferencePromptProvenanceV1
    provenance_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
