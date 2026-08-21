"""Strict contracts for the closed Agent Canvas role-reference matrix."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RoleReferenceTargetV1 = Literal[
    "product_multiview",
    "character_turnaround",
    "storyboard_grid_1",
    "storyboard_grid_n",
    "storyboard_video",
    "bgm",
    "editing",
]
RoleReferenceSourceRoleV1 = Literal[
    "product_main",
    "character_main",
    "character_turnaround",
    "scene_board",
    "storyboard_grid_1",
    "storyboard_grid",
    "product_multiview",
    "prop",
    "video_segment",
    "bgm",
]
ReferenceMediaKindV1 = Literal["image", "video", "audio"]


class _RoleReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleReferenceRuleV1(_RoleReferenceModel):
    source_role: RoleReferenceSourceRoleV1
    media_kind: ReferenceMediaKindV1
    minimum: int = Field(ge=0, le=64)
    maximum: int = Field(ge=1, le=64)
    required: bool
    required_when_active: bool = False
    default_included: bool
    canonical_order: int = Field(ge=0, le=64)

    @model_validator(mode="after")
    def validate_cardinality(self) -> "RoleReferenceRuleV1":
        if self.minimum > self.maximum:
            raise ValueError("Role reference minimum cannot exceed maximum.")
        if self.required and self.minimum == 0:
            raise ValueError("Required role references need a positive minimum.")
        return self


class RoleReferencePolicyV1(_RoleReferenceModel):
    policy_version: Literal["agent_canvas_role_reference_policy_v1"]
    target_role: RoleReferenceTargetV1
    sources: tuple[RoleReferenceRuleV1, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def validate_sources(self) -> "RoleReferencePolicyV1":
        roles = tuple(item.source_role for item in self.sources)
        if len(roles) != len(set(roles)):
            raise ValueError("Role reference sources must be unique.")
        orders = tuple(item.canonical_order for item in self.sources)
        if orders != tuple(sorted(orders)):
            raise ValueError("Role reference sources must use canonical order.")
        return self

    @property
    def allowed_source_roles(self) -> tuple[RoleReferenceSourceRoleV1, ...]:
        return tuple(item.source_role for item in self.sources)

    def rule_for(self, source_role: str) -> RoleReferenceRuleV1 | None:
        return next((item for item in self.sources if item.source_role == source_role), None)
