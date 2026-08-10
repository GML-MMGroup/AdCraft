"""Strict contracts for selected Agent Canvas capability Materialization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas_ad_media import (
    BgmContentV2,
    CharacterDesignAssetContentV2,
    DesignAssetContentV2,
    SceneDesignBoardContentV2,
    StoryboardGridContentV2,
    VideoSegmentContentV2,
)
from app.schemas.agent_canvas_capability_identity import CapabilityIdV1
from app.schemas.agent_canvas_draft_seeds import DraftSeedCapabilityIdV1
from app.schemas.agent_canvas_creative_session import (
    ProposedDraftReferenceV2,
    ScriptDraftContentV2,
)
from app.schemas.agent_canvas_world_setting import WorldSettingCoreV2
from app.schemas.agent_canvas_video_parameters import CanvasParameterProvenanceV2


class _MaterializationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SelectedConceptOptionV1(_MaterializationModel):
    option_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=256)
    public_summary: str = Field(min_length=1, max_length=8_192)
    key_decisions: tuple[Annotated[str, Field(min_length=1, max_length=1_024)], ...] = Field(
        min_length=1, max_length=6
    )


class ProposalReferenceSnapshotV1(_MaterializationModel):
    source_kind: Literal["node", "image_asset"]
    source_id: str = Field(min_length=1, max_length=160)
    source_revision: int | None = Field(default=None, ge=1)
    asset_version_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_version_identity(self) -> "ProposalReferenceSnapshotV1":
        if self.source_kind == "node" and self.source_revision is None:
            raise ValueError("Node reference snapshots require a source revision.")
        if self.source_kind == "image_asset" and self.asset_version_id is None:
            raise ValueError("Asset reference snapshots require a version identity.")
        return self


class ProposalReferencePlanV1(_MaterializationModel):
    plan_id: str = Field(min_length=1, max_length=160)
    references: tuple[ProposedDraftReferenceV2, ...] = Field(default=(), max_length=64)
    source_snapshots: tuple[ProposalReferenceSnapshotV1, ...] = Field(default=(), max_length=64)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class CapabilityMaterializationEnvelopeV1(_MaterializationModel):
    schema_version: Literal["1"] = "1"
    envelope_id: str = Field(min_length=1, max_length=160)
    materialization_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    proposal_revision: int = Field(ge=1)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    action_turn_id: str = Field(min_length=1, max_length=160)
    action: Literal["select_option", "delegate_choice", "reuse_direction"]
    selection_actor: Literal["user", "agent"]
    selection_reason: str | None = Field(default=None, max_length=2_048)
    capability_id: CapabilityIdV1
    selected_option: SelectedConceptOptionV1
    reference_plan: ProposalReferencePlanV1
    expected_session_revision: int = Field(ge=1)
    target_node_id: str | None = Field(default=None, max_length=160)
    target_node_revision: int | None = Field(default=None, ge=1)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    style_skill_run_id: str | None = Field(default=None, max_length=160)
    result_contract_name: str = Field(min_length=1, max_length=160)
    attempt_no: int = Field(ge=1)
    agent_request_identity: str = Field(min_length=1, max_length=256)
    created_at: datetime

    @model_validator(mode="after")
    def validate_target_revision_pair(self) -> "CapabilityMaterializationEnvelopeV1":
        if (self.target_node_id is None) != (self.target_node_revision is None):
            raise ValueError("Targeted Materialization requires node ID and revision.")
        return self


class ProposalPublicationEnvelopeV1(_MaterializationModel):
    schema_version: Literal["1"] = "1"
    envelope_id: str = Field(min_length=1, max_length=160)
    materialization_id: str = Field(min_length=1, max_length=160)
    proposal_id: str = Field(min_length=1, max_length=160)
    proposal_revision: int = Field(ge=1)
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    action_turn_id: str = Field(min_length=1, max_length=160)
    action: Literal["select_option", "delegate_choice", "reuse_direction"]
    selection_actor: Literal["user", "agent"]
    selection_reason: str | None = Field(default=None, max_length=2_048)
    capability_id: DraftSeedCapabilityIdV1
    selected_option: SelectedConceptOptionV1
    draft_seed_schema: Literal["draft_seed_v1"] | None = None
    draft_seed_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reference_plan: ProposalReferencePlanV1
    expected_session_revision: int = Field(ge=1)
    target_node_id: str | None = Field(default=None, max_length=160)
    target_node_revision: int | None = Field(default=None, ge=1)
    context_snapshot_id: str = Field(min_length=1, max_length=160)
    context_snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    style_skill_run_id: str | None = Field(default=None, max_length=160)
    attempt_no: int = Field(ge=1)
    idempotency_identity: str = Field(min_length=1, max_length=256)
    created_at: datetime

    @model_validator(mode="after")
    def validate_publication_identity(self) -> "ProposalPublicationEnvelopeV1":
        if (self.target_node_id is None) != (self.target_node_revision is None):
            raise ValueError("Targeted Proposal publication requires node ID and revision.")
        if (self.draft_seed_schema is None) != (self.draft_seed_digest is None):
            raise ValueError("Proposal publication Seed metadata must be complete.")
        return self


ProposalApplicationEnvelopeV1: TypeAlias = (
    CapabilityMaterializationEnvelopeV1 | ProposalPublicationEnvelopeV1
)


class CapabilityMaterializationContextV1(_MaterializationModel):
    context_kind: Literal["capability_materialization"] = "capability_materialization"
    workflow_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    capability_id: CapabilityIdV1
    selected_option: SelectedConceptOptionV1
    creative_goal: str = Field(min_length=1, max_length=4_096)
    explicit_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    shared_summary: str = Field(default="", max_length=8_192)
    capability_facts: dict[str, JsonValue] = Field(default_factory=dict)
    world_setting_excerpt: str | None = Field(default=None, max_length=8_192)
    reference_summaries: tuple[dict[str, JsonValue], ...] = Field(default=(), max_length=64)
    style_projection: dict[str, JsonValue] = Field(default_factory=dict)
    target_node_summary: dict[str, JsonValue] | None = None
    repair_error: str | None = Field(default=None, max_length=160)


class CapabilityMaterializationExecutionResultV1(_MaterializationModel):
    materialization_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(min_length=1, max_length=160)
    repaired: bool = False


class WorldSettingMaterializationContentV1(_MaterializationModel):
    content: str = Field(min_length=1, max_length=32_768)
    core: WorldSettingCoreV2


class QuickMediaMaterializationContentV1(_MaterializationModel):
    media_type: Literal["image", "video", "audio"]
    content_summary: str = Field(min_length=1, max_length=8_192)


class _MaterializationResultBaseV1(_MaterializationModel):
    title: str = Field(min_length=1, max_length=256)
    summary_prompt: str = Field(min_length=1, max_length=8_192)


class WorldSettingMaterializationResultV1(_MaterializationResultBaseV1):
    structured_content: WorldSettingMaterializationContentV1


class ScriptMaterializationResultV1(_MaterializationResultBaseV1):
    structured_content: ScriptDraftContentV2


class ProductMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: DesignAssetContentV2


class PropMaterializationResultV1(ProductMaterializationResultV1):
    pass


class CharacterMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: CharacterDesignAssetContentV2


class SceneMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: SceneDesignBoardContentV2


class StoryboardMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: StoryboardGridContentV2


class VideoMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: VideoSegmentContentV2


class BgmMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: BgmContentV2


class QuickMediaMaterializationResultV1(_MaterializationResultBaseV1):
    generation_prompt: str = Field(min_length=1, max_length=32_768)
    structured_content: QuickMediaMaterializationContentV1


CapabilityMaterializationResultV1: TypeAlias = (
    WorldSettingMaterializationResultV1
    | ScriptMaterializationResultV1
    | ProductMaterializationResultV1
    | PropMaterializationResultV1
    | CharacterMaterializationResultV1
    | SceneMaterializationResultV1
    | StoryboardMaterializationResultV1
    | VideoMaterializationResultV1
    | BgmMaterializationResultV1
    | QuickMediaMaterializationResultV1
)


CAPABILITY_MATERIALIZATION_RESULT_CONTRACTS: dict[
    CapabilityIdV1, type[_MaterializationResultBaseV1]
] = {
    "world_setting": WorldSettingMaterializationResultV1,
    "product_design": ProductMaterializationResultV1,
    "prop_design": PropMaterializationResultV1,
    "character_design": CharacterMaterializationResultV1,
    "scene_design": SceneMaterializationResultV1,
    "script_authoring": ScriptMaterializationResultV1,
    "storyboard_design": StoryboardMaterializationResultV1,
    "video_direction": VideoMaterializationResultV1,
    "bgm_direction": BgmMaterializationResultV1,
    "quick_media": QuickMediaMaterializationResultV1,
}


class MaterializationNormalizationV1(_MaterializationModel):
    result: CapabilityMaterializationResultV1
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    parameter_provenance: dict[str, CanvasParameterProvenanceV2] = Field(default_factory=dict)
    mode: Literal["model", "repaired", "deterministic_fallback"]
    warnings: tuple[str, ...] = Field(default=(), max_length=32)
