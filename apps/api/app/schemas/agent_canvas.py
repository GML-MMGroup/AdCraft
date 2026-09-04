"""Strict public and internal contracts for the Agent Canvas V1 model."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.schemas.agent_canvas_errors import CanvasNodeErrorV2
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.agent_canvas_role_prompt_preparation import EditablePromptProjectionV1
from app.schemas.agent_canvas_video_parameters import CanvasParameterProvenanceV2
from app.schemas.agent_canvas_world_setting import WorldSettingResolvedInputV2


CanvasNodeTypeV2 = Literal["text", "script", "image", "video", "audio", "editing"]
CanvasNodeStatusV2 = Literal["draft", "working", "ready", "failed"]
CanvasNodeExecutionModeV2 = Literal["generative", "source_only"]
RoleContractVersionV2 = Literal["ad-media-role-v1", "ad-media-role-v2"]
ModelSelectionModeV1 = Literal["default", "explicit"]
CanvasCreativeRoleV2 = Literal[
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
CanvasBindingInputRoleV2 = Literal[
    "text_context",
    "image_reference",
    "video_reference",
    "audio_reference",
]
CanvasInputRoleV2 = CanvasBindingInputRoleV2
CanvasBindingKindV2 = CanvasBindingInputRoleV2
ProjectAssetMediaTypeV2 = Literal["image", "video", "audio"]
ProjectAssetSourceTypeV2 = Literal[
    "upload",
    "generated",
    "recommended",
    "derived",
    "library",
    "editing_export",
]
ImageLibraryCategoryV2 = Literal["character", "scene", "prop"]


class _AgentCanvasModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanvasPositionV2(_AgentCanvasModel):
    x: float
    y: float


class CanvasModelSummaryV2(_AgentCanvasModel):
    model_ref: str = Field(min_length=3, max_length=320)
    provider_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=256)
    capability: Literal["text", "image", "video", "audio"]
    availability: Literal["available", "unavailable", "unauthorized", "unsupported", "deprecated"]
    unavailable_reason: str | None = None
    catalog_revision: int = Field(ge=1)


def _validate_model_selection(mode: str | None, model_ref: str | None) -> None:
    if (mode == "default" and model_ref is not None) or (mode == "explicit" and not model_ref):
        raise ValueError("model_selection_invalid")


class CanvasNodeCreateRequestV2(_AgentCanvasModel):
    node_type: CanvasNodeTypeV2
    creative_role: CanvasCreativeRoleV2
    role_contract_version: RoleContractVersionV2 = "ad-media-role-v2"
    title: str = Field(min_length=1)
    summary_prompt: str | None = None
    generation_prompt: str | None = None
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    model_selection_mode: ModelSelectionModeV1 = "default"
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    position: CanvasPositionV2
    source_asset_id: str | None = None

    @property
    def semantic_role(self) -> CanvasCreativeRoleV2:
        """Internal transition accessor; public JSON uses creative_role only."""

        return self.creative_role

    @model_validator(mode="after")
    def validate_model_selection(self) -> "CanvasNodeCreateRequestV2":
        _validate_model_selection(self.model_selection_mode, self.model_ref)
        return self


class CanvasNodePatchRequestV2(_AgentCanvasModel):
    title: str | None = Field(default=None, min_length=1)
    summary_prompt: str | None = None
    generation_prompt: str | None = None
    structured_content: dict[str, JsonValue] | None = None
    model_selection_mode: ModelSelectionModeV1 | None = None
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    parameters: dict[str, JsonValue] | None = None
    position: CanvasPositionV2 | None = Field(default=None, deprecated=True)

    @model_validator(mode="after")
    def validate_model_selection(self) -> "CanvasNodePatchRequestV2":
        selected_fields = self.model_fields_set
        if "model_selection_mode" not in selected_fields and "model_ref" not in selected_fields:
            return self
        _validate_model_selection(self.model_selection_mode, self.model_ref)
        return self


class ProjectCreateRequestV2(_AgentCanvasModel):
    name: str = Field(min_length=1)
    description: str = ""
    video_skill_id: str | None = None
    video_skill_version: str | None = None


class CanvasLayoutPositionV2(CanvasPositionV2):
    node_id: str = Field(min_length=1)


class CanvasLayoutPatchRequestV2(_AgentCanvasModel):
    expected_layout_revision: int = Field(ge=1)
    positions: tuple[CanvasLayoutPositionV2, ...] = Field(
        min_length=1,
        max_length=200,
    )

    @model_validator(mode="after")
    def validate_unique_nodes(self) -> "CanvasLayoutPatchRequestV2":
        node_ids = [position.node_id for position in self.positions]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Layout positions contain a duplicate node ID.")
        return self


class CanvasLayoutPatchResponseV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    layout_revision: int = Field(ge=1)
    positions: tuple[CanvasLayoutPositionV2, ...]


class CanvasNodeLatestAttemptV2(_AgentCanvasModel):
    execution_id: str = Field(min_length=1, max_length=160)
    member_id: str = Field(min_length=1, max_length=160)
    run_intent_snapshot_id: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal[
        "queued",
        "waiting",
        "blocked",
        "skipped_dependency",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ]
    created_at: datetime
    updated_at: datetime
    error: CanvasNodeErrorV2 | None = None


class CanvasNodeV2(_AgentCanvasModel):
    node_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    node_type: CanvasNodeTypeV2
    creative_role: CanvasCreativeRoleV2
    role_contract_version: RoleContractVersionV2 = "ad-media-role-v2"
    title: str = Field(min_length=1)
    status: CanvasNodeStatusV2
    execution_mode: CanvasNodeExecutionModeV2 = "generative"
    summary_prompt: str | None = None
    generation_prompt: str | None = None
    prompt_presentation: EditablePromptProjectionV1 | None = None
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    model_selection_mode: ModelSelectionModeV1 = "default"
    model_ref: str | None = Field(default=None, min_length=3, max_length=320)
    model_summary: CanvasModelSummaryV2 | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    parameter_provenance: dict[str, CanvasParameterProvenanceV2] = Field(default_factory=dict)
    prompt_context_snapshot_id: str | None = None
    output_asset_id: str | None = None
    output_asset_version_id: str | None = None
    latest_attempt: CanvasNodeLatestAttemptV2 | None = None
    position: CanvasPositionV2
    revision: int = Field(ge=1)
    error: CanvasNodeErrorV2 | None = None
    prompt_preparation: NodePromptPreparationV1 = Field(
        default_factory=NodePromptPreparationV1.legacy_ready
    )
    created_at: datetime
    updated_at: datetime

    @property
    def semantic_role(self) -> CanvasCreativeRoleV2:
        """Internal transition accessor; public JSON uses creative_role only."""

        return self.creative_role

    @model_validator(mode="after")
    def validate_model_selection(self) -> "CanvasNodeV2":
        _validate_model_selection(self.model_selection_mode, self.model_ref)
        return self

    @model_validator(mode="after")
    def validate_ready_output(self) -> "CanvasNodeV2":
        if (
            self.status == "ready"
            and self.node_type in {"image", "video", "audio", "editing"}
            and self.output_asset_id is None
        ):
            raise ValueError("Ready media nodes require an output asset.")
        return self


class CanvasBindingSourceNodeV2(_AgentCanvasModel):
    kind: Literal["node_output"] = "node_output"
    source_node_id: str = Field(min_length=1)

    @property
    def node_id(self) -> str:
        return self.source_node_id


class CanvasBindingSourceImageAssetV2(_AgentCanvasModel):
    kind: Literal["image_asset"] = "image_asset"
    source_asset_id: str = Field(min_length=1)
    source_asset_version_id: str | None = Field(default=None, min_length=1)

    @property
    def asset_id(self) -> str:
        return self.source_asset_id


CanvasBindingSourceV2 = Annotated[
    CanvasBindingSourceNodeV2 | CanvasBindingSourceImageAssetV2,
    Field(discriminator="kind"),
]


class CanvasBindingCreateRequestV2(_AgentCanvasModel):
    source: CanvasBindingSourceV2
    target_node_id: str = Field(min_length=1)
    input_role: CanvasBindingInputRoleV2
    enabled: bool = True
    order: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=160)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CanvasBindingV2(_AgentCanvasModel):
    binding_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    source: CanvasBindingSourceV2
    target_node_id: str = Field(min_length=1)
    input_role: CanvasBindingInputRoleV2
    enabled: bool = True
    order: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=160)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @property
    def binding_kind(self) -> CanvasBindingInputRoleV2:
        return self.input_role

    @property
    def display_order(self) -> int:
        return self.order


class CanvasBindingPatchRequestV2(_AgentCanvasModel):
    input_role: CanvasBindingInputRoleV2 | None = None
    enabled: bool | None = None
    order: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=160)
    metadata: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "CanvasBindingPatchRequestV2":
        if (
            self.input_role is None
            and self.enabled is None
            and self.order is None
            and self.label is None
            and self.metadata is None
        ):
            raise ValueError("Binding patch must include at least one change.")
        return self


class CanvasConnectionRoleRuleV2(_AgentCanvasModel):
    source_node_type: CanvasNodeTypeV2
    target_node_type: CanvasNodeTypeV2
    roles: tuple[CanvasInputRoleV2, ...]
    default_role: CanvasInputRoleV2


class CanvasConnectionPolicyV2(_AgentCanvasModel):
    policy_version: Literal["agent_canvas_connection_policy_v1"]
    target_node_types: dict[CanvasNodeTypeV2, tuple[CanvasNodeTypeV2, ...]]
    input_roles: tuple[CanvasConnectionRoleRuleV2, ...]
    image_asset_targets: dict[CanvasNodeTypeV2, tuple[CanvasInputRoleV2, ...]]
    binding_kind_by_source_type: dict[CanvasNodeTypeV2, CanvasBindingKindV2]
    model_validation: dict[str, str]


class CanvasConnectionDecisionV2(_AgentCanvasModel):
    accepted: bool
    error_code: str | None = None
    source_node_type: CanvasNodeTypeV2
    target_node_type: CanvasNodeTypeV2
    input_role: CanvasInputRoleV2 | None = None
    allowed_roles: tuple[CanvasInputRoleV2, ...] = ()
    binding_kind: CanvasBindingKindV2 | None = None
    input_type: Literal["text", "image", "video", "audio"] | None = None


class CanvasConnectedNodeBindingRequestV2(_AgentCanvasModel):
    input_role: CanvasBindingInputRoleV2
    order: int | None = Field(default=None, ge=0)


class CanvasConnectedNodeCreateRequestV2(_AgentCanvasModel):
    anchor_node_id: str = Field(min_length=1)
    direction: Literal["upstream", "downstream"]
    node: CanvasNodeCreateRequestV2
    binding: CanvasConnectedNodeBindingRequestV2


class CanvasConnectedNodeCreateResponseV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    layout_revision: int = Field(ge=1)
    node: CanvasNodeV2
    binding: CanvasBindingV2
    events_cursor: int = Field(ge=0)


class CanvasBindingMutationResponseV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    binding: CanvasBindingV2
    incoming_bindings: tuple[CanvasBindingV2, ...]
    events_cursor: int = Field(ge=0)


class ProjectAssetV2(_AgentCanvasModel):
    asset_id: str = Field(min_length=1)
    version_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    workflow_id: str | None = Field(default=None, min_length=1)
    media_type: ProjectAssetMediaTypeV2
    source_type: ProjectAssetSourceTypeV2
    semantic_type: str | None = Field(default=None, max_length=160)
    display_name: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    status: Literal["ready", "unavailable"]
    size_bytes: int = Field(default=0, ge=0)
    storage_key: str | None = None
    preview_url: str | None = None
    media_url: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    checksum: str = Field(min_length=1)
    source_semantic_role: str | None = Field(default=None, min_length=1, max_length=160)
    source_node_id: str | None = None
    source_execution_id: str | None = None
    provider: str | None = None
    model_id: str | None = None
    prompt_provenance: dict[str, JsonValue] = Field(default_factory=dict)
    actual_media_facts: dict[str, JsonValue] = Field(default_factory=dict)
    generation_provenance: dict[str, JsonValue] = Field(default_factory=dict)
    quality_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None

    @field_validator("preview_url", "media_url")
    @classmethod
    def validate_browser_safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith(("/api/", "https://", "http://")):
            return value
        raise ValueError("Asset URLs must be browser-safe.")


ProjectAssetSummaryV2 = ProjectAssetV2


class AgentTargetRefV2(_AgentCanvasModel):
    kind: Literal["node", "image_asset"]
    target_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    node_type: CanvasNodeTypeV2 | None = None
    creative_role: CanvasCreativeRoleV2 | None = None
    media_type: ProjectAssetMediaTypeV2 | None = None
    asset_version_id: str | None = Field(default=None, min_length=1)


class AgentTargetResolutionV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    target: AgentTargetRefV2


class ActiveStyleSkillSummaryV2(_AgentCanvasModel):
    skill_run_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    category: str = Field(min_length=1)
    creative_direction_snapshot_id: str = Field(min_length=1)


class AgentCanvasWorkflowV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    workflow_schema_version: Literal[2] = 2
    canvas_model: Literal["agent_canvas_v1"] = "agent_canvas_v1"
    revision: int = Field(ge=1)
    layout_revision: int = Field(default=1, ge=1)
    nodes: tuple[CanvasNodeV2, ...] = ()
    bindings: tuple[CanvasBindingV2, ...] = ()
    assets: tuple[ProjectAssetSummaryV2, ...] = ()
    active_style_skill: ActiveStyleSkillSummaryV2 | None = None


class ProjectCreateResponseV2(AgentCanvasWorkflowV2):
    active_style_skill_run_id: str = Field(min_length=1)
    guidance_session_id: str | None = None


class CanvasMutationResponseV2(_AgentCanvasModel):
    workflow: AgentCanvasWorkflowV2
    node: CanvasNodeV2 | None = None
    binding: CanvasBindingV2 | None = None


class ProjectAssetListResponseV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    assets: tuple[ProjectAssetSummaryV2, ...] = ()


class ImageLibraryListResponseV2(_AgentCanvasModel):
    items: tuple[dict[str, JsonValue], ...] = ()


class StorageAccessDescriptorV2(_AgentCanvasModel):
    descriptor_type: Literal["asset_content"] = "asset_content"
    asset_id: str = Field(min_length=1)
    media_url: str = Field(min_length=1)
    checksum: str = Field(min_length=1)

    @field_validator("media_url")
    @classmethod
    def validate_media_url(cls, value: str) -> str:
        if value.startswith(("/api/", "https://", "http://")):
            return value
        raise ValueError("Media access must use a browser-safe asset URL.")


class ResolvedTextInputSnapshotV2(_AgentCanvasModel):
    snapshot_type: Literal["text"] = "text"
    source_kind: Literal["node_output"] = "node_output"
    source_node_id: str = Field(min_length=1)
    source_node_revision: int = Field(ge=1)
    binding_kind: Literal["text_context"] = "text_context"
    document_kind: Literal["text", "script"]
    content: str
    content_hash: str = Field(min_length=1)
    source_semantic_role: str | None = Field(default=None, min_length=1, max_length=160)
    binding_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    source_structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    binding_id: str | None = None
    input_role: Literal["text_context"] = "text_context"
    display_order: int = Field(default=0, ge=0)


class ResolvedMediaInputSnapshotV2(_AgentCanvasModel):
    snapshot_type: Literal["media"] = "media"
    source_kind: Literal["node_output", "image_asset"]
    source_node_id: str | None = None
    source_node_revision: int | None = Field(default=None, ge=1)
    binding_kind: Literal["image_reference", "video_reference", "audio_reference"]
    source_semantic_role: str | None = Field(default=None, min_length=1, max_length=160)
    binding_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    source_structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    asset_id: str = Field(min_length=1)
    asset_version_id: str | None = Field(default=None, min_length=1)
    media_type: ProjectAssetMediaTypeV2
    asset_checksum: str = Field(min_length=1)
    access_descriptor: StorageAccessDescriptorV2
    binding_id: str | None = None
    input_role: CanvasBindingInputRoleV2
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ResolvedMediaInputSnapshotV2":
        if self.source_kind == "node_output":
            if self.source_node_id is None or self.source_node_revision is None:
                raise ValueError("Node media snapshots require source node identity.")
        elif self.source_node_id is not None or self.source_node_revision is not None:
            raise ValueError("Image asset snapshots cannot include a source node.")
        return self


class ResolvedTextBindingInputV2(_AgentCanvasModel):
    binding_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    source_node_revision: int = Field(ge=1)
    input_role: Literal["text_context"] = "text_context"
    display_order: int = Field(default=0, ge=0)

    snapshot_id: str = Field(min_length=1)
    document_kind: Literal["text", "script"]
    content_digest: str = Field(min_length=1)
    content: str
    source_semantic_role: str | None = Field(default=None, min_length=1, max_length=160)
    binding_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    source_structured_content: dict[str, JsonValue] = Field(default_factory=dict)


class ResolvedMediaBindingInputV2(_AgentCanvasModel):
    binding_id: str = Field(min_length=1)
    source_kind: Literal["node_output", "image_asset"]
    source_node_id: str | None = None
    source_node_revision: int | None = Field(default=None, ge=1)
    input_role: Literal["image_reference", "video_reference", "audio_reference"]
    source_semantic_role: str | None = Field(default=None, min_length=1, max_length=160)
    binding_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    source_structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    display_order: int = Field(default=0, ge=0)
    asset_id: str = Field(min_length=1)
    asset_version_id: str | None = Field(default=None, min_length=1)
    media_type: ProjectAssetMediaTypeV2
    checksum: str = Field(min_length=1)


class OmittedOptionalInputV2(_AgentCanvasModel):
    binding_id: str = Field(min_length=1)
    source_node_id: str | None = None
    reason_code: Literal["omitted_no_output"]


class ResolvedNodeInputManifestV2(_AgentCanvasModel):
    manifest_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    node_run_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    workflow_revision: int = Field(ge=1)
    text_inputs: tuple[ResolvedTextBindingInputV2, ...] = ()
    world_setting_inputs: tuple[WorldSettingResolvedInputV2, ...] = ()
    media_inputs: tuple[ResolvedMediaBindingInputV2, ...] = ()
    omitted_optional_inputs: tuple[OmittedOptionalInputV2, ...] = ()
    run_intent_snapshot_id: str | None = Field(default=None, min_length=1)
    manifest_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    delivered_asset_version_ids: tuple[str, ...] = ()
    created_at: datetime


ResolvedInputSnapshotV2 = Annotated[
    ResolvedTextInputSnapshotV2 | ResolvedMediaInputSnapshotV2,
    Field(discriminator="snapshot_type"),
]


class ProjectAssetUploadMetadataV2(_AgentCanvasModel):
    media_type: ProjectAssetMediaTypeV2
    title: str = Field(min_length=1)
    semantic_role: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ProjectAssetUploadResponseV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    asset: ProjectAssetSummaryV2
    pending_handoff_id: str | None = Field(default=None, min_length=1)


class SaveImageToLibraryRequestV2(_AgentCanvasModel):
    category: ImageLibraryCategoryV2
    display_name: str = Field(min_length=1)


class AgentCanvasDocumentRecordV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    document_kind: Literal["text", "script", "editing_manifest"]
    content: dict[str, JsonValue]
    content_hash: str = Field(min_length=1)
    node_revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class AgentCanvasPromptContextSnapshotV2(_AgentCanvasModel):
    snapshot_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    inputs: tuple[ResolvedTextInputSnapshotV2, ...]
    turn_id: str | None = None
    role: str | None = None
    operation: str | None = None
    target_asset_ids: tuple[str, ...] = ()
    binding_ids: tuple[str, ...] = ()
    creative_direction_snapshot_id: str | None = None
    skill_refs: tuple[dict[str, str], ...] = ()
    memory_digest: str | None = None
    upstream_summary_digest: str | None = None
    requirement_revision_id: str | None = None
    requirement_revision_no: int | None = Field(default=None, ge=1)
    requirement_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    requirement_projection_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    byte_estimate: int = Field(default=0, ge=0)
    token_estimate: int = Field(default=0, ge=0)
    content_digest: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_requirement_lineage(self) -> "AgentCanvasPromptContextSnapshotV2":
        lineage = (
            self.requirement_revision_id,
            self.requirement_revision_no,
            self.requirement_digest,
            self.requirement_projection_digest,
        )
        if any(item is not None for item in lineage) and any(item is None for item in lineage):
            raise ValueError("Prompt context Requirement lineage must be complete.")
        return self
