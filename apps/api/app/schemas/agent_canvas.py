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


CanvasNodeTypeV2 = Literal["text", "script", "image", "video", "audio", "editing"]
CanvasNodeStatusV2 = Literal["draft", "working", "ready", "failed"]
CanvasBindingKindV2 = Literal[
    "brief_context",
    "script_context",
    "image_reference",
    "video_reference",
    "audio_reference",
]
ProjectAssetMediaTypeV2 = Literal["image", "video", "audio"]
ProjectAssetSourceTypeV2 = Literal[
    "upload",
    "generated",
    "recommended",
    "library",
    "editing_export",
]
ImageLibraryCategoryV2 = Literal["character", "scene", "prop"]


class _AgentCanvasModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanvasPositionV2(_AgentCanvasModel):
    x: float
    y: float


class CanvasNodeErrorV2(_AgentCanvasModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool


class CanvasNodeCreateRequestV2(_AgentCanvasModel):
    node_type: CanvasNodeTypeV2
    semantic_role: str = Field(min_length=1)
    role_contract_version: Literal["ad-media-role-v1"] = "ad-media-role-v1"
    title: str = Field(min_length=1)
    summary_prompt: str | None = None
    generation_prompt: str | None = None
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    model_id: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    position: CanvasPositionV2
    clone_inputs_from_node_id: str | None = None
    source_asset_id: str | None = None
    video_skill_run_id: str | None = None


class CanvasNodePatchRequestV2(_AgentCanvasModel):
    title: str | None = Field(default=None, min_length=1)
    summary_prompt: str | None = None
    generation_prompt: str | None = None
    structured_content: dict[str, JsonValue] | None = None
    model_id: str | None = None
    parameters: dict[str, JsonValue] | None = None
    position: CanvasPositionV2 | None = None


class ProjectCreateRequestV2(_AgentCanvasModel):
    name: str = Field(min_length=1)
    description: str = ""
    video_skill_id: str | None = None
    video_skill_version: str | None = None


class CanvasNodeV2(_AgentCanvasModel):
    node_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    node_type: CanvasNodeTypeV2
    semantic_role: str = Field(min_length=1)
    role_contract_version: Literal["ad-media-role-v1"] = "ad-media-role-v1"
    title: str = Field(min_length=1)
    status: CanvasNodeStatusV2
    summary_prompt: str | None = None
    generation_prompt: str | None = None
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    model_id: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    prompt_context_snapshot_id: str | None = None
    output_asset_id: str | None = None
    video_skill_run_id: str | None = None
    position: CanvasPositionV2
    revision: int = Field(ge=1)
    error: CanvasNodeErrorV2 | None = None
    created_at: datetime
    updated_at: datetime

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
    kind: Literal["node"] = "node"
    node_id: str = Field(min_length=1)


class CanvasBindingSourceImageAssetV2(_AgentCanvasModel):
    kind: Literal["image_asset"] = "image_asset"
    asset_id: str = Field(min_length=1)


CanvasBindingSourceV2 = Annotated[
    CanvasBindingSourceNodeV2 | CanvasBindingSourceImageAssetV2,
    Field(discriminator="kind"),
]


class CanvasBindingCreateRequestV2(_AgentCanvasModel):
    source: CanvasBindingSourceV2
    target_node_id: str = Field(min_length=1)
    binding_kind: CanvasBindingKindV2
    required: bool = True
    display_order: int = Field(default=0, ge=0)


class CanvasBindingV2(_AgentCanvasModel):
    binding_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    source: CanvasBindingSourceV2
    target_node_id: str = Field(min_length=1)
    binding_kind: CanvasBindingKindV2
    required: bool
    display_order: int = Field(ge=0)
    created_at: datetime


class ProjectAssetSummaryV2(_AgentCanvasModel):
    asset_id: str = Field(min_length=1)
    media_type: ProjectAssetMediaTypeV2
    source_type: ProjectAssetSourceTypeV2
    display_name: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    status: Literal["ready", "unavailable"]
    preview_url: str | None = None
    media_url: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    checksum: str = Field(min_length=1)

    @field_validator("preview_url", "media_url")
    @classmethod
    def validate_browser_safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith(("/api/", "https://", "http://")):
            return value
        raise ValueError("Asset URLs must be browser-safe.")


class AgentCanvasWorkflowV2(_AgentCanvasModel):
    workflow_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    workflow_schema_version: Literal[2] = 2
    canvas_model: Literal["agent_canvas_v1"] = "agent_canvas_v1"
    revision: int = Field(ge=1)
    nodes: tuple[CanvasNodeV2, ...] = ()
    bindings: tuple[CanvasBindingV2, ...] = ()
    assets: tuple[ProjectAssetSummaryV2, ...] = ()


class ProjectCreateResponseV2(AgentCanvasWorkflowV2):
    pass


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
    source_kind: Literal["node"] = "node"
    source_node_id: str = Field(min_length=1)
    source_node_revision: int = Field(ge=1)
    binding_kind: Literal["brief_context", "script_context"]
    document_kind: Literal["text", "script"]
    content: str
    content_hash: str = Field(min_length=1)


class ResolvedMediaInputSnapshotV2(_AgentCanvasModel):
    snapshot_type: Literal["media"] = "media"
    source_kind: Literal["node", "image_asset"]
    source_node_id: str | None = None
    source_node_revision: int | None = Field(default=None, ge=1)
    binding_kind: Literal["image_reference", "video_reference", "audio_reference"]
    asset_id: str = Field(min_length=1)
    media_type: ProjectAssetMediaTypeV2
    asset_checksum: str = Field(min_length=1)
    access_descriptor: StorageAccessDescriptorV2

    @model_validator(mode="after")
    def validate_source_identity(self) -> "ResolvedMediaInputSnapshotV2":
        if self.source_kind == "node":
            if self.source_node_id is None or self.source_node_revision is None:
                raise ValueError("Node media snapshots require source node identity.")
        elif self.source_node_id is not None or self.source_node_revision is not None:
            raise ValueError("Image asset snapshots cannot include a source node.")
        return self


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
    created_at: datetime
