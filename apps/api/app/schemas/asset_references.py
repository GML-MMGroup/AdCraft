from typing import Any, Literal

from pydantic import BaseModel, Field


ReferenceSource = Literal["asset_library", "canvas_asset"]


class AssetReferencePreviewAsset(BaseModel):
    asset_id: str
    uri: str | None = None
    local_path: str | None = None
    public_url: str | None = None
    mime_type: str | None = None


class AssetReferenceSuggestionItem(BaseModel):
    reference_source: ReferenceSource
    entity_id: str | None = None
    asset_id: str | None = None
    display_name: str
    entity_type: str
    semantic_types: list[str] = Field(default_factory=list)
    suggested_role: str
    preview_asset: AssetReferencePreviewAsset | None = None
    linked_canvas_asset_ids: list[str] = Field(default_factory=list)
    scope: str = "project"
    workspace_id: str | None = None
    owner_user_id: str | None = None
    visibility: str = "private"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetReferenceSuggestResponse(BaseModel):
    items: list[AssetReferenceSuggestionItem] = Field(default_factory=list)
