from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


V2ReferenceUsageRole = Literal[
    "product_identity",
    "character_identity",
    "scene_identity",
    "style_reference",
    "shot_cell_keyframe",
    "video_segment",
    "bgm_audio",
    "composition_clip",
    "free_reference",
]

V2ReferenceUsageSource = Literal[
    "explicit_slot_reference",
    "implicit_companion_reference",
    "dependency_slot_selected_asset",
    "asset_owner_relation",
    "free_asset_absorption",
    "workflow_input_asset",
]


class V2ReferenceUsage(BaseModel):
    asset_id: str
    usage_role: V2ReferenceUsageRole
    source: V2ReferenceUsageSource
    required: bool = False
    reason: str | None = None
    owner_node_id: str | None = None
    owner_item_id: str | None = None
    owner_slot_id: str | None = None

    @field_validator("asset_id", mode="after")
    @classmethod
    def strip_asset_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("asset_id must not be empty")
        return value


class V2ReferenceDropReason(BaseModel):
    asset_id: str
    reason_code: str
    message: str
    provider: str | None = None
    capability_field: str | None = None
    required: bool = False

    @field_validator("asset_id", "reason_code", "message", mode="after")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must not be empty")
        return value


class V2ReferenceAudit(BaseModel):
    audit_id: str
    workflow_id: str
    node_id: str
    item_id: str | None = None
    slot_id: str
    slot_type: str
    media_type: str
    generation_action: str
    slot_context_id: str | None = None
    slot_context_fingerprint: str | None = None
    provider_prompt_fingerprint: str | None = None
    allowed_reference_asset_ids: list[str] = Field(default_factory=list)
    forbidden_reference_asset_ids: list[str] = Field(default_factory=list)
    reference_policy: str = "best_effort"
    required_reference_asset_ids: list[str] = Field(default_factory=list)
    explicit_reference_asset_ids: list[str] = Field(default_factory=list)
    implicit_reference_asset_ids: list[str] = Field(default_factory=list)
    dependency_reference_asset_ids: list[str] = Field(default_factory=list)
    requested_reference_asset_ids: list[str] = Field(default_factory=list)
    submitted_reference_asset_ids: list[str] = Field(default_factory=list)
    dropped_reference_asset_ids: list[str] = Field(default_factory=list)
    drop_reasons: list[V2ReferenceDropReason] = Field(default_factory=list)
    reference_usage: list[V2ReferenceUsage] = Field(default_factory=list)
    provider: str | None = None
    provider_model: str | None = None
    provider_capability_snapshot: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator(
        "allowed_reference_asset_ids",
        "forbidden_reference_asset_ids",
        "required_reference_asset_ids",
        "explicit_reference_asset_ids",
        "implicit_reference_asset_ids",
        "dependency_reference_asset_ids",
        "requested_reference_asset_ids",
        "submitted_reference_asset_ids",
        "dropped_reference_asset_ids",
        mode="after",
    )
    @classmethod
    def clean_asset_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in (str(raw).strip() for raw in value) if item))


class V2ReferenceAuditValidationResult(BaseModel):
    valid: bool
    error_code: str | None = None
    error_message: str | None = None
    violations: list[str] = Field(default_factory=list)
