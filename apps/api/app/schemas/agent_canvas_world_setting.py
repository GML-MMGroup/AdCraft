"""Strict contracts for Agent Canvas World Setting authoring and projections."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WorldSettingProjectionAudienceV1 = Literal[
    "shared",
    "script_writer",
    "product_designer",
    "prop_designer",
    "character_designer",
    "scene_designer",
    "storyboard_artist",
    "video_director",
    "bgm_director",
]

_ProjectionItem = Annotated[str, Field(min_length=1, max_length=1_024)]
_Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class _WorldSettingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorldSettingAuthoringProvenanceV1(_WorldSettingModel):
    source_proposal_id: str = Field(min_length=1, max_length=160)
    source_option_id: str = Field(min_length=1, max_length=160)
    materialization_run_id: str = Field(min_length=1, max_length=160)
    style_skill_run_id: str | None = Field(default=None, max_length=160)
    creative_direction_snapshot_id: str | None = Field(default=None, max_length=160)


class WorldSettingDocumentV1(_WorldSettingModel):
    document_kind: Literal["world_setting"] = "world_setting"
    contract_version: Literal["world-setting-v1"] = "world-setting-v1"
    content: str = Field(min_length=1, max_length=32_768)
    authoring_provenance: WorldSettingAuthoringProvenanceV1


class WorldSettingDirectionV1(_WorldSettingModel):
    option_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=256)
    premise: str = Field(min_length=1, max_length=2_048)
    era_and_place: str = Field(min_length=1, max_length=2_048)
    world_rules: tuple[_ProjectionItem, ...] = Field(min_length=1, max_length=8)
    visual_continuity: tuple[_ProjectionItem, ...] = Field(min_length=1, max_length=8)
    user_summary: str = Field(min_length=1, max_length=4_096)


class WorldSettingProposalDraftV1(_WorldSettingModel):
    proposal_kind: Literal["world_setting"] = "world_setting"
    specialist_name: Literal["scene_designer"] = "scene_designer"
    options: tuple[WorldSettingDirectionV1, ...] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_unique_option_ids(self) -> "WorldSettingProposalDraftV1":
        option_ids = tuple(option.option_id for option in self.options)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("World Setting option IDs must be unique.")
        return self


class SharedWorldSettingProjectionV1(_WorldSettingModel):
    premise: str = Field(min_length=1, max_length=2_048)
    era_and_location: str = Field(min_length=1, max_length=2_048)
    continuity_rules: tuple[_ProjectionItem, ...] = Field(min_length=1, max_length=8)


class ScriptWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["script_writer"] = "script_writer"
    narrative_laws: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    permitted_conflicts: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    continuity: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class ProductWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["product_designer"] = "product_designer"
    origin: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    technology: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    materials: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    status_and_use_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class PropWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["prop_designer"] = "prop_designer"
    origin: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    materials: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    availability: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    interaction_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class CharacterWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["character_designer"] = "character_designer"
    social_identity: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    wardrobe_logic: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    behavior: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    world_fit: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class SceneWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["scene_designer"] = "scene_designer"
    era_and_place: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    architecture: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    materials_and_light: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    spatial_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class StoryboardWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["storyboard_artist"] = "storyboard_artist"
    spatial_continuity: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    staging_laws: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    time_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    narrative_motion: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class VideoWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["video_director"] = "video_director"
    physical_continuity: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    motion_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    time_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    environmental_behavior: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


class BgmWorldSettingProjectionV1(_WorldSettingModel):
    audience: Literal["bgm_director"] = "bgm_director"
    era_and_culture: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    mood: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    energy: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    instrumentation_cues: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)


WorldSettingRoleProjectionV1 = Annotated[
    ScriptWorldSettingProjectionV1
    | ProductWorldSettingProjectionV1
    | PropWorldSettingProjectionV1
    | CharacterWorldSettingProjectionV1
    | SceneWorldSettingProjectionV1
    | StoryboardWorldSettingProjectionV1
    | VideoWorldSettingProjectionV1
    | BgmWorldSettingProjectionV1,
    Field(discriminator="audience"),
]


class WorldSettingReadyProjectionBundleV1(_WorldSettingModel):
    contract_version: Literal["world-setting-projection-v1"] = "world-setting-projection-v1"
    shared: SharedWorldSettingProjectionV1
    script_writer: ScriptWorldSettingProjectionV1
    product_designer: ProductWorldSettingProjectionV1
    prop_designer: PropWorldSettingProjectionV1
    character_designer: CharacterWorldSettingProjectionV1
    scene_designer: SceneWorldSettingProjectionV1
    storyboard_artist: StoryboardWorldSettingProjectionV1
    video_director: VideoWorldSettingProjectionV1
    bgm_director: BgmWorldSettingProjectionV1


class WorldSettingMaterializationDraftV1(_WorldSettingModel):
    title: str = Field(min_length=1, max_length=256)
    document_content: str = Field(min_length=1, max_length=32_768)
    projection: WorldSettingReadyProjectionBundleV1


class WorldSettingProjectionSnapshotV1(_WorldSettingModel):
    projection_snapshot_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    source_content_digest: _Digest
    projection_contract_version: Literal["world-setting-projection-v1"]
    projection_prompt_digest: _Digest
    projection_skill_digest: _Digest
    model_ref: str = Field(min_length=3, max_length=320)
    compiler_digest: _Digest
    projection_mode: Literal["ready", "fallback"]
    shared_projection: SharedWorldSettingProjectionV1
    role_projections: tuple[WorldSettingRoleProjectionV1, ...] = Field(default=(), max_length=8)
    projection_digest: _Digest
    warning_code: str | None = Field(default=None, max_length=160)
    created_at: datetime

    @model_validator(mode="after")
    def validate_projection_shape(self) -> "WorldSettingProjectionSnapshotV1":
        audiences = tuple(item.audience for item in self.role_projections)
        if len(audiences) != len(set(audiences)):
            raise ValueError("World Setting projection audiences must be unique.")
        expected = {
            "script_writer",
            "product_designer",
            "prop_designer",
            "character_designer",
            "scene_designer",
            "storyboard_artist",
            "video_director",
            "bgm_director",
        }
        if self.projection_mode == "ready" and set(audiences) != expected:
            raise ValueError("Ready World Setting projections require every role audience.")
        if self.projection_mode == "fallback" and audiences:
            raise ValueError("Fallback World Setting projections must be shared-only.")
        return self


class WorldSettingProjectionContextV1(_WorldSettingModel):
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    source_content_digest: _Digest
    projection_snapshot_id: str = Field(min_length=1, max_length=160)
    projection_digest: _Digest
    projection_mode: Literal["ready", "fallback"]
    projection_audience: WorldSettingProjectionAudienceV1
    shared: SharedWorldSettingProjectionV1
    role_projection: WorldSettingRoleProjectionV1 | None = None
    warning_code: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_projection_shape(self) -> "WorldSettingProjectionContextV1":
        if self.projection_mode == "fallback":
            if self.role_projection is not None:
                raise ValueError("Fallback World Setting context must be shared-only.")
            return self
        if self.projection_audience == "shared":
            if self.role_projection is not None:
                raise ValueError("Shared World Setting context cannot include a role projection.")
            return self
        if (
            self.role_projection is None
            or self.role_projection.audience != self.projection_audience
        ):
            raise ValueError("World Setting role projection must match its audience.")
        return self


class ResolvedWorldSettingInputV1(_WorldSettingModel):
    """Identity-only reference to one frozen World Setting projection."""

    binding_id: str = Field(min_length=1, max_length=160)
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    source_content_digest: _Digest
    required: bool
    display_order: int = Field(ge=0)
    projection_audience: WorldSettingProjectionAudienceV1
    projection_contract_version: Literal["world-setting-projection-v1"]
    projection_snapshot_id: str = Field(min_length=1, max_length=160)
    projection_digest: _Digest
    projection_mode: Literal["ready", "fallback"]
    warning_code: str | None = Field(default=None, max_length=160)
