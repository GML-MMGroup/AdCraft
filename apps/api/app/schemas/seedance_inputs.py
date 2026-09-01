"""Typed ephemeral Seedance inputs and safe durable audit projections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_canvas import CanvasInputRoleV2


class _SeedanceInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryboardPanelReferenceV1(_SeedanceInputModel):
    panel_index: int = Field(ge=1, le=9)
    shot_id: str = Field(min_length=1, max_length=256)
    beat: str = Field(min_length=1, max_length=2_048)


class StoryboardGroundingReferenceV1(_SeedanceInputModel):
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1, max_length=160)
    binding_id: str = Field(min_length=1)
    media_type: Literal["image"] = "image"
    required: bool = True
    display_order: int = Field(ge=0)


class StoryboardReferenceIdentityAuditV1(_SeedanceInputModel):
    asset_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1, max_length=160)
    binding_id: str = Field(min_length=1)
    display_order: int = Field(ge=0)
    provider_input_type: str | None = Field(default=None, min_length=1)
    omitted_payload: bool = True


class StoryboardGridGroundingPlanV1(_SeedanceInputModel):
    schema_version: Literal["storyboard_grid_grounding_plan_v1"] = (
        "storyboard_grid_grounding_plan_v1"
    )
    node_id: str = Field(min_length=1)
    grid_asset_id: str = Field(min_length=1)
    grid_version_id: str = Field(min_length=1)
    grid_checksum: str = Field(min_length=1)
    storyboard_revision: str = Field(min_length=1)
    grid_rows: Literal[3] = 3
    grid_columns: Literal[3] = 3
    panel_count: Literal[9] = 9
    panels: tuple[StoryboardPanelReferenceV1, ...] = Field(min_length=9, max_length=9)
    target_shot_id: str = Field(min_length=1, max_length=256)
    target_panel_indices: tuple[int, ...] = Field(min_length=1, max_length=9)
    ordered_references: tuple[StoryboardGroundingReferenceV1, ...] = Field(
        min_length=1, max_length=32
    )
    provider_reference_limit: int = Field(ge=1, le=64)
    prompt_snapshot_digest: str = Field(min_length=1)
    panel_sequence_fingerprint: str = Field(min_length=1)
    plan_fingerprint: str = Field(min_length=1)


class StoryboardGridGroundingAuditV1(_SeedanceInputModel):
    schema_version: Literal["storyboard_grid_grounding_audit_v1"] = (
        "storyboard_grid_grounding_audit_v1"
    )
    requested: tuple[StoryboardReferenceIdentityAuditV1, ...] = ()
    delivered: tuple[StoryboardReferenceIdentityAuditV1, ...] = ()
    serialized: tuple[StoryboardReferenceIdentityAuditV1, ...] = ()
    submitted: tuple[StoryboardReferenceIdentityAuditV1, ...] = ()
    primary_reference_asset_id: str = Field(min_length=1)
    primary_reference_version_id: str = Field(min_length=1)
    panel_count: Literal[9] = 9
    grid_rows: Literal[3] = 3
    grid_columns: Literal[3] = 3
    panel_sequence_fingerprint: str = Field(min_length=1)
    provider_request_field: str = Field(min_length=1)
    provider_input_order: tuple[str, ...] = ()
    prompt_reference_labels: tuple[str, ...] = ()
    omitted_optional_references: tuple[str, ...] = ()
    omitted_payload: bool = True

    @property
    def all_lifecycle_asset_ids(self) -> tuple[str, ...]:
        return tuple(
            item.asset_id
            for item in (*self.requested, *self.delivered, *self.serialized, *self.submitted)
        )


SeedanceMediaTypeV1 = Literal["image", "video", "audio"]
SeedanceReferencePurposeV1 = Literal["storyboard_sequence", "scene_reference"]
SeedanceProviderInputTypeV1 = Literal[
    "image_url",
    "video_url",
    "audio_url",
    "data_url",
    "provider_file_id",
    "provider_uploaded_url",
]


class SeedanceTextInputV1(_SeedanceInputModel):
    binding_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    source_node_revision: int = Field(ge=1)
    source_type: Literal["text", "script"]
    input_role: CanvasInputRoleV2
    display_order: int = Field(ge=0)
    content: str = Field(exclude=True)
    content_hash: str = Field(min_length=1)
    label: str = Field(min_length=1)


class SeedanceDeliveredMediaInputV1(_SeedanceInputModel):
    binding_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    media_type: SeedanceMediaTypeV1
    input_role: CanvasInputRoleV2
    source_semantic_role: str | None = Field(default=None, min_length=1, max_length=160)
    required: bool
    display_order: int = Field(ge=0)
    provider_input_type: SeedanceProviderInputTypeV1
    provider_input_value: str = Field(min_length=1, exclude=True, repr=False)
    checksum: str = Field(min_length=1)
    byte_count: int | None = Field(default=None, ge=0)
    reference_instruction: str | None = Field(default=None, min_length=1, max_length=512)
    reference_instruction_transport: Literal["native_slot", "provider_only"] | None = None


class SeedanceMediaInputV1(SeedanceDeliveredMediaInputV1):
    reference_purpose: SeedanceReferencePurposeV1 | None = None
    label: str = Field(min_length=1)


class SeedanceInputManifestV1(_SeedanceInputModel):
    schema_version: Literal["seedance_input_manifest_v1"] = "seedance_input_manifest_v1"
    node_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1, exclude=True)
    text_inputs: tuple[SeedanceTextInputV1, ...] = ()
    image_inputs: tuple[SeedanceMediaInputV1, ...] = ()
    video_inputs: tuple[SeedanceMediaInputV1, ...] = ()
    audio_inputs: tuple[SeedanceMediaInputV1, ...] = ()
    aspect_ratio: str = Field(min_length=1)
    resolution: str = Field(min_length=1)
    requested_duration_seconds: int = Field(ge=1)
    effective_duration_seconds: int = Field(ge=1, le=15)
    generate_audio: bool
    normalizations: tuple[str, ...] = ()

    @property
    def media_inputs(self) -> tuple[SeedanceMediaInputV1, ...]:
        return tuple(
            sorted(
                (*self.image_inputs, *self.video_inputs, *self.audio_inputs),
                key=lambda item: (item.display_order, item.binding_id),
            )
        )


class SeedanceTextInputAuditV1(_SeedanceInputModel):
    binding_id: str
    source_node_id: str
    source_node_revision: int
    source_type: Literal["text", "script"]
    input_role: CanvasInputRoleV2
    display_order: int
    content_hash: str
    label: str


class SeedanceMediaInputAuditV1(_SeedanceInputModel):
    binding_id: str
    asset_id: str
    media_type: SeedanceMediaTypeV1
    input_role: CanvasInputRoleV2
    source_semantic_role: str | None = None
    reference_purpose: SeedanceReferencePurposeV1 | None = None
    required: bool
    display_order: int
    provider_input_type: SeedanceProviderInputTypeV1
    checksum: str
    label: str
    byte_count: int | None = None


class SeedanceInputManifestAuditV1(_SeedanceInputModel):
    schema_version: Literal["seedance_input_manifest_audit_v1"] = "seedance_input_manifest_audit_v1"
    node_id: str
    model_id: str
    prompt_hash: str
    text_inputs: tuple[SeedanceTextInputAuditV1, ...] = ()
    media_inputs: tuple[SeedanceMediaInputAuditV1, ...] = ()
    input_counts: dict[Literal["text", "script", "image", "video", "audio"], int]
    aspect_ratio: str
    resolution: str
    requested_duration_seconds: int
    effective_duration_seconds: int
    generate_audio: bool
    normalizations: tuple[str, ...] = ()
