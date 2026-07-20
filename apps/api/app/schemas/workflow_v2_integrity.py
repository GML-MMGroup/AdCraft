from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class V2PlanningConstraints(BaseModel):
    requested_product_count: int | None = None
    requested_character_count: int | None = None
    requested_scene_count: int | None = None
    requested_scene_styles: list[str] = Field(default_factory=list)
    requested_shot_count: int | None = None
    duration_seconds: int
    aspect_ratio: str
    source_map: dict[str, str] = Field(default_factory=dict)


class V2GenerationIntegrityAudit(BaseModel):
    slot_contract: str
    semantic_boundary_passed: bool
    forbidden_terms_removed: list[str] = Field(default_factory=list)
    forbidden_terms_detected: list[str] = Field(default_factory=list)
    reference_scope: str
    source_prompt_hash: str
    validated_prompt_hash: str
    error_code: str | None = None
    message: str | None = None
    stage: str = "provider_prompt_compilation"
    node_id: str | None = None
    item_id: str | None = None
    slot_id: str | None = None
    slot_type: str | None = None
    boundary_scope: str | None = None
    offending_provider_prompt: str | None = None
    offending_reference_asset_ids: list[str] = Field(default_factory=list)


class V2SlotSemanticContract(BaseModel):
    slot_type: str
    allowed_subjects: list[str] = Field(default_factory=list)
    forbidden_subjects: list[str] = Field(default_factory=list)
    allowed_reference_roles: list[str] = Field(default_factory=list)
    composition_layer: Literal["asset", "storyboard", "video", "audio", "timeline"]
