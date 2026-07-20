from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SUPPORTED_LIBRARY_ENTITY_TYPES = {
    "character",
    "scene",
    "storyboard_shot",
    "video_clip",
    "bgm",
    "product",
    "style_reference",
    "uploaded_reference",
}

SUPPORTED_LIBRARY_SEMANTIC_TYPES = {
    "character_main",
    "character_face_id",
    "character_three_view",
    "character_concept",
    "scene_main",
    "scene_multi_view",
    "storyboard_image",
    "storyboard_video",
    "product_reference",
    "product_image",
    "bgm",
    "final_video",
    "uploaded_reference",
    "style_reference",
}

SUPPORTED_ASSET_REFERENCE_ROLES = {
    "character_reference",
    "scene_reference",
    "style_reference",
    "bgm_reference",
    "video_reference",
    "storyboard_reference",
    "product_reference",
    "general_reference",
}


class LibraryEntity(BaseModel):
    entity_id: str
    entity_type: str
    display_name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)
    asset_ids: list[str] = Field(default_factory=list)
    reuse_policy: dict[str, Any] = Field(default_factory=dict)
    is_archived: bool = False
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LibraryAsset(BaseModel):
    asset_id: str
    entity_id: str
    asset_type: str = ""
    media_type: str = ""
    type: str = ""
    kind: str = ""
    semantic_type: str
    uri: str
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    is_archived: bool = False
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetLibraryCreateEntityRequest(BaseModel):
    source_workflow_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    source_entity_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    entity_type: str = Field(min_length=1)
    asset_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reuse_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetReference(BaseModel):
    reference_source: Literal["asset_library", "canvas_asset"] | None = None
    entity_id: str | None = Field(default=None, min_length=1)
    asset_id: str | None = Field(default=None, min_length=1)
    display_name: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    mention_text: str | None = None
    role: str | None = None
    use_as_prompt: bool = True
    lock_identity: bool = False
    allow_style_transfer: bool = False
    is_primary: bool | None = None
    reference_mode: str | None = None
    target_node_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_reference_source(self) -> "AssetReference":
        if self.reference_source is None:
            if self.entity_id:
                self.reference_source = "asset_library"

        if self.reference_source == "asset_library":
            if not self.entity_id:
                raise ValueError("asset_library reference requires entity_id")
            if self.asset_id:
                self.asset_ids = [
                    *([self.asset_id] if self.asset_id not in self.asset_ids else []),
                    *self.asset_ids,
                ]
        elif self.reference_source == "canvas_asset":
            if not self.asset_id:
                raise ValueError("canvas_asset reference requires asset_id")
            self.asset_ids = [self.asset_id]
        else:
            raise ValueError("reference_source must be asset_library or canvas_asset")
        return self


class ProviderCapability(BaseModel):
    provider: str
    media_type: str = ""
    supports_image_reference: bool = False
    supports_multi_image_reference: bool = False
    supports_video_reference: bool = False
    supports_audio_reference: bool = False
    supports_identity_lock: bool = False
    supports_style_reference: bool = False
    max_reference_assets: int = 0
    supported_reference_semantic_types: list[str] = Field(default_factory=list)
    node_types: list[str] = Field(default_factory=list)


class ReferencePolicyResult(BaseModel):
    reference_mode: str = "strict"
    provider: str
    accepted_assets: list[dict[str, Any]] = Field(default_factory=list)
    prompt_only_assets: list[dict[str, Any]] = Field(default_factory=list)
    rejected_assets: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    reference_plan: dict[str, Any] = Field(default_factory=dict)


class AssetLibraryPatchEntityRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    tags: list[str] | None = None
    reuse_policy: dict[str, Any] | None = None
    is_archived: bool | None = None


class AssetLibraryAssetSummary(BaseModel):
    asset_id: str
    asset_type: str
    media_type: str = ""
    type: str = ""
    kind: str = ""
    semantic_type: str
    uri: str
    mime_type: str | None = None
    is_archived: bool = False


class AssetLibraryEntitySummary(BaseModel):
    entity_id: str
    entity_type: str
    display_name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    assets: list[AssetLibraryAssetSummary] = Field(default_factory=list)
    is_archived: bool = False
    updated_at: str


class AssetLibraryEntityDetailResponse(BaseModel):
    entity: LibraryEntity
    assets: list[LibraryAsset] = Field(default_factory=list)


class AssetLibraryListResponse(BaseModel):
    entities: list[AssetLibraryEntitySummary] = Field(default_factory=list)


class AssetLibraryCreateEntityResponse(BaseModel):
    entity_id: str
    asset_ids: list[str] = Field(default_factory=list)
    entity: LibraryEntity
