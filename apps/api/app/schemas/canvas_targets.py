from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CanvasTargetType = Literal["node", "item", "asset"]
CanvasTargetIntentScope = Literal["single", "downstream", "all_in_node"]
CanvasTargetSource = Literal[
    "mention",
    "selected_node",
    "selected_item",
    "selected_asset",
    "inferred",
    "memory_focus",
]


class CanvasTargetReference(BaseModel):
    target_type: CanvasTargetType
    node_id: str | None = None
    node_type: str | None = None
    item_id: str | None = None
    asset_id: str | None = None
    semantic_type: str | None = None
    intent_scope: CanvasTargetIntentScope = "single"
    mention_text: str | None = None
    source: CanvasTargetSource = "mention"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "node_id",
        "node_type",
        "item_id",
        "asset_id",
        "semantic_type",
        "mention_text",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_required_identity(self) -> "CanvasTargetReference":
        if self.target_type == "node" and not self.node_id:
            raise ValueError("node target requires node_id")
        if self.target_type == "item" and (not self.node_id or not self.item_id):
            raise ValueError("item target requires node_id and item_id")
        if self.target_type == "asset" and not self.asset_id:
            raise ValueError("asset target requires asset_id")
        return self


class NormalizedCanvasTarget(BaseModel):
    workflow_id: str
    target_type: CanvasTargetType
    node_id: str | None = None
    node_type: str | None = None
    item_id: str | None = None
    asset_id: str | None = None
    semantic_type: str | None = None
    intent_scope: CanvasTargetIntentScope = "single"
    display_name: str | None = None
    source: CanvasTargetSource = "mention"
    resolved: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
