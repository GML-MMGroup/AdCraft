"""Versioned advertising media contracts for Agent Canvas roles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.agent_canvas import StorageAccessDescriptorV2
from app.schemas.agent_canvas_prompt_assertion import ProviderPromptAssertionEvidenceV1


AdMediaSemanticRoleV2 = Literal[
    "creative_brief",
    "world_setting",
    "script",
    "product",
    "prop",
    "character",
    "scene",
    "storyboard_sequence",
    "storyboard_video",
    "bgm",
    "general_text",
    "general_image",
    "general_video",
    "general_audio",
    "editing",
]
SemanticReferenceRoleV2 = Literal[
    "world_setting_reference",
    "subject_reference",
    "environment_reference",
    "product_reference",
    "prop_reference",
    "style_reference",
    "style_composition_reference",
    "storyboard_visual_reference",
]


class _AdMediaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VisualStyleContractV2(_AdMediaModel):
    style_prompt: str = Field(min_length=1, max_length=8_192)
    source: Literal["user", "video_skill", "references", "platform_default"]
    negative_style_constraints: tuple[str, ...] = Field(default=(), max_length=64)


class DesignAssetContentV2(_AdMediaModel):
    asset_kind: Literal["main", "multi_view"] = "main"
    subject_identity: str = Field(min_length=1, max_length=4_096)
    design_summary: str = Field(min_length=1, max_length=8_192)
    style: VisualStyleContractV2
    explicit_inclusions: tuple[str, ...] = Field(default=(), max_length=64)
    negative_constraints: tuple[str, ...] = Field(default=(), max_length=64)


CharacterAssetKindV2 = Literal["identity_master", "turnaround"]
CharacterReferenceRenderingModeV2 = Literal["detailed_semi_realistic_illustration"]


class CharacterDesignAssetContentV2(DesignAssetContentV2):
    character_asset_kind: CharacterAssetKindV2 = "identity_master"
    reference_rendering_mode: CharacterReferenceRenderingModeV2 = (
        "detailed_semi_realistic_illustration"
    )


class SceneBoardPanelV2(_AdMediaModel):
    panel_index: int = Field(ge=1, le=9)
    view_or_zone: str = Field(min_length=1, max_length=1_024)
    spatial_description: str = Field(min_length=1, max_length=4_096)
    lighting_material_detail: str = Field(min_length=1, max_length=2_048)


class SceneDesignBoardContentV2(_AdMediaModel):
    scene_identity: str = Field(min_length=1, max_length=4_096)
    environment_summary: str = Field(min_length=1, max_length=8_192)
    layout: str = Field(min_length=1, max_length=4_096)
    lighting: str = Field(min_length=1, max_length=2_048)
    materials: str = Field(min_length=1, max_length=2_048)
    time_of_day: str = Field(min_length=1, max_length=512)
    style: VisualStyleContractV2
    panels: tuple[SceneBoardPanelV2, ...] = Field(min_length=9, max_length=9)
    explicit_entity_reference_ids: tuple[str, ...] = Field(default=(), max_length=32)
    exclude_unreferenced_entities: Literal[True] = True
    no_narrative_progression: Literal[True] = True

    @model_validator(mode="after")
    def validate_panel_sequence(self) -> "SceneDesignBoardContentV2":
        _require_panel_sequence(self.panels, "scene_design_board_contract_invalid")
        _require_distinct_panel_values(
            self.panels,
            lambda panel: (panel.view_or_zone, panel.spatial_description),
            "scene_design_board_contract_invalid",
        )
        return self


class StoryboardPanelV2(_AdMediaModel):
    panel_index: int = Field(ge=1, le=9)
    beat: str = Field(min_length=1, max_length=2_048)
    composition: str = Field(min_length=1, max_length=2_048)
    camera: str = Field(min_length=1, max_length=1_024)
    subject_action: str = Field(min_length=1, max_length=2_048)
    continuity_from_previous: str = Field(min_length=1, max_length=2_048)


class StoryboardGridContentV2(_AdMediaModel):
    sequence_summary: str = Field(min_length=1, max_length=8_192)
    narrative_goal: str = Field(min_length=1, max_length=4_096)
    style: VisualStyleContractV2
    panels: tuple[StoryboardPanelV2, ...] = Field(min_length=9, max_length=9)
    no_generated_text: Literal[True] = True

    @model_validator(mode="after")
    def validate_panel_sequence(self) -> "StoryboardGridContentV2":
        _require_panel_sequence(self.panels, "storyboard_grid_contract_invalid")
        _require_distinct_panel_values(
            self.panels,
            lambda panel: (
                panel.beat,
                panel.composition,
                panel.camera,
                panel.subject_action,
            ),
            "storyboard_grid_contract_invalid",
        )
        return self


class VideoSegmentContentV2(_AdMediaModel):
    segment_summary: str = Field(min_length=1, max_length=8_192)
    duration_seconds: float = Field(gt=0, le=3_600)
    storyboard_content: str = Field(min_length=1, max_length=16_384)
    style: VisualStyleContractV2 | None = None
    dialogue: str = Field(default="", max_length=8_192)
    voice_style: str = Field(default="", max_length=2_048)
    environment_sound: str = Field(default="", max_length=4_096)
    action_effects: str = Field(default="", max_length=4_096)
    negative_constraints: str = Field(default="", max_length=8_192)
    background_music: Literal[False] = False


class BgmContentV2(_AdMediaModel):
    music_summary: str = Field(min_length=1, max_length=8_192)
    duration_seconds: float = Field(gt=0, le=3_600)
    pace: str = Field(min_length=1, max_length=1_024)
    energy_curve: str = Field(min_length=1, max_length=2_048)
    instrumentation: str = Field(min_length=1, max_length=2_048)
    mood: str = Field(min_length=1, max_length=1_024)
    instrumental_only: Literal[True] = True
    no_vocals: Literal[True] = True


class ReferenceRequirementV2(_AdMediaModel):
    binding_kind: Literal[
        "text_context",
        "image_reference",
        "video_reference",
        "audio_reference",
    ]
    required_role: str | None = None
    minimum: int = Field(default=0, ge=0)
    maximum: int = Field(default=8, ge=1)


class AdMediaRoleContractV2(_AdMediaModel):
    semantic_role: AdMediaSemanticRoleV2
    node_type: Literal["text", "script", "image", "video", "audio", "editing"]
    output_media_type: Literal["text", "image", "video", "audio"]
    role_contract_version: Literal["ad-media-role-v2"] = "ad-media-role-v2"
    content_schema_ref: str
    output_cardinality: Literal[1] = 1
    reference_requirements: tuple[ReferenceRequirementV2, ...] = ()


class ResolvedAdReferenceV2(_AdMediaModel):
    binding_id: str
    binding_revision: int | None = Field(default=None, ge=1, exclude=True)
    source_kind: Literal["node_output", "image_asset"]
    source_node_id: str | None = None
    source_node_revision: int | None = Field(default=None, ge=1, exclude=True)
    source_sequence_id: str | None = Field(default=None, min_length=1, exclude=True)
    source_semantic_role: str | None = None
    semantic_reference_role: SemanticReferenceRoleV2 | None = None
    storyboard_reference_purpose: Literal["sequence_visual_anchor"] | None = None
    asset_id: str
    asset_version_id: str = Field(min_length=1)
    media_type: Literal["image", "video", "audio"]
    display_order: int = Field(ge=0)
    source_identity_facts: dict[str, JsonValue] = Field(default_factory=dict)
    access_descriptor: StorageAccessDescriptorV2


class AdReferenceBundleV2(_AdMediaModel):
    target_node_id: str
    references: tuple[ResolvedAdReferenceV2, ...]
    bundle_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProviderModelCapabilityV2(_AdMediaModel):
    model_id: str
    max_duration_seconds: float | None = Field(default=None, gt=0)
    supports_native_audio: bool = False
    max_reference_images: int = Field(default=8, ge=0)


class CompiledProviderPromptV2(_AdMediaModel):
    semantic_role: AdMediaSemanticRoleV2
    prompt_registry_ref: str
    prompt_registry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    render_context_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_bundle_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    style_source: Literal["user", "video_skill", "references", "platform_default"]
    prompt: str
    negative_prompt: str
    provider_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    assertion_evidence: ProviderPromptAssertionEvidenceV1 | None = None


def resolve_visual_style(
    *,
    user_style: VisualStyleContractV2 | None = None,
    video_skill_style: VisualStyleContractV2 | None = None,
    reference_style: VisualStyleContractV2 | None = None,
) -> VisualStyleContractV2:
    if user_style is not None:
        return user_style.model_copy(update={"source": "user"})
    if video_skill_style is not None:
        return video_skill_style.model_copy(update={"source": "video_skill"})
    if reference_style is not None:
        return reference_style.model_copy(update={"source": "references"})
    return VisualStyleContractV2(
        style_prompt="Detailed semi-realistic advertising illustration",
        source="platform_default",
    )


def _require_panel_sequence(panels: tuple[object, ...], error_code: str) -> None:
    if [getattr(panel, "panel_index") for panel in panels] != list(range(1, 10)):
        raise ValueError(error_code)


def _require_distinct_panel_values(
    panels: tuple[object, ...],
    signature: Callable[[object], object],
    error_code: str,
) -> None:
    values = [signature(panel) for panel in panels]
    if len(values) != len(set(values)):
        raise ValueError(error_code)
