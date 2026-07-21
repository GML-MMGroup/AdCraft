from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AssetType = Literal["image", "video", "audio"]
AssetRole = Literal["product", "character", "scene", "reference"]
AssetPromptTarget = Literal["product_design", "character_design", "scene_design"]
InputModality = Literal["text_only", "text_image", "text_video", "text_image_video"]


class WorkflowAssetReference(BaseModel):
    asset_id: str = Field(min_length=1, max_length=80)
    asset_type: AssetType
    media_type: AssetType | None = None
    type: AssetType | None = None
    kind: AssetType | None = None
    asset_role: AssetRole = "reference"
    filename: str = Field(min_length=1, max_length=255)
    display_name: str | None = None
    semantic_type: str | None = None
    mime_type: str = Field(min_length=1, max_length=120)
    local_path: str = Field(min_length=1, max_length=500)
    public_url: str | None = None
    use_as_prompt: bool = False
    prompt_targets: list[AssetPromptTarget] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt_targets")
    @classmethod
    def deduplicate_prompt_targets(
        cls,
        targets: list[AssetPromptTarget],
    ) -> list[AssetPromptTarget]:
        return list(dict.fromkeys(targets))


class AssetUploadResponse(WorkflowAssetReference):
    size_bytes: int = Field(ge=0)
    library_entity_id: str | None = None
    library_asset_ids: list[str] = Field(default_factory=list)
    library_entity: dict[str, Any] | None = None
    library_assets: list[dict[str, Any]] = Field(default_factory=list)


class AssetUploadBatchResponse(BaseModel):
    assets: list[AssetUploadResponse] = Field(default_factory=list)
    library_entity_id: str | None = None
    library_asset_ids: list[str] = Field(default_factory=list)
    library_entity: dict[str, Any] | None = None
    library_assets: list[dict[str, Any]] = Field(default_factory=list)


class AssetListResponse(BaseModel):
    assets: list[AssetUploadResponse]


def default_prompt_targets_for_role(asset_role: AssetRole) -> list[AssetPromptTarget]:
    if asset_role == "product":
        return ["product_design", "scene_design"]
    if asset_role == "character":
        return ["character_design", "scene_design"]
    if asset_role == "scene":
        return ["scene_design"]
    return ["product_design", "character_design", "scene_design"]
