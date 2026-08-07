"""Strict contracts for Agent Canvas World Setting authoring and context."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WorldSettingContextAudienceV2 = Literal[
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


class WorldSettingAuthoringProvenanceV2(_WorldSettingModel):
    source_proposal_id: str = Field(min_length=1, max_length=160)
    source_option_id: str = Field(min_length=1, max_length=160)
    materialization_run_id: str = Field(min_length=1, max_length=160)
    style_skill_run_id: str | None = Field(default=None, max_length=160)
    creative_direction_snapshot_id: str | None = Field(default=None, max_length=160)


class WorldSettingCoreV2(_WorldSettingModel):
    premise: str = Field(min_length=1, max_length=2_048)
    era_and_place: str = Field(min_length=1, max_length=2_048)
    world_rules: tuple[_ProjectionItem, ...] = Field(min_length=1, max_length=8)
    visual_continuity: tuple[_ProjectionItem, ...] = Field(min_length=1, max_length=8)


class WorldSettingDocumentV2(_WorldSettingModel):
    document_kind: Literal["world_setting"] = "world_setting"
    contract_version: Literal["world-setting-v2"] = "world-setting-v2"
    content: str = Field(min_length=1, max_length=32_768)
    core: WorldSettingCoreV2
    authoring_provenance: WorldSettingAuthoringProvenanceV2


class WorldSettingMaterializationDraftV2(_WorldSettingModel):
    title: str = Field(min_length=1, max_length=256)
    document_content: str = Field(min_length=1, max_length=32_768)


class WorldSettingContextEnvelopeV2(_WorldSettingModel):
    context_kind: Literal["world_setting_context_v2"] = "world_setting_context_v2"
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    source_content_digest: _Digest
    source_core_digest: _Digest
    target_audience: WorldSettingContextAudienceV2
    shared_summary: str = Field(min_length=1, max_length=4_096)
    relevant_world_rules: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    relevant_visual_continuity: tuple[_ProjectionItem, ...] = Field(default=(), max_length=8)
    compiler_id: str = Field(min_length=1, max_length=160)
    compiler_digest: _Digest
    context_digest: _Digest


class WorldSettingResolvedInputV2(_WorldSettingModel):
    binding_id: str = Field(min_length=1, max_length=160)
    source_node_id: str = Field(min_length=1, max_length=160)
    source_node_revision: int = Field(ge=1)
    source_content_digest: _Digest
    source_core_digest: _Digest
    required: bool
    display_order: int = Field(ge=0)
    target_audience: WorldSettingContextAudienceV2
    compiler_id: str = Field(min_length=1, max_length=160)
    compiler_digest: _Digest
    context_digest: _Digest
    context: WorldSettingContextEnvelopeV2

    @model_validator(mode="after")
    def validate_context_identity(self) -> "WorldSettingResolvedInputV2":
        identity = (
            self.source_node_id,
            self.source_node_revision,
            self.source_content_digest,
            self.source_core_digest,
            self.target_audience,
            self.compiler_id,
            self.compiler_digest,
            self.context_digest,
        )
        context_identity = (
            self.context.source_node_id,
            self.context.source_node_revision,
            self.context.source_content_digest,
            self.context.source_core_digest,
            self.context.target_audience,
            self.context.compiler_id,
            self.context.compiler_digest,
            self.context.context_digest,
        )
        if identity != context_identity:
            raise ValueError("World Setting context identity is inconsistent.")
        return self


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
